"""
core/comment_ingest.py —— 评论数据合规接入层(去标识化)

★ 安全与合规设计(项目底线):
    本项目对"用户提供的评论数据"只做两件事: ①只保留评论文本用于情感分析/统计;
    ②一律丢弃账号类信息(昵称/用户名/头像/手机号/ID/IP/邮箱等), 不做任何存储与展示。
    数据来源以"用户主动提供"(上传 CSV / 粘贴文本)为主; 本模块不包含任何
    爬虫/批量抓取逻辑, 项目内也不得新增绕过平台防护的抓取代码。

对外函数:
    deidentify(df) -> df                删除账号/隐私列, 只保留评论文本列
    extract_comments(df) -> list[str]   提取评论文本列表(清洗+去空, 可抽样)
    parse_comments_text(text) -> list[str]  解析粘贴文本为评论列表(供注入 state.comments)
    ingest_comments_file(path, max_sample=8000) -> (素材文本, 统计dict)
        读取 CSV 评论文件 → 去标识化 → 统计 → 生成素材文本(供 Agent 报告溯源)
    ingest_comments_text(text, max_sample=8000) -> (素材文本, 统计dict)
        解析粘贴的评论文本(每行一条 / 支持 "|" 分隔)
"""
import os
import re
from typing import Dict, List, Tuple

# 账号/隐私类列名(命中即删除): 中英文 + 常见变体
_PRIVACY_COL_PATTERNS = (
    "昵称", "用户名", "用户", "账号", "手机", "电话", "邮箱", "ip", "地址",
    "头像", "id", "uid", "userId", "user_id", "author", "name", "avatar",
    "phone", "email", "vip", "等级", "粉丝", "点赞数", "点赞", "收藏", "评论数",
    "回复数", "时间", "日期", "location", "地区", "城市", "设备", "型号",
)
_PRIVACY_RE = re.compile("|".join(re.escape(p.lower()) for p in _PRIVACY_COL_PATTERNS))

_TEXT_COL_PATTERNS = ("评论内容", "评论", "内容", "评语", "comment", "content",
                      "text", "review", "body", "message", "评价")
_TEXT_RE = re.compile("|".join(re.escape(p.lower()) for p in _TEXT_COL_PATTERNS))


def deidentify(df) -> "object":
    """删除账号/隐私类列(评论分析只保留文本, 不保留任何可关联到个人的信息)。

    :param df: pandas DataFrame
    :return: 删除隐私列后的 DataFrame
    """
    drop_cols = []
    for col in df.columns:
        name = str(col).strip().lower()
        if _PRIVACY_RE.search(name):
            drop_cols.append(col)
    if drop_cols:
        df = df.drop(columns=drop_cols)
    return df


_NUM_RE = re.compile(r"^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?$")


def _is_numeric_column(series) -> bool:
    """判断列是否近似纯数字列(评论文本列不可能是纯数字)。

    抽样前 50 个非空值: 若 >90% 可解析为纯数字, 视为数值列跳过。
    """
    sample = series.dropna().astype(str).str.strip().head(50)
    if len(sample) == 0:
        return True
    numeric = sum(1 for v in sample if _NUM_RE.fullmatch(v))
    return numeric / len(sample) > 0.9


def detect_text_column(df) -> Tuple[str, float]:
    """启发式定位评论文本列。

    优先: 列名命中"评论/内容/text/content/comment"等关键词;
    其次: 非纯数字文本列中平均长度最长的列(评论文本通常最长)。
    返回 (列名, 置信度 0~1); 找不到时返回 ("", 0)。
    """
    if df.shape[1] == 0:
        return "", 0.0
    # 1) 列名关键词匹配
    best_name, best_score = "", 0.0
    for col in df.columns:
        name = str(col).strip().lower()
        if _TEXT_RE.search(name):
            score = 0.95 if ("评论" in name or "comment" in name) else 0.85
            if score > best_score:
                best_name, best_score = str(col), score
    if best_name:
        return best_name, best_score
    # 2) 兜底: 非纯数字文本列中样本平均长度最长者
    best_avg = -1.0
    for col in df.columns:
        try:
            if _is_numeric_column(df[col]):
                continue  # 数值列(销量/金额/年份等)不可能是评论文本
            lens = df[col].astype(str).str.len()
            if len(lens) == 0:
                continue
            avg = float(lens.mean())
            if avg > best_avg:
                best_avg, best_name = avg, str(col)
        except Exception:  # noqa: BLE001 —— 非文本列跳过
            continue
    return (best_name, 0.6) if best_name else ("", 0.0)


def _clean_comment(text) -> str:
    """清洗单条评论(去空白/URL/控制字符; 截断过长评论)。"""
    from sentiment.preprocess import clean_text

    s = clean_text(str(text or ""))
    return s[:500]  # 超长评论截断, 避免注入/噪音


def extract_comments(df, max_sample: int = 8000) -> List[str]:
    """提取评论文本列表(清洗+去空)。max_sample 控制单次分析上限(成本控制)。"""
    col, _ = detect_text_column(df)
    if not col:
        return []
    comments = [_clean_comment(v) for v in df[col].tolist()]
    comments = [c for c in comments if c]
    # 抽样: 超量时均匀抽样, 保证分布代表性(固定种子可复现)
    if len(comments) > max_sample:
        step = len(comments) / max_sample
        comments = [comments[int(i * step)] for i in range(max_sample)]
    return comments


def _build_material(comments: List[str], source_desc: str,
                    stats: Dict) -> Tuple[str, Dict]:
    """生成素材文本(统计 + 抽样示例, 供 Agent 报告引用与溯源)。"""
    total = len(comments)
    stats = {
        "total": total,
        "source": source_desc,
        "sample_size": len(comments),
        "dropped_privacy": stats.get("dropped_privacy", 0),
    }
    if total == 0:
        return (f"【提示】评论数据接入: {source_desc} 中没有可分析的评论文本"
                "(文件为空/没有评论文本列/全部为空文本)。", stats)
    lines = [
        f"【素材-评论数据】来源: {source_desc}",
        f"共 {total} 条评论(已去标识化: 不保留昵称/账号/IP 等个人信息, 仅文本用于分析)",
    ]
    sample_n = min(10, total)
    lines.append(f"抽样前 {sample_n} 条(供阅读与后续归因):")
    for i, c in enumerate(comments[:sample_n], start=1):
        lines.append(f"[{i}] {c}")
    return "\n".join(lines), stats


def load_comments(path: str, max_sample: int = 8000) -> Tuple[List[str], Dict]:
    """读取 CSV 评论文件 → 去标识化 → 提取评论文本列表(供 state.comments)。

    与 ingest_comments_file 的区别: 本函数直接返回"评论文本列表"本身(不生成素材文本),
    供 main.py / server.py 在任务开始时把评论注入 Agent State(仅文本, 已去标识化)。
    返回 (评论列表, 统计dict); 文件不可读/无文本列时返回 ([], stats)。
    """
    import pandas as pd

    df = None
    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb18030", "latin1"):
        try:
            df = pd.read_csv(path, encoding=encoding)
            break
        except Exception:  # noqa: BLE001
            continue
    if df is None or df.shape[1] == 0 or df.shape[0] == 0:
        return [], {"total": 0, "source": str(path), "sample_size": 0, "dropped_privacy": 0}
    before_cols = df.shape[1]
    df = deidentify(df)
    dropped = before_cols - df.shape[1]
    comments = extract_comments(df, max_sample=max_sample)
    return comments, {"total": len(df), "source": str(path), "sample_size": len(comments),
                      "dropped_privacy": dropped}


def ingest_comments_file(path: str, max_sample: int = 8000,
                         head_only: bool = False) -> Tuple[str, Dict]:
    """读取 CSV 评论文件 → 去标识化 → 统计 → 素材文本。

    :param path:      CSV 文件路径
    :param max_sample: 单次分析上限(成本控制)
    :param head_only:  仅做结构预览(不提取全文), 供 UI 预检
    :return: (素材文本, 统计dict)
    """
    import pandas as pd

    df = None
    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb18030", "latin1"):
        try:
            df = pd.read_csv(path, encoding=encoding)
            break
        except Exception:  # noqa: BLE001
            continue
    if df is None:
        return ("【工具异常】评论文件读取失败: 无法识别编码/格式(支持 UTF-8/GBK 的 CSV)。",
                {"total": 0, "source": str(path), "sample_size": 0, "dropped_privacy": 0})
    if df.shape[1] == 0 or df.shape[0] == 0:
        return ("【提示】评论文件为空(0 行)。", {"total": 0, "source": str(path),
                "sample_size": 0, "dropped_privacy": 0})

    before_cols = df.shape[1]
    df = deidentify(df)
    dropped = before_cols - df.shape[1]

    if head_only:
        col, conf = detect_text_column(df)
        preview = df.head(20).to_string(index=False, max_colwidth=40)
        text = (f"【素材-评论文件预览】文件: {os.path.basename(str(path))}\n"
                f"行数: {len(df)}  | 列数: {df.shape[1]} | 已删除隐私列: {dropped}\n"
                f"识别到的评论文本列: {col if col else '(未识别, 请检查列名)'}\n"
                f"前 20 行预览:\n{preview}")
        return text, {"total": len(df), "source": str(path), "sample_size": len(df),
                      "dropped_privacy": dropped}

    comments, stats = load_comments(path, max_sample=max_sample)
    stats = dict(stats)
    stats["dropped_privacy"] = dropped
    return _build_material(comments, f"上传文件 {os.path.basename(str(path))}", stats)


def parse_comments_text(text: str, max_sample: int = 8000) -> List[str]:
    """从粘贴文本解析评论文本列表(每行一条, 或空白/逗号/竖线分隔)。

    与 ingest_comments_text 的区别: 本函数直接返回"评论文本列表"(不生成素材文本),
    供 main.py / server.py 把粘贴评论注入 Agent State(仅文本, 已去标识化)。
    空输入/全空白返回 []。
    """
    raw = str(text or "")
    parts = [p.strip() for p in re.split(r"[\n\r|;；]+", raw) if p.strip()]
    comments = [_clean_comment(p) for p in parts if _clean_comment(p)]
    if len(comments) > max_sample:
        step = len(comments) / max_sample
        comments = [comments[int(i * step)] for i in range(max_sample)]
    return comments


def ingest_comments_text(text: str, max_sample: int = 8000) -> Tuple[str, Dict]:
    """解析粘贴的评论文本(每行一条, 或空白/逗号/竖线分隔)。"""
    comments = parse_comments_text(text, max_sample=max_sample)
    return _build_material(comments, "用户粘贴的评论文本", {"dropped_privacy": 0})
