"""
sentiment/textcnn_model.py —— TextCNN 分类模型(自包含, 从原项目并入)

来源: text_classification/models/textcnn.py, 参数与原训练配置(configs/config.py)
一致(embed_dim=128 / num_filters=100 / filter_sizes=(2,3,4) / num_classes=3)。
为自包含并入, 本文件不再依赖原项目的 configs 包, 超参直接内联为模块常量。

结构:
    Embedding → 三种尺寸卷积核(2/3/4, 各 num_filters 个) → 全局最大池化
            → 拼接 → Dropout → 全连接分类头(3 类: 负向/中性/正向)
"""
import torch
import torch.nn as nn

# ---- 与原训练配置一致的模型超参(修改需同步重训) ----
EMBED_DIM = 128          # 词向量维度
NUM_FILTERS = 100        # 每种卷积核数量
FILTER_SIZES = (2, 3, 4)  # 卷积核尺寸(捕捉 2/3/4-gram 局部特征)
NUM_CLASSES = 3          # 分类数: 0=负向 1=中性 2=正向
DROPOUT = 0.3            # 分类头 dropout
MAX_LEN = 128            # 输入序列最大长度(与预处理 encode 一致)


class TextCNN(nn.Module):
    """TextCNN 分类器(多尺寸卷积核 + 全局最大池化)。"""

    def __init__(self, vocab_size: int):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, EMBED_DIM, padding_idx=0)
        self.convs = nn.ModuleList([
            nn.Conv1d(
                in_channels=EMBED_DIM,
                out_channels=NUM_FILTERS,
                kernel_size=k,
                padding=k // 2,  # 保持序列长度不变, 方便拼接后池化
            )
            for k in FILTER_SIZES
        ])
        total_filters = NUM_FILTERS * len(FILTER_SIZES)
        self.dropout = nn.Dropout(DROPOUT)
        self.fc = nn.Linear(total_filters, NUM_CLASSES)

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        # input_ids: (batch, seq_len)
        x = self.embedding(input_ids)          # (batch, seq_len, embed_dim)
        x = x.transpose(1, 2)                  # (batch, embed_dim, seq_len)
        conv_outs = []
        for conv in self.convs:
            h = torch.relu(conv(x))            # (batch, num_filters, seq_len)
            h = h.max(dim=2).values            # 全局最大池化
            conv_outs.append(h)
        x = torch.cat(conv_outs, dim=1)        # (batch, num_filters * 3)
        x = self.dropout(x)
        return self.fc(x)                      # (batch, num_classes)
