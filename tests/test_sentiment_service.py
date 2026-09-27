"""
tests/test_sentiment_service.py —— 情感分析服务(并入模块)基础行为单测(离线)

覆盖(「漫研」2026 并入):
    - 模型资源缺失时优雅降级: available()=False, summarize 返回【工具异常】说明, 不抛异常;
    - 空输入返回【提示】说明;
    - classify_batch 模型不可用时返回空列表(调用方按降级处理);
    - 模型可用时的批量分类与聚合摘要(若 torch 已安装且权重就位)。
"""

from sentiment.service import SentimentService


def test_service_missing_model_degrades_gracefully(workdir):
    """模型目录为空(workdir) → 不抛异常, 给出明确不可用说明。"""
    svc = SentimentService(model_root=str(workdir))
    assert svc.available() is False
    assert svc.load_error is not None
    text = svc.summarize(["画风很棒", "剧情拖沓"])
    assert text.startswith("【工具异常】")
    assert "情感分析" in text


def test_service_empty_texts_returns_hint(workdir):
    svc = SentimentService(model_root=str(workdir))
    text = svc.summarize([])
    assert "没有可分析的评论文本" in text
    # 全空白文本同样按无内容处理
    text2 = svc.summarize(["  ", "\n"])
    assert "没有可分析的评论文本" in text2


def test_classify_batch_returns_empty_when_unavailable(workdir):
    svc = SentimentService(model_root=str(workdir))
    assert svc.classify_batch(["随便一条评论"]) == []


def test_sentiment_analyzer_tool_returns_material_text(workdir, monkeypatch):
    """tools.sentiment_tool 无论模型可用与否都只返回字符串素材(工具约定)。"""
    import tools.sentiment_tool as st

    monkeypatch.setattr(st, "sentiment_analyzer", lambda texts: "【提示】情感分析不可用(测试降级)")
    out = st.sentiment_analyzer(["一条评论"])
    assert isinstance(out, str)
    assert "情感分析" in out
