"""
core/report_verifier.py —— 报告引用一致性校验(防幻觉闭环的确定性兜底, v1.6.0)

背景: 报告提示词强制要求"每条结论标注素材编号【素材N】", 但 LLM 偶尔会引用
不存在的素材编号(如素材15 而实际只有 8 条素材)。本模块在报告生成后做**确定性
校验**(不依赖 LLM): 提取报告中的全部素材引用编号, 逐一核对是否落在素材列表
范围内 —— 把"防幻觉"从提示词约束升级为可验证、可展示的工程闭环。

对外函数:
    extract_citations(report) -> list[int]
        提取报告中全部素材引用编号(兼容【素材N】/〔素材N〕/(素材N)/素材N 等
        任意括号形式, 以及"素材N[i]"带页码/条目后缀的写法), 保持出现顺序
    verify_report_citations(report, materials) -> dict
        校验报告引用是否全部有效, 返回结构化结果供 UI/API 展示

说明:
    - 编号语义: 素材列表 collected_info 按下标 1 基编号(素材1 = materials[0]);
    - 引用后缀 [i] / [i,j](素材内部第 i/j 条来源)只校验主编号 N 是否越界;
    - 校验失败(存在越界引用/零引用)不阻断流程 —— 结果如实展示, 由用户判断,
      避免因模型偶发不规范而浪费一次完整重跑。
"""
import re
from typing import Dict, List

# 匹配 "素材N"(N 后不能紧跟数字, 避免把 "素材12" 误拆成 "素材1+2");
# 前缀允许任意括号与文字, 后缀允许 [i] / [i,j] 页码引用。
_CITATION_RE = re.compile(r"素材\s*(\d+)(?!\d)")

# URL 提取: 截到空白/中文标点/括号/引号为止(报告中 URL 均已清洗, 此处兜底去尾巴)
# 报告中的 URL 已经过 search_tool.clean_url 清洗, 此处兜底防全角尾巴)
# 报告中的 URL 已经过 search_tool.clean_url 清洗, 此处兜底防全角尾巴)
_URL_RE = re.compile(r"https?://[^\s，；。：！？、）】」』》>\"']+")
_PCT_TAIL_RE = re.compile(r"(?:%[0-9A-Fa-f]{1,3})+$")          # 尾随百分号编码乱码
_TRAIL_PUNCT_RE = re.compile(r"[)\]},.;:!?…、，。；：！？」』】]+$")  # 尾随标点


def extract_urls(text: str) -> list:
    """提取文本中全部 http(s) URL(出现顺序)。无 URL 返回 []。"""
    if not text:
        return []
    return _URL_RE.findall(str(text))


def _norm_url_for_match(url: str) -> str:
    """URL 匹配归一化: 去掉尾随百分号编码/标点, 小写, 去尾部斜杠(比较用, 不修改展示)。"""
    s = str(url or "").strip()
    s = _PCT_TAIL_RE.sub("", s)
    s = _TRAIL_PUNCT_RE.sub("", s).strip()
    return s.lower().rstrip("/")


def _material_url_set(materials: list) -> set:
    """收集素材文本中出现的全部 URL(归一化后), 供报告 URL 溯源比对。"""
    out = set()
    for m in materials or []:
        for u in extract_urls(str(m)):
            out.add(_norm_url_for_match(u))
    return out


def extract_citations(report: str) -> List[int]:
    """提取报告中全部素材引用编号(出现顺序, 不去重)。

    :param report: 最终调研报告文本
    :return: 编号列表, 如 [1, 3, 2, 10]; 无引用返回 []
    """
    if not report:
        return []
    return [int(m.group(1)) for m in _CITATION_RE.finditer(report)]


def verify_report_citations(report: str, materials: list) -> Dict[str, object]:
    """校验报告引用是否全部有效(确定性检查, 不调用 LLM)。

    规则:
        - 有效编号: 1 <= N <= len(materials)(素材列表 1 基编号);
        - 引用总数: 报告中出现的引用次数(含重复);
        - 去重编号: 去重后的引用编号列表;
        - 无效引用: 越界(> 素材数 或 < 1)的去重编号;
        - all_valid: 报告含至少一处引用, 且不存在无效引用。

    :return: {"total_citations", "unique_citations", "invalid_citations",
              "materials_count", "has_citations", "all_valid"}
    """
    materials = list(materials or [])
    citations = extract_citations(report)
    unique = sorted(set(citations))
    invalid = [n for n in unique if n < 1 or n > len(materials)]
    has_citations = len(citations) > 0
    # 素材覆盖度(信息性提示, 不阻断): 未被报告引用的素材编号 —— 帮助发现
    # "某素材被忽略/引用偏少"(如编号靠后的素材常被 LLM 忽略), 供 UI 提示反思。
    used = set(n for n in unique if 1 <= n <= len(materials))
    unused = sorted(set(range(1, len(materials) + 1)) - used)
    # URL 溯源(防编造链接, v1.7.0-fix4): 报告中出现的 URL 必须能在素材中找到
    # (归一化匹配, 容忍素材 URL 尾部的乱码尾巴)。报告无 URL 不算错(评论类素材本无链接)。
    report_urls = extract_urls(report)
    material_urls = _material_url_set(materials)
    invalid_urls = sorted(
        {u for u in report_urls
         if _norm_url_for_match(u) not in material_urls})
    return {
        "total_citations": len(citations),
        "unique_citations": unique,
        "invalid_citations": invalid,
        "unused_materials": unused,
        "materials_count": len(materials),
        "has_citations": has_citations,
        "url_citations_total": len(report_urls),
        "invalid_urls": invalid_urls,
        "all_valid": has_citations and not invalid and not invalid_urls,
    }


def citation_check_mark(result: Dict[str, object]) -> str:
    """把校验结果渲染为一行简明的 UI 文案(供 Streamlit / API 展示)。

    例: "✅ 引用校验: 24 处引用(去重 10 个编号)全部有效"
        "⚠️ 引用校验: 发现 2 个无效编号(素材12/素材15), 共 8 条素材"
        "⚠️ 引用校验: 报告未包含任何素材引用(建议重新生成)"
    """
    total = int(result.get("total_citations") or 0)
    unique = list(result.get("unique_citations") or [])
    invalid = list(result.get("invalid_citations") or [])
    unused = list(result.get("unused_materials") or [])
    invalid_urls = list(result.get("invalid_urls") or [])
    n_materials = int(result.get("materials_count") or 0)
    if not result.get("has_citations"):
        return f"⚠️ 引用校验: 报告未包含任何素材引用(共 {n_materials} 条素材, 建议重新生成)"
    if invalid:
        bad = "/".join(f"素材{n}" for n in invalid)
        return (f"⚠️ 引用校验: {total} 处引用(去重 {len(unique)} 个编号), "
                f"发现 {len(invalid)} 个无效编号({bad}), 素材共 {n_materials} 条")
    base = (f"✅ 引用校验: {total} 处引用(去重 {len(unique)} 个编号)全部有效, "
            f"素材共 {n_materials} 条")
    if invalid_urls:
        base += (f"；⚠️ 发现 {len(invalid_urls)} 个素材中不存在的链接"
                 f"(如 {invalid_urls[0][:60]}), 已触发自动重生成")
    if unused:
        base += f"；⚠️ {len(unused)} 条素材未被引用(素材{'/'.join(f'{n}' for n in unused[:6])}{'等' if len(unused) > 6 else ''}), 建议反思节点深挖"
    return base
