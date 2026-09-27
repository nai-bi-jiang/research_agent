"""
sentiment/service.py —— 情感分析服务(懒加载 + 优雅降级)

职责:
    1. 懒加载 TextCNN 模型(权重 + 词表, 进程级单例, 线程安全);
    2. classify_batch(texts): 批量分类, 返回每条 {label, label_name, probs};
    3. summarize(texts): 聚合为"素材文本"(正/中/负分布 + 抽样示例),
       供 Agent 工具调用后作为素材进入报告(报告强制溯源);
    4. ★ 安全降级: torch / jieba / 权重缺失或加载失败时, 返回明确说明文字,
       绝不抛断 Agent 主流程(情感分析是增强能力, 不是依赖)。

模型资源(并入时从原 text_classification 拷贝, 见 README「情感分析并入」):
    sentiment/models/textcnn.pt   TextCNN 权重(state_dict)
    sentiment/models/vocab.json    词表(含 <pad>=0 / <unk>=1)
路径可用环境变量 SENTIMENT_MODEL_ROOT 覆盖(默认本包 sentiment/models/)。
"""
import json
import os
import threading
from typing import List, Optional

LABELS = ["负向", "中性", "正向"]  # 与原项目一致: 0/1/2


def _default_model_root() -> str:
    """默认模型目录: 本包 sentiment/models/(随项目自包含)。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")


class SentimentService:
    """中文评论情感分析服务(懒加载, 线程安全)。

    用法:
        svc = SentimentService()
        svc.classify_batch(["画风很棒", "剧情太拖沓了"])   # 模型可用
        svc.summarize([...])                              # 聚合素材文本
    模型不可用时不抛异常: classify_batch 返回空列表, summarize 返回
    以【工具异常】/【提示】开头的说明文字(由 Agent 作为素材如实记录)。
    """

    def __init__(self, model_root: str | None = None):
        self._model_root = model_root or os.getenv("SENTIMENT_MODEL_ROOT", "") \
            or _default_model_root()
        self._model = None
        self._vocab: Optional[dict] = None
        self._lock = threading.Lock()
        self._load_error: Optional[str] = None

    # ---------------- 加载 ----------------
    def _ensure_loaded(self) -> None:
        """首次调用时加载模型(线程安全); 失败记录原因, 不抛出。"""
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            try:
                self._load()
            except Exception as exc:  # noqa: BLE001 —— 记录失败原因, 对外不抛
                self._load_error = f"{type(exc).__name__}: {exc}"

    def _load(self) -> None:
        try:
            import torch  # noqa: F401 —— 延迟导入: 未装 torch 时给出明确降级说明
        except ImportError:
            raise RuntimeError(
                "情感分析服务不可用: 未安装 torch。请执行 "
                "pip install torch --index-url https://download.pytorch.org/whl/cpu "
                "(或 pip install -r requirements.txt) 后重试。")
        import torch as _torch

        ckpt_path = os.path.join(self._model_root, "textcnn.pt")
        vocab_path = os.path.join(self._model_root, "vocab.json")
        for p in (ckpt_path, vocab_path):
            if not os.path.exists(p):
                raise RuntimeError(
                    f"情感分析模型资源缺失: {p}。请按 README「情感分析并入」"
                    "从原 text_classification 项目拷贝 textcnn.pt 与 vocab.json 到 "
                    f"sentiment/models/ 目录(或设置 SENTIMENT_MODEL_ROOT 指向模型目录)。")
        with open(vocab_path, encoding="utf-8") as f:
            vocab = json.load(f)
        from sentiment.textcnn_model import MAX_LEN, TextCNN

        model = TextCNN(vocab_size=len(vocab))
        model.load_state_dict(
            _torch.load(ckpt_path, map_location="cpu", weights_only=True))
        model.eval()
        self._model = model
        self._vocab = vocab
        self._max_len = MAX_LEN

    # ---------------- 编码 ----------------
    def _encode_text(self, text: str) -> Optional["object"]:
        """单条文本 → id 序列张量(与训练预处理对齐); 空文本返回 None。"""
        if self._vocab is None or self._model is None:
            return None
        from sentiment.preprocess import clean_text, encode, tokenize

        import torch

        cleaned = clean_text(text)
        if not cleaned:
            return None
        tokens = tokenize(cleaned)
        ids = encode(tokens, self._vocab, self._max_len)
        return torch.tensor([ids], dtype=torch.long)

    # ---------------- 对外接口 ----------------
    def available(self) -> bool:
        """模型是否可用(首次调用会触发加载)。"""
        self._ensure_loaded()
        return self._model is not None

    @property
    def load_error(self) -> Optional[str]:
        """模型不可用时的原因(供 UI/报告如实展示)。"""
        self._ensure_loaded()
        return self._load_error

    def classify_batch(self, texts: List[str]) -> List[dict]:
        """批量情感分类。模型不可用时返回空列表(调用方按降级处理)。

        返回: [{"label": 0/1/2, "label_name": "负向/中性/正向",
                 "probs": [负, 中, 正], "text": 原评论文本(截断), "clean": 清洗文本}]
        """
        self._ensure_loaded()
        if self._model is None or self._vocab is None:
            return []
        import torch

        out: List[dict] = []
        tensors = []
        valid_idx = []
        for i, t in enumerate(texts or []):
            x = self._encode_text(t)
            if x is not None:
                tensors.append(x)
                valid_idx.append(i)
        if not tensors:
            return []
        batch = torch.cat(tensors, dim=0)
        with torch.no_grad():
            logits = self._model(batch)
            probs_all = torch.softmax(logits, dim=1).tolist()
        for pos, idx in enumerate(valid_idx):
            probs = probs_all[pos]
            label = int(max(range(len(LABELS)), key=lambda i: probs[i]))
            out.append({
                "label": label,
                "label_name": LABELS[label],
                "probs": [round(p, 4) for p in probs],
                "text": str(texts[idx])[:200],
                "clean": str(texts[idx])[:200],
            })
        return out

    def summarize(self, texts: List[str], max_samples: int = 8) -> str:
        """聚合评论情感为"素材文本": 分布统计 + 抽样示例(供 Agent 报告引用)。

        模型不可用/无有效文本时返回以【提示】开头的说明文字(不抛异常)。
        """
        texts = [str(t or "") for t in (texts or [])]
        texts = [t for t in texts if t.strip()]
        if not texts:
            return "【提示】sentiment_analyzer: 没有可分析的评论文本(评论为空或清洗后无有效内容)。"
        self._ensure_loaded()
        if self._model is None:
            reason = self._load_error or "未知原因"
            return (f"【工具异常】sentiment_analyzer: 情感分析模型不可用({reason})。"
                    f"本次共 {len(texts)} 条评论未做自动情感分类; 可基于评论原文人工归纳, "
                    "或先修复模型加载问题后重试。")
        results = self.classify_batch(texts)
        if not results:
            return "【提示】sentiment_analyzer: 清洗后没有可分析的评论文本(全部为空/无效)。"

        from collections import Counter

        counts = Counter(r["label_name"] for r in results)
        total = len(results)
        lines = [
            f"情感分析模型: TextCNN(电商评论预训练权重, 3 分类: 负向/中性/正向)",
            f"共分析 {total} 条评论: 正向 {counts['正向']} 条({counts['正向']/total:.1%}), "
            f"中性 {counts['中性']} 条({counts['中性']/total:.1%}), "
            f"负向 {counts['负向']} 条({counts['负向']/total:.1%})",
        ]
        # 抽样示例(按类别均衡抽取, 便于 LLM 后续做方面级归因)
        seen = {k: 0 for k in LABELS}
        samples: List[str] = []
        for r in results:
            name = r["label_name"]
            if seen[name] >= max(1, max_samples // 3):
                continue
            seen[name] += 1
            samples.append(f"- [{name}] {r['clean']}")
        if samples:
            lines.append("抽样示例(每类至多 3 条, 供细粒度归因):")
            lines.extend(samples)
        lines.append("说明: 该模型为电商评论预训练, 迁移到内容行业评论后准确率会有偏差, "
                     "细粒度结论请结合 LLM 归因与人工复核(报告中请如实标注此局限)。")
        return "\n".join(lines)


# ============================ 进程级单例(与 memory/ 模块风格一致) ============================
_service: Optional[SentimentService] = None
_service_error: Optional[str] = None


def get_sentiment_service() -> Optional[SentimentService]:
    """返回进程级 SentimentService 单例; 模型不可用时仍返回实例(内部降级)。"""
    global _service, _service_error
    if _service is None:
        try:
            _service = SentimentService()
        except Exception as exc:  # noqa: BLE001 —— 构造失败仅记录, 返回 None
            _service_error = f"{type(exc).__name__}: {exc}"
            return None
    return _service


def get_sentiment_service_error() -> Optional[str]:
    """获取情感服务不可用的原因(供 UI/报告如实展示)。"""
    return _service_error
