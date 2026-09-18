"""证据链接器：检索优先（retrieval-first）的三依据装配。

## 为什么不按原设计让 LLM 写条款号

`w3-w8-triple-evidence.md` §3.2 原设计是「LLM 输出 `{code, article_no}`
→ EvidenceLinker 模糊匹配 DB 补 version/effective_date」。本模块改为
**反过来的方向**（决策日志 §2026-09 「证据引用改检索优先」）：

1. 先从知识库检索候选条款，编号为 `[L1]`/`[S1]` 注入 prompt
2. LLM **只输出标签**（`law_refs: ["L1"]`），没有机会写出条款号
3. 后端按标签回映射真实 DB 行，`version`/`effective_date` 直接取库里的值

应用原则 2「LLM 不参与关键数字生成」——条款号就是关键数字。
应用原则 3「引用必须有版本号 + 生效日期」——直接取库值，不可能填错。

## 检索方案：领域术语重叠度排序（实测选定）

`laws.version` 全空、无中文分词扩展、`tsv` 列全空的情况下，实测过三条路：

| 方案 | 实测结果 | 结论 |
|---|---|---|
| 朴素关键词 ILIKE | 3 个查询只有 1 个命中 | 召回不足 |
| `pg_trgm` `similarity()` | 相似度全在 0.000-0.020，把《海商法》索赔权转移排在《民法典》合同编之前 | 短查询 vs 长文档被长度主导，不可用 |
| **领域术语重叠度** | Top-14 全部命中建设工程合同争议的正确条款 | ✅ 采用 |

重叠度排序是 IR 里的经典做法（coordination level matching），
只用现有数据 + 一个 SQL 聚合，不引入新依赖（AGENTS.md 原则 2/6/8）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# 检索术语表 —— 分法条 / 强条两张。
#
# **为什么必须分开**（实测教训）：最初只有一张合同法词汇表，用在 `laws` 上没问题
# （Top-14 全部命中建设工程合同争议的正确条款），但用在 `standard_clauses` 上
# **20 个合同法术语命中 0 次**——通用规范不谈价款/发包人/索赔，它谈混凝土/防水/消防。
# 术语必须匹配语料的词汇体系，否则检索等于空转。
#
# 两张表的选取标准都相同：必须是**条文原文里逐字出现**的短词（2-6 字），
# 否则 ILIKE 命不中（例如「工程变更」命不中，法条原文写「工程范围」「变更」）。
# 表内每个词都用 3750 条真实强条 / 13461 条法条验证过命中数，0 命中的已剔除。

# 法条检索术语（合同法 / 建设工程合同争议词汇）
#
# 分两组：**锚点词**与**通用词**。
#
# 为什么必须分：实测「变更/书面/约定」这类通用合同词会让《旅游法》《土地管理法》
# 误命中——旅游法第六十九条写「不得擅自变更…订立书面委托合同，约定双方的权利和义务」，
# 土地管理法第六十三条写「应当签订书面合同…约定」，各自凑够 3 个通用词命中，
# 却与建设工程毫无关系。因此除重叠度阈值外，**候选条文本身还必须含至少一个锚点词**。
#
# 锚点词**只作为排序权重，不做硬过滤**（实测：一旦硬过滤，《民法典》合同编总则
# 里关于「合同变更须协商一致」「书面形式」的条文会被全部挡掉——而"口头指令变更"
# 这类程序争议恰恰要靠总则条文，导致该场景 🟨 恒为空）。有了 IDF 打分后，
# 工程条文本身就会排到前面，门控已无必要。
#
# 锚点词怎么选：中文 ILIKE 没有词边界，`工期` 会命中「动**工期**限」这种巧合子串。
# 因此对每个候选词统计它在 13461 条法条里命中的法律分布，只保留**领域纯度 ≥ 60%**
# （命中集中在建设工程相关法律）的词。实测被淘汰的：
#   索赔 20%、价款 10%、结算 17%、开工 33%、修理 33%、改建 30%、签证 0%、延误 14%、
#   工期 57%（正是「动工期限」误命中的来源）
_LAW_ANCHOR_TERMS: tuple[str, ...] = (
    # 主体（纯度 100%）
    "承包人", "发包人", "施工人", "监理人", "勘察",
    # 合同（纯度 100% / 75%）
    "建设工程", "设计文件", "施工图纸", "分包", "转包",
    # 价款（纯度 100%）
    "工程款", "工程价款", "工程造价",
    # 质量与工期（纯度 100% / 75%）
    "隐蔽工程", "竣工验收", "返工", "顺延", "停建", "缓建", "工程质量",
)

_LAW_GENERIC_TERMS: tuple[str, ...] = (
    "变更", "书面", "约定", "补充协议", "施工合同", "工程范围",
    "支付", "催告", "拖欠", "利息", "损失", "赔偿", "违约金", "延误",
    "工期", "竣工", "价款", "结算", "索赔",
    "质量", "验收", "材料", "设备",
    "解除", "无效", "设计", "图纸", "标准",
)

LAW_TERMS: tuple[str, ...] = _LAW_ANCHOR_TERMS + _LAW_GENERIC_TERMS

# 强条检索术语（建设工程技术规范词汇）
#
# 依据：对 31 本通用规范 3750 条正文做词频统计，取命中率 0.5%~35% 的技术名词。
# 通用规范用语（"应符合""下列规定""应设置"）无区分度，一律不入表。
STANDARD_TERMS: tuple[str, ...] = (
    # 结构 / 材料
    "混凝土", "钢筋", "砌体", "钢", "木结构", "构件", "连接", "焊接", "螺栓",
    "锚固", "承载力", "荷载", "强度", "变形", "裂缝", "挠度", "稳定",
    "地基", "基础", "桩", "基坑", "边坡", "抗震", "设防",
    # 建筑 / 防火 / 机电
    "防火", "消防", "疏散", "楼梯", "电梯", "门窗", "幕墙", "屋面", "楼板",
    "墙体", "隔墙", "装修", "保温", "防水", "排水", "给水", "供暖", "通风",
    "空调", "燃气", "电气", "电缆", "接地", "照明", "报警", "管道",
    # 市政 / 环境
    "道路", "桥梁", "隧道", "轨道", "垃圾", "污水", "噪声", "绿化", "无障碍",
    # 施工 / 安全
    "施工", "验收", "检测", "检验", "隐蔽", "脚手架", "模板", "吊装",
    "作业", "防护", "安全",
    # 通用场所
    "建筑", "场所", "人员", "场地", "地下", "公共",
)

# 向后兼容别名（此前只有一张表）
DOMAIN_TERMS: tuple[str, ...] = LAW_TERMS

# 每次检索返回的候选上限（注入 prompt 的量，太多会稀释 LLM 注意力）
_LAW_CANDIDATE_LIMIT = 10
_STANDARD_CANDIDATE_LIMIT = 6

# 重叠度下限。分开设定：技术名词比合同法通用词更具区分度，
# 且强条语料里同时命中 3 个技术名词的条款很少，阈值 3 会把召回压到接近 0
# （实测：3 个场景只有 1 个命中强条）。
#
# 阈值随命中术语数自适应：案情本身命中术语很少时（如只有「幕墙」一个），
# 固定阈值 2 会让这类案子永远检索不到任何强条。宁可给 LLM 少量候选让它筛，
# 也不要直接空手——候选错了 LLM 可以不选，空手则必然无依据。
_MIN_OVERLAP_LAW = 3
_MIN_OVERLAP_STANDARD = 2

# 命中术语少于此数时，强条阈值降到 1
_THIN_CONTEXT_TERMS = 3


def _standard_min_overlap(term_count: int) -> int:
    """强条检索的重叠度阈值（随命中术语数自适应）。"""
    return 1 if term_count < _THIN_CONTEXT_TERMS else _MIN_OVERLAP_STANDARD


# ===== 候选结构 =====


@dataclass(frozen=True)
class LawCandidate:
    """法条候选（对应 law_articles 一行）。"""

    label: str            # "L1"
    law_code: str
    law_name: str
    article_no: str
    version: str | None
    effective_date: str | None
    content: str
    overlap: int

    @property
    def citable(self) -> bool:
        """是否具备可引用条件（应用原则 3：版本号 + 生效日期缺一不可）。"""
        return bool(self.version) and bool(self.effective_date)


@dataclass(frozen=True)
class StandardCandidate:
    """强条候选（对应 standard_clauses 一行）。"""

    label: str            # "S1"
    standard_code: str
    standard_name: str
    clause_no: str
    version: str | None
    effective_date: str | None
    is_mandatory: bool
    content: str
    overlap: int

    @property
    def citable(self) -> bool:
        """通用规范均为全文强制；仍需版本号 + 生效日期才可引用。"""
        return bool(self.version) and bool(self.effective_date)


@dataclass
class EvidenceCandidates:
    """一次检索的全部候选。"""

    laws: list[LawCandidate] = field(default_factory=list)
    standards: list[StandardCandidate] = field(default_factory=list)
    terms_used: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.laws and not self.standards

    def render_for_prompt(self) -> str:
        """渲染成注入 prompt 的候选清单。

        只列 **citable** 的候选——不可引用的（缺版本号/生效日期）不进 prompt，
        免得 LLM 选了却拿不到依据，白跑一轮。
        """
        lines: list[str] = []
        citable_laws = [c for c in self.laws if c.citable]
        citable_stds = [c for c in self.standards if c.citable]

        if citable_laws:
            lines.append("【可引用的法律条文】（引用时只写标签，如 \"L1\"）")
            for c in citable_laws:
                lines.append(
                    f"  [{c.label}] 《{c.law_name}》{c.article_no}"
                    f"（{c.version}，{c.effective_date} 生效）：{c.content[:180]}"
                )
        if citable_stds:
            lines.append("")
            lines.append("【可引用的强制性标准条文】（引用时只写标签，如 \"S1\"）")
            for sc in citable_stds:
                tag = "强制性条文" if sc.is_mandatory else "标准条文"
                lines.append(
                    f"  [{sc.label}] {sc.standard_name} {sc.clause_no}"
                    f"（{sc.version}，{tag}）：{sc.content[:180]}"
                )
        if not lines:
            lines.append(
                "【知识库检索结果】无可用条款。law_refs / standard_refs 必须留空数组，"
                "并在 reasoning_chain 中明确说明「知识库中无明确对应依据」。"
            )
        return "\n".join(lines)

    def citable_labels(self) -> tuple[set[str], set[str]]:
        """返回 (可引用的法条标签集, 可引用的强条标签集)。"""
        return (
            {c.label for c in self.laws if c.citable},
            {c.label for c in self.standards if c.citable},
        )

    def find_law(self, label: str) -> LawCandidate | None:
        return next((c for c in self.laws if c.label == label), None)

    def find_standard(self, label: str) -> StandardCandidate | None:
        return next((c for c in self.standards if c.label == label), None)


# ===== 检索 =====


def build_terms(context: str, vocabulary: tuple[str, ...]) -> list[str]:
    """从案情文本里筛出命中的术语。

    只保留**确实出现在案情里**的术语，避免用全部术语去检索导致每个条款重叠度趋同。
    注意这不是"抽取关键词"——它是"用领域词汇去对照案情"。

    Args:
        context: 案情文本
        vocabulary: 用哪张表（LAW_TERMS / STANDARD_TERMS）
    """
    return [t for t in vocabulary if t in context]


# IDF 加权：越稀有的词权重越高。
#
# 为什么需要：纯计数（overlap）分辨率太低，大量条文打平。实测「拖欠工程款」场景里
# 《民法典》第807条（催告付款，正是该争议的核心条款）与第788/798/803/800条同为
# overlap=4，只能靠 length ASC 破平，被挤到第 7 位。而「催告」「拖欠」这类词的
# 文档频率远低于「支付」「约定」，本应更能定位——IDF 正是为此而生。
_SQL_LAWS = text("""
    WITH terms(t)   AS MATERIALIZED (SELECT unnest(CAST(:terms AS text[]))),
         anchors(t) AS MATERIALIZED (SELECT unnest(CAST(:anchors AS text[]))),
         df AS MATERIALIZED (
             SELECT t,
                    GREATEST(
                        (SELECT count(*) FROM law_articles a2
                          WHERE a2.content LIKE '%' || t || '%'), 1
                    ) AS n
             FROM terms
         )
    SELECT a.id            AS article_id,
           l.code          AS law_code,
           l.name          AS law_name,
           a.article_no    AS article_no,
           l.version       AS version,
           l.effective_date AS effective_date,
           a.content       AS content,
           (SELECT count(*) FROM terms   WHERE a.content LIKE '%' || terms.t   || '%') AS overlap,
           (SELECT count(*) FROM anchors WHERE a.content LIKE '%' || anchors.t || '%') AS anchor_overlap,
           (SELECT COALESCE(sum(1.0 / ln(2.0 + df.n)), 0)
              FROM df WHERE a.content LIKE '%' || df.t || '%') AS score
    FROM law_articles a
    JOIN laws l ON l.id = a.law_id
    WHERE l.status = 'active'
    ORDER BY score DESC, anchor_overlap DESC, length(a.content) ASC
    LIMIT :limit
""")

_SQL_STANDARDS = text("""
    WITH terms(t) AS MATERIALIZED (SELECT unnest(CAST(:terms AS text[]))),
         df AS MATERIALIZED (
             SELECT t,
                    GREATEST(
                        (SELECT count(*) FROM standard_clauses c2
                          WHERE c2.content LIKE '%' || t || '%'), 1
                    ) AS n
             FROM terms
         )
    SELECT c.id               AS clause_id,
           s.code             AS standard_code,
           s.name             AS standard_name,
           c.clause_no        AS clause_no,
           s.version          AS version,
           s.effective_date   AS effective_date,
           c.is_mandatory     AS is_mandatory,
           c.content          AS content,
           (SELECT count(*) FROM terms WHERE c.content LIKE '%' || terms.t || '%') AS overlap,
           (SELECT COALESCE(sum(1.0 / ln(2.0 + df.n)), 0)
              FROM df WHERE c.content LIKE '%' || df.t || '%') AS score
    FROM standard_clauses c
    JOIN standards s ON s.id = c.standard_id
    WHERE s.status = 'active'
    ORDER BY score DESC, length(c.content) ASC
    LIMIT :limit
""")


async def retrieve_candidates(
    db: AsyncSession,
    context: str,
    *,
    extra_terms: list[str] | None = None,
    law_limit: int = _LAW_CANDIDATE_LIMIT,
    standard_limit: int = _STANDARD_CANDIDATE_LIMIT,
) -> EvidenceCandidates:
    """按领域术语重叠度检索候选条款。

    Args:
        db: 会话
        context: 案情文本（facts + 用户输入拼接）
        extra_terms: 查询扩展词（见 `expand_search_terms`）。
            案情是口语（"索赔""工期顺延"），法条是法言法语（"赔偿损失""顺延工程日期"），
            仅靠案情自身用词做子串匹配召回极低——实测主场景 0 条候选。
            扩展词把口语映射到法条词汇，是召回的关键。只接受受控词表内的词。
        law_limit: 法条候选上限
        standard_limit: 强条候选上限

    Returns:
        EvidenceCandidates。检索失败不抛错——三依据缺失应当降级为 warning，
        而不是让整轮报告生成失败（consultation-ui.md §3.2a）。
    """
    law_terms = build_terms(context, LAW_TERMS)
    std_terms = build_terms(context, STANDARD_TERMS)
    # 锚点集用**完整**锚点表，不按案情过滤：锚点门控要回答的是
    # "这条候选是不是在讲建设工程"，这与案情里有没有出现该词无关。
    # 若按案情过滤，案情没提「分包」时《民法典》第791条（分包）就永远进不了候选。
    law_anchors = list(_LAW_ANCHOR_TERMS)

    # 扩展词必须落在受控词表内，否则会产出"工程变更"这类法条原文里查不到的词
    if extra_terms:
        allowed_law = set(LAW_TERMS)
        allowed_std = set(STANDARD_TERMS)
        for t in extra_terms:
            if t in allowed_law and t not in law_terms:
                law_terms.append(t)
            if t in allowed_std and t not in std_terms:
                std_terms.append(t)

    if not law_terms and not std_terms:
        logger.info("证据检索：案情中未命中任何领域术语，跳过检索")
        return EvidenceCandidates()

    # 去重但保持顺序（「验收」「隐蔽」等词同时出现在两张表里）
    result = EvidenceCandidates(
        terms_used=list(dict.fromkeys([*law_terms, *std_terms]))
    )

    if law_terms:
        try:
            rows = (
                await db.execute(
                    _SQL_LAWS,
                    {
                        "terms": law_terms,
                        "anchors": law_anchors,
                        "limit": law_limit,
                    },
                )
            ).mappings()
            for i, r in enumerate(rows, start=1):
                if r["overlap"] < _MIN_OVERLAP_LAW:
                    continue
                result.laws.append(
                    LawCandidate(
                        label=f"L{i}",
                        law_code=r["law_code"],
                        law_name=r["law_name"],
                        article_no=r["article_no"],
                        version=r["version"],
                        effective_date=r["effective_date"],
                        content=r["content"],
                        overlap=r["overlap"],
                    )
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("法条检索失败: %s", e)

    if std_terms:
        try:
            rows = (
                await db.execute(
                    _SQL_STANDARDS, {"terms": std_terms, "limit": standard_limit}
                )
            ).mappings()
            std_floor = _standard_min_overlap(len(std_terms))
            for i, r in enumerate(rows, start=1):
                if r["overlap"] < std_floor:
                    continue
                result.standards.append(
                    StandardCandidate(
                        label=f"S{i}",
                        standard_code=r["standard_code"],
                        standard_name=r["standard_name"],
                        clause_no=r["clause_no"],
                        version=r["version"],
                        effective_date=r["effective_date"],
                        is_mandatory=r["is_mandatory"],
                        content=r["content"],
                        overlap=r["overlap"],
                    )
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("强条检索失败: %s", e)

    logger.info(
        "证据检索：法条术语 %d 个 → 候选 %d 条（可引用 %d）；"
        "强条术语 %d 个 → 候选 %d 条（可引用 %d）",
        len(law_terms),
        len(result.laws),
        sum(1 for c in result.laws if c.citable),
        len(std_terms),
        len(result.standards),
        sum(1 for c in result.standards if c.citable),
    )
    return result


# ===== 标签 → 引用映射 =====


@dataclass
class LinkResult:
    """链接结果：可落库的引用 + 必须可观测的 warning。"""

    law_refs: list[dict[str, Any]] = field(default_factory=list)
    standard_refs: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def link_evidence(
    *,
    law_labels: list[str],
    standard_labels: list[str],
    candidates: EvidenceCandidates,
    conclusion_index: int,
) -> LinkResult:
    """把 LLM 输出的标签映射成可落库的引用。

    降级规则（consultation-ui.md §3.2a 裁决）：
    - 标签命中且可引用（有版本号 + 生效日期）→ 收进 refs
    - 标签命中但缺版本号/生效日期 → **丢弃该引用** + warning（应用原则 3 红线）
    - 标签不存在（LLM 编的）→ 丢弃 + warning
    - 一条引用都没有 → warning，但**结论本身保留**（应用原则 1 是"无依据不升格"，
      不是"无依据不出结论"）
    """
    out = LinkResult()

    for label in law_labels:
        law_cand = candidates.find_law(label)
        if law_cand is None:
            out.warnings.append(
                {
                    "scope": "ref",
                    "index": conclusion_index,
                    "type": "unknown_law_label",
                    "detail": f"丢弃引用：LLM 给出未检索到的标签 {label!r}",
                }
            )
            continue
        if not law_cand.citable:
            out.warnings.append(
                {
                    "scope": "ref",
                    "index": conclusion_index,
                    "type": "missing_law_version",
                    "detail": (
                        f"丢弃引用：《{law_cand.law_name}》{law_cand.article_no}"
                        f"（version={law_cand.version!r} "
                        f"effective_date={law_cand.effective_date!r}，"
                        "不满足应用原则 3）"
                    ),
                }
            )
            continue
        out.law_refs.append(
            {
                "code": law_cand.law_code,
                "name": law_cand.law_name,
                "article_no": law_cand.article_no,
                "version": law_cand.version,
                "effective_date": law_cand.effective_date,
            }
        )

    for label in standard_labels:
        std_cand = candidates.find_standard(label)
        if std_cand is None:
            out.warnings.append(
                {
                    "scope": "ref",
                    "index": conclusion_index,
                    "type": "unknown_standard_label",
                    "detail": f"丢弃引用：LLM 给出未检索到的标签 {label!r}",
                }
            )
            continue
        if not std_cand.citable:
            out.warnings.append(
                {
                    "scope": "ref",
                    "index": conclusion_index,
                    "type": "missing_standard_version",
                    "detail": (
                        f"丢弃引用：{std_cand.standard_name} {std_cand.clause_no}"
                        f"（version={std_cand.version!r} "
                        f"effective_date={std_cand.effective_date!r}，"
                        "不满足应用原则 3）"
                    ),
                }
            )
            continue
        out.standard_refs.append(
            {
                "code": std_cand.standard_code,
                "name": std_cand.standard_name,
                "clause_no": std_cand.clause_no,
                "version": std_cand.version,
                "is_mandatory": std_cand.is_mandatory,
                "effective_date": std_cand.effective_date,
            }
        )

    if not out.law_refs and not out.standard_refs:
        out.warnings.append(
            {
                "scope": "conclusion",
                "index": conclusion_index,
                "type": "no_candidate_basis",
                "detail": "该结论无任何可引用的法律/强条依据（知识库无对应条款或版本信息缺失）",
            }
        )

    return out
