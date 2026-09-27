"""
tests/test_mangyan_graph.py —— 「漫研」改造点集成测试(离线, 注入假 LLM)

覆盖(2026 新增改造, 验证不改坏原图结构):
    - planner_node: 按任务类型注入 planner_hint(口碑监测 → 提及情感分析);
    - report_node: 按任务类型注入 report_hint(口碑监测 → 口碑周报结构);
    - tool_node: sentiment_analyzer 分支从 state.comments 取评论并产出素材
      (模型可用与否都不抛异常——工具约定);
    - tool_node: 无评论数据时给出明确错误素材(不静默)。
"""
import json

import core.tasks as core_tasks
from graph_builder import make_planner_node, make_report_node, make_tool_node


def _llm_result(content):
    return type("R", (), {"content": content})()


class _ScriptedLLM:
    """按脚本顺序返回 content; 记录每次 invoke 的消息列表。"""
    model_name = "mock-model"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.i = 0
        self.seen = []

    def invoke(self, messages):
        self.seen.append(messages)
        out = self.outputs[min(self.i, len(self.outputs) - 1)]
        self.i += 1
        return _llm_result(out)


def test_planner_system_prompt_injects_task_hint():
    """口碑监测: 规划节点系统提示词包含任务专用指令(且提示可调用情感分析)。"""
    llm = _ScriptedLLM([json.dumps({"sub_tasks": ["搜集评论情绪分布"]}, ensure_ascii=False)])
    node = make_planner_node(llm, task_type=core_tasks.TASK_REPUTATION)
    node({"user_query": "监测《某漫剧》的观众口碑"})
    system = llm.seen[0][0][1]
    assert "【口碑监测】" in system
    assert "sentiment_analyzer" in system


def test_report_system_prompt_injects_report_structure():
    llm = _ScriptedLLM(["报告内容"])
    node = make_report_node(llm, task_type=core_tasks.TASK_REPUTATION)
    node({"user_query": "q", "collected_info": ["素材一"]})
    system = llm.seen[0][0][1]
    assert "【口碑周报】" in system
    assert "被夸的点" in system and "被吐槽的点" in system


def test_tool_node_sentiment_analyzer_branch():
    """sentiment_analyzer 分支: 从 state.comments 取评论, 产出【素材-sentiment_analyzer】。"""
    llm = _ScriptedLLM([json.dumps({"tool": "sentiment_analyzer"}, ensure_ascii=False)])
    node = make_tool_node(llm, task_type=core_tasks.TASK_REPUTATION)
    out = node({
        "user_query": "q",
        "iteration_count": 0,
        "comments": ["画风很棒", "剧情拖沓"],
        "collected_info": [],
        "uploaded_files": [],
    })
    entries = out.get("collected_info") or []
    assert entries and "【素材-sentiment_analyzer】" in entries[0]
    assert "情感分析" in entries[0]  # 模型可用给统计、不可用给说明, 均含"情感分析"


def test_tool_node_sentiment_without_comments_returns_error_material():
    """没有评论数据时, sentiment_analyzer 必须给出明确错误素材而非静默。"""
    llm = _ScriptedLLM([json.dumps({"tool": "sentiment_analyzer"}, ensure_ascii=False)])
    node = make_tool_node(llm, task_type=core_tasks.TASK_REPUTATION)
    out = node({
        "user_query": "q",
        "iteration_count": 0,
        "comments": [],
        "collected_info": [],
        "uploaded_files": [],
    })
    entries = out.get("collected_info") or []
    assert entries and "需要评论数据" in entries[0]


def test_unknown_task_type_backward_compatible():
    """task_type 未知/None 时, 节点提示词不含任务指令(行为与旧版一致)。"""
    llm = _ScriptedLLM([json.dumps({"sub_tasks": ["通用搜索"]}, ensure_ascii=False)])
    node = make_planner_node(llm, task_type=None)
    node({"user_query": "任意主题"})
    system = llm.seen[0][0][1]
    assert "【口碑监测】" not in system
    assert "【选题调研】" not in system


def test_report_system_prompt_quality_contract():
    """报告提示词契约: 书面化转写 / 时间口径 / 数据局限声明 / 真实性标注(质量评分卡两项低分维度)。"""
    from graph_builder import _load_prompt
    text = _load_prompt("report_system.txt")
    for kw in ("书面语", "时间口径", "资料获取情况", "数据局限", "(推断)", "严禁编造"):
        assert kw in text, f"report_system.txt 缺少关键词: {kw}"


def test_tool_system_contains_worked_example():
    """工具提示词契约: 口碑监测完整调用序列示例(强制式 few-shot, 比建议性文字有效)。"""
    from graph_builder import _load_prompt
    text = _load_prompt("tool_system.txt")
    for kw in ("工作示例", "第 1 步", "sentiment_analyzer", "绝不跳过"):
        assert kw in text, f"tool_system.txt 缺少关键词: {kw}"


def test_rerun_report_with_guard_retries_on_fake_url():
    """引用护栏: 报告含素材中不存在的 URL 时, 自动用同批素材重生成一次。"""
    from graph_builder import rerun_report_with_guard
    materials = ["搜索来源: 博查\n链接: https://real.test/ok"]

    class _GoodLLM:
        model_name = "fake"

        def invoke(self, messages, **kw):
            # 重跑的那次生成即为干净报告(只引用素材中真实存在的 URL)
            return type("R", (), {"content": "好报告【素材1】（链接： https://real.test/ok)"})()

    final, retried, check = rerun_report_with_guard(
        "坏报告【素材1】（链接： https://fake.test/not-exist)",
        materials, "测试主题", _GoodLLM(), task_type=None, max_retries=1)
    assert retried == 1                       # 护栏确实触发了一次自动重生成
    assert "好报告" in final                   # 采用重跑后的干净报告
    assert check["invalid_urls"] == []
    assert check["all_valid"] is True


def test_rerun_guard_keeps_old_when_retry_still_bad():
    """护栏只重试 max_retries 次: 重跑后仍不干净时, 保留最新一版并如实报告, 不掩盖问题。"""
    from graph_builder import rerun_report_with_guard
    materials = ["链接: https://real.test/ok"]

    class _BadLLM:
        def invoke(self, messages, **kw):
            return type("R", (), {"content": "坏【素材1】（链接： https://fake.test/x)"})()

    final, retried, check = rerun_report_with_guard(
        "坏【素材1】（链接： https://fake.test/x)", materials, "主题",
        _BadLLM(), task_type=None, max_retries=1)
    assert retried == 1
    assert check["all_valid"] is False          # 如实报告: 重试后仍未通过
    assert check["invalid_urls"]                # 不把问题藏起来


def test_rerun_report_with_guard_keeps_clean_report():
    """报告本就干净时, 护栏不触发重跑。"""
    from graph_builder import rerun_report_with_guard
    materials = ["链接: https://a.test/x"]
    final, retried, check = rerun_report_with_guard(
        "结论【素材1】（链接： https://a.test/x)", materials, "主题",
        object(), task_type=None, max_retries=1)
    assert retried == 0
    assert "结论【素材1】" in final
    assert check["all_valid"] is True


def test_reflection_system_prompt_coverage_contract():
    """反思提示词契约: 素材覆盖均衡(引用偏少的素材优先深挖)。"""
    from graph_builder import _load_prompt
    text = _load_prompt("reflection_system.txt")
    for kw in ("素材覆盖均衡", "未被利用", "偏少利用"):
        assert kw in text, f"reflection_system.txt 缺少关键词: {kw}"


def test_reputation_tool_hint_mentions_comment_material_trigger():
    """口碑监测工具指令必须含『素材-评论数据』触发条件(模型据此感知评论存在并调用情感分析)。"""
    llm = _ScriptedLLM([json.dumps({"tool": "bocha_web_search", "query": "x"}, ensure_ascii=False)])
    node = make_tool_node(llm, task_type=core_tasks.TASK_REPUTATION)
    node({"user_query": "q", "iteration_count": 0, "collected_info": [], "uploaded_files": []})
    system = llm.seen[0][0][1]
    assert "素材-评论数据" in system
    assert "先调用 sentiment_analyzer" in system
