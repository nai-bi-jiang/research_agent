"""
tools/sentiment_tool.py —— Agent 情感分析工具(并入的情感分析服务)

作为「漫研」Agent 的工具之一, 由编排层 tool_node 在用户上传评论数据时调用:
    输入: 评论文本列表(来自评论接入层提取/素材)
    输出: 情感分布统计 + 抽样示例的素材文本(报告必须溯源引用)

★ 安全与合规: 本工具只处理"文本内容"本身, 不接收/不存储任何账号类信息;
  模型不可用时返回【工具异常】说明文字(不中断调研主流程, 由报告如实说明)。

对外函数:
    sentiment_analyzer(comment_texts: list[str]) -> str
        批量情感分类 + 聚合统计素材文本(与 search_tool 一致的"只返回字符串"约定)
    analyze_comments_summary(comment_texts: list[str]) -> str
        同 sentiment_analyzer 的别名(兼容性)
"""
from typing import List


def _normalize_inputs(comment_texts) -> List[str]:
    """兼容多种输入形态: list / 单个字符串 / None。"""
    if comment_texts is None:
        return []
    if isinstance(comment_texts, str):
        return [comment_texts]
    return [str(t) for t in comment_texts if str(t or "").strip()]


def sentiment_analyzer(comment_texts) -> str:
    """批量评论情感分析 → 聚合素材文本(只返回字符串, 不抛异常)。

    工具约定: 无论成功失败都返回文本; 失败文本以【工具异常】/【提示】开头,
    由上层作为一条素材记录, 不中断调研主流程。
    """
    texts = _normalize_inputs(comment_texts)
    if not texts:
        return "【提示】sentiment_analyzer: 没有收到可分析的评论文本(参数为空或全为空白)。"
    from sentiment.service import get_sentiment_service

    service = get_sentiment_service()
    if service is None:
        from sentiment.service import get_sentiment_service_error

        return (f"【工具异常】sentiment_analyzer: 情感分析服务初始化失败"
                f"({get_sentiment_service_error() or '未知原因'})。")
    return service.summarize(texts)


# 别名(与 search_tool 命名风格一致: 工具名即函数名)
analyze_comments_summary = sentiment_analyzer
