"""
tests/test_tasks.py —— 「漫研」内容行业任务注册表单测(离线)

覆盖(2026 新增):
    - 三大内容任务(选题调研/口碑监测/对标拆解)都具备 planner/tool/report 三套指令;
    - 未知/空任务类型回退通用调研(general), 向后兼容;
    - 任务标签映射完整。
"""
import core.tasks as tasks


def test_three_content_tasks_have_all_hints():
    """三大任务必须同时具备规划/工具/报告三套任务指令(否则提示词注入会失效)。"""
    for t in [tasks.TASK_TOPIC_RESEARCH, tasks.TASK_REPUTATION, tasks.TASK_BENCHMARK]:
        task = tasks.get_task(t)
        assert task["name"], t
        assert task["planner_hint"], t
        assert task["tool_hint"], t
        assert task["report_hint"], t
        assert "选题" in task["planner_hint"] or "口碑" in task["planner_hint"] \
            or "对标" in task["planner_hint"], t


def test_unknown_task_falls_back_to_general():
    assert tasks.normalize_task_type("not-a-task") == tasks.TASK_GENERAL
    assert tasks.normalize_task_type(None) == tasks.TASK_GENERAL
    assert tasks.normalize_task_type("") == tasks.TASK_GENERAL
    assert tasks.get_task("not-a-task") == tasks.get_task(tasks.TASK_GENERAL)


def test_valid_task_passthrough():
    for t in tasks.VALID_TASKS:
        assert tasks.normalize_task_type(t) == t


def test_task_labels_complete():
    for t in tasks.VALID_TASKS:
        assert tasks.TASK_LABELS[t]
