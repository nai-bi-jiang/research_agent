"""
sentiment/preprocess.py —— 评论文本预处理(自包含, 从原项目并入)

来源: text_classification/scripts/preprocess.py 的 clean_text / tokenize / encode。
与原项目保持一致的清洗与分词逻辑(去 URL / emoji / 控制字符 / 合并空白,
jieba 分词), 保证训练时与推理时的预处理完全对齐。

★ 工程边界备注: jieba 未安装时降级为"字符级切分"(按空白与标点切词),
  模型效果会略降但不抛断; 安装 jieba 后自动恢复标准分词。
"""
import re

_JIEBA_AVAILABLE = False
try:
    import jieba  # noqa: F401 —— 延迟探测, 不在此处初始化词库

    _JIEBA_AVAILABLE = True
except Exception:  # noqa: BLE001 —— 未安装 jieba 时降级为字符切分
    _JIEBA_AVAILABLE = False

_WS_RE = re.compile(r"[\s\u3000]+")
_SPLIT_RE = re.compile(r"[，。！？、；：,.!?;:\s]+")


def clean_text(text: str) -> str:
    """文本清洗: 去 URL / emoji / 控制字符 / 合并空白(与原项目一致)。"""
    if not isinstance(text, str):
        return ""
    text = re.sub(r"https?://\S+|www\.\S+", "", text)                # 去 URL
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)  # 去 emoji
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)                       # 去控制字符
    text = _WS_RE.sub(" ", text)                                      # 合并空白
    return text.strip()


def tokenize(text: str) -> list:
    """jieba 分词; 未安装 jieba 时降级为按空白/标点切词。"""
    if _JIEBA_AVAILABLE:
        try:
            return [w for w in jieba.lcut(text) if w.strip()]
        except Exception:  # noqa: BLE001 —— 分词异常降级字符切分
            pass
    return [w for w in _SPLIT_RE.split(text or "") if w]


def encode(tokens: list, vocab: dict, max_len: int = 128) -> list:
    """token 列表转 id 序列并 padding/truncation 到 max_len(与原项目一致)。"""
    ids = [vocab.get(w, vocab["<unk>"]) for w in tokens]
    ids = ids[:max_len]
    ids = ids + [vocab["<pad>"]] * (max_len - len(ids))
    return ids
