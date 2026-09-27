"""
sentiment/ —— 中文评论情感分析服务(自包含并入模块)

来源: 原 text_classification 项目(电商评论三分类课程实验)并入本 Agent 项目,
作为「内容调研与口碑情报 Agent」的口碑分析工具。并入方式:
    - 模型代码(TextCNN 定义/预处理)迁入本包, 不再依赖外部项目路径;
    - 权重与词表: textcnn.pt + vocab.json 拷贝至 sentiment/models/(见部署说明);
    - 服务化: SentimentService 懒加载模型, 提供单条/批量分类与聚合摘要;
    - 安全降级: torch/jieba/权重缺失时返回明确说明, 绝不抛断 Agent 主流程。

对外接口(推荐):
    get_sentiment_service() -> SentimentService  进程级单例(懒加载)
    service.classify_batch(texts) -> list[dict]  每条: {label, label_name, probs}
    service.summarize(texts) -> str              聚合素材文本(供 Agent 报告引用)

依赖: torch(推理) + jieba(分词), 未安装时自动降级(README 有安装说明)。
"""
from sentiment.service import (
    SentimentService,
    get_sentiment_service,
    get_sentiment_service_error,
)

__all__ = [
    "SentimentService",
    "get_sentiment_service",
    "get_sentiment_service_error",
]
