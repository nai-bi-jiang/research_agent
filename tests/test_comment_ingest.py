"""
tests/test_comment_ingest.py —— 评论数据合规接入层单测(离线, 不触网不加载模型)

覆盖(「漫研」2026 新增模块):
    - deidentify: 删除昵称/用户ID/手机号等隐私列, 只保留评论文本;
    - detect_text_column: 按列名关键词识别评论列; 纯数字列(销量/年份)不得误判为评论;
    - load_comments: CSV 去标识化 + 提取评论; 无评论列的 CSV 返回空;
    - ingest_comments_text / ingest_comments_file: 素材文本与统计。
"""
import csv

import pandas as pd

import core.comment_ingest as ci


def _write_csv(path, rows, headers):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)


# =====================================================================
# 去标识化(安全底线)
# =====================================================================
def test_deidentify_drops_privacy_columns():
    df = pd.DataFrame({
        "昵称": ["用户A", "用户B"],
        "用户ID": ["u1", "u2"],
        "评论内容": ["画风很棒", "剧情拖沓"],
        "手机号": ["13800000000", "13900000000"],
    })
    out = ci.deidentify(df)
    assert "昵称" not in out.columns
    assert "用户ID" not in out.columns
    assert "手机号" not in out.columns
    assert "评论内容" in out.columns


def test_deidentify_keeps_anonymous_csv_unchanged():
    df = pd.DataFrame({"评论": ["a", "b"]})
    out = ci.deidentify(df)
    assert list(out.columns) == ["评论"]


# =====================================================================
# 评论列识别(关键词优先 / 纯数字列排除)
# =====================================================================
def test_detect_text_column_by_keyword():
    df = pd.DataFrame({"content": ["a", "b"], "id": [1, 2]})
    col, conf = ci.detect_text_column(df)
    assert col == "content"
    assert conf > 0.8  # 关键词命中: 非"评论/comment"精确词为 0.85 置信度


def test_numeric_columns_not_detected_as_comments():
    """销量/年份等纯数字列不得被误判为评论文本(防止一般 CSV 被当评论处理)。"""
    df = pd.DataFrame({"year": ["2023", "2024", "2025"], "sales": [100, 120, 150]})
    col, _ = ci.detect_text_column(df)
    assert col == ""


# =====================================================================
# load_comments: 去标识化 + 提取(workdir 由 tests/conftest.py 提供)
# =====================================================================
def test_load_comments_extracts_and_deidentifies(workdir):
    path = workdir / "comments.csv"
    _write_csv(path, [
        ["张三", "u1", "画风绝了，帧帧壁纸"],
        ["李四", "u2", "剧情节奏太慢了"],
        ["王五", "u3", "配音有点出戏"],
    ], ["昵称", "用户ID", "评论内容"])
    comments, stats = ci.load_comments(str(path))
    assert len(comments) == 3
    assert stats["dropped_privacy"] == 2
    # 只保留文本: 昵称/ID 不进入评论
    assert not any(("张三" in c or "u1" in c) for c in comments)


def test_load_comments_numeric_csv_returns_empty(workdir):
    path = workdir / "sales.csv"
    _write_csv(path, [["2023", 100], ["2024", 120], ["2025", 150]], ["year", "sales"])
    comments, stats = ci.load_comments(str(path))
    assert comments == []
    assert stats["sample_size"] == 0


# =====================================================================
# 素材文本与统计
# =====================================================================
def test_ingest_comments_text_parses_lines():
    material, stats = ci.ingest_comments_text("好评！\n剧情拖沓\n画风好看")
    assert stats["total"] == 3
    assert "已去标识化" in material
    assert "共 3 条评论" in material


def test_parse_comments_text_returns_comment_list():
    """粘贴文本解析必须返回"评论列表"本身(而非素材文本/字符列表), 供注入 state.comments。"""
    comments = ci.parse_comments_text("画风很棒\n剧情节奏太慢了\n配音出戏")
    assert comments == ["画风很棒", "剧情节奏太慢了", "配音出戏"]
    assert len(comments) == 3
    # 竖线/分号分隔也支持
    assert ci.parse_comments_text("好评 | 一般; 差评") == ["好评", "一般", "差评"]
    # 空/空白输入 → 空列表(调用方按"无评论"处理)
    assert ci.parse_comments_text("") == []
    assert ci.parse_comments_text("  \n  ") == []
    # 清洗: URL/超长/空白行被去除
    messy = ci.parse_comments_text("  https://example.com/x  \n好作品\n\n")
    assert messy == ["好作品"]


def test_ingest_comments_file_no_comment_column_returns_hint(workdir):
    path = workdir / "data.csv"
    _write_csv(path, [[1, 2], [3, 4]], ["a", "b"])
    material, stats = ci.ingest_comments_file(str(path))
    assert stats["total"] == 0
    assert "没有可分析的评论文本" in material


def test_load_comments_max_sample_caps(workdir):
    path = workdir / "many.csv"
    rows = [[f"评论内容{i}"] for i in range(100)]
    _write_csv(path, rows, ["评论内容"])
    comments, stats = ci.load_comments(str(path), max_sample=10)
    assert len(comments) == 10
    assert stats["total"] == 100
