"""
core/tasks.py —— 内容行业任务类型注册表(「漫研」内容调研与口碑情报 Agent)

本项目面向动漫/漫剧/短剧内容从业者, 提供三大核心任务 + 通用调研兜底:
    1. topic_research         选题调研    —— 帮创作者判断"做什么"
    2. reputation_monitoring   口碑监测    —— 帮创作者了解"做得怎么样"(并入情感分析)
    3. benchmark_analysis      对标拆解    —— 帮创作者看清"别人怎么做"
    4. general (缺省)          通用调研    —— 保留原 research_agent 的通用调研问答能力

每个任务定义: 任务名/一句话说明/规划器指令(planner_hint)/报告指令(report_hint)/
工具提示(tool_hint)。graph_builder 按 task_type 把对应指令注入各节点系统提示词,
在不改动 LangGraph 图结构的前提下, 让同一套编排流程适配不同任务。
"""
from typing import Optional

# ---------------- 任务类型常量 ----------------
TASK_TOPIC_RESEARCH = "topic_research"
TASK_REPUTATION = "reputation_monitoring"
TASK_BENCHMARK = "benchmark_analysis"
TASK_GENERAL = "general"

VALID_TASKS = {TASK_TOPIC_RESEARCH, TASK_REPUTATION, TASK_BENCHMARK, TASK_GENERAL}

# ---------------- 任务定义 ----------------
TASKS = {
    TASK_TOPIC_RESEARCH: {
        "name": "选题调研",
        "desc": "帮内容创作者判断一个题材/方向值不值得做: 市场热度、同类作品表现、观众讨论、差异化空间",
        "planner_hint": (
            "当前任务: 【选题调研】。请围绕以下维度拆解子任务(每个子任务可直接当搜索关键词): "
            "①该题材/方向的近期市场热度与平台榜单表现; ②同类作品(动漫/漫剧/短剧)的近期表现与口碑; "
            "③目标观众在讨论什么、期待什么(可搜索相关社区/平台讨论); ④差异化机会(已有作品没做好的地方)。"
        ),
        "tool_hint": (
            "当前任务: 【选题调研】。优先使用联网搜索搜集市场/作品/观众信息; "
            "若用户上传了评论/反馈文件, 可使用 sentiment_analyzer 分析观众情绪。"
        ),
        "report_hint": (
            "报告定位: 【选题调研报告】。请按以下结构输出: "
            "一、资料获取情况(素材编号与来源); 二、市场热度概览(数据点必须带素材编号溯源); "
            "三、同类作品表现(列表/表格对比); 四、观众讨论与需求; 五、差异化机会与风险; "
            "六、结论: 该选题是否值得做、建议的切入角度。"
        ),
    },
    TASK_REPUTATION: {
        "name": "口碑监测",
        "desc": "帮创作者了解一部作品的观众口碑: 好评/差评分布、被夸与被骂的点、趋势变化、异常预警",
        "planner_hint": (
            "当前任务: 【口碑监测】。请围绕以下维度拆解子任务: "
            "①确认监测对象(作品名/平台)与评论数据来源(用户提供的评论, 粘贴或 CSV 上传); "
            "②评论情感倾向的整体分布(素材区已有『素材-评论数据』时, 必须规划调用 sentiment_analyzer "
            "做三分类统计与抽样归因); "
            "③被观众夸奖的点(剧情/画风/配音/节奏/人设等维度); ④被观众吐槽的点; "
            "⑤与近期同类作品/上一周口碑的对比趋势(若有历史报告可检索记忆)。"
        ),
        "tool_hint": (
            "当前任务: 【口碑监测】。若素材区出现了『素材-评论数据』条目(用户粘贴或 CSV 上传的评论, "
            "系统已去标识化), 请在搜索之前**先调用 sentiment_analyzer** 对评论做三分类统计与抽样归因 "
            "(工具无需传参, 评论已由系统注入), 再结合联网搜索补充作品背景与对比信息。"
        ),
        "report_hint": (
            "报告定位: 【口碑周报】。请按以下结构输出: "
            "一、监测对象与数据来源(如实说明评论条数/来源/情感模型局限); "
            "二、口碑总览(正/中/负分布, 数据来自 sentiment_analyzer 素材, 必须溯源); "
            "三、被夸的点(分方面: 剧情/画风/配音/节奏/人设); 四、被吐槽的点(同上分方面); "
            "五、趋势与异常(与历史对比或值得注意的变化); 六、对创作者的建议。"
        ),
    },
    TASK_BENCHMARK: {
        "name": "对标拆解",
        "desc": "帮创作者拆解一部对标作品: 热度曲线、观众画像、评论高频词、可复用的亮点",
        "planner_hint": (
            "当前任务: 【对标拆解】。请围绕以下维度拆解子任务(每个子任务可直接当搜索关键词): "
            "①对标作品的基本信息与热度表现(播放/榜单/讨论量); ②对标作品的观众评价与口碑(可配合评论情感分析); "
            "③对标作品被认可的核心亮点(题材/人设/画风/叙事/运营等); ④对标作品被诟病的点(可借鉴的避坑); "
            "⑤可复用到新作品的启示。"
        ),
        "tool_hint": (
            "当前任务: 【对标拆解】。优先使用联网搜索搜集对标作品的信息与讨论; "
            "若用户上传了该作品的评论数据, 可调用 sentiment_analyzer 分析观众情绪。"
        ),
        "report_hint": (
            "报告定位: 【对标分析报告】。请按以下结构输出: "
            "一、对标对象与数据来源; 二、热度与市场表现(数据溯源); 三、观众评价拆解(正面亮点/负面槽点, 分方面); "
            "四、核心亮点提炼(哪些是成功要素); 五、避坑清单(哪些是失败教训); 六、对新作品的启示。"
        ),
    },
    TASK_GENERAL: {
        "name": "通用调研",
        "desc": "通用调研问答(原 research_agent 能力, 兜底任务)",
        "planner_hint": "",
        "tool_hint": "",
        "report_hint": "",
    },
}

TASK_LABELS = {TASK_TOPIC_RESEARCH: "选题调研", TASK_REPUTATION: "口碑监测",
               TASK_BENCHMARK: "对标拆解", TASK_GENERAL: "通用调研"}


def normalize_task_type(task_type: Optional[str]) -> str:
    """规范化任务类型: 未知/空值回退到通用调研(general), 保证向后兼容。"""
    if task_type and task_type in VALID_TASKS:
        return task_type
    return TASK_GENERAL


def get_task(task_type: Optional[str]) -> dict:
    """按任务类型取任务定义(未知回退通用调研)。"""
    return TASKS[normalize_task_type(task_type)]
