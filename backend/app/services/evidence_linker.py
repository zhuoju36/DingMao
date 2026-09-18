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


# 建设工程施工合同争议的领域术语表。
#
# 选取标准：必须是**法条原文里逐字出现**的短词（2-6 字），否则 ILIKE 命不中。
# 例如用「工程变更」命不中（法条原文写「工程范围」「变更」），所以要拆成「变更」。
# 这张表是检索的"法律透镜"——把当事人的口语（"业主不给钱"）映射到法言法语（"价款""催告"）。
DOMAIN_TERMS: tuple[str, ...] = (
    # 主体
    "建设工程", "承包人", "发包人", "施工人", "监理", "分包", "转包",
    # 合同与变更
    "施工合同", "工程范围", "变更", "签证", "书面", "约定", "补充协议",
    # 工期
    "工期", "顺延", "竣工", "开工", "停建", "缓建", "延误",
    # 价款与索赔
    "价款", "工程款", "结算", "支付", "催告", "拖欠", "利息", "索赔",
    "违约金", "损失", "赔偿", "折价补偿",
    # 质量
    "质量", "验收", "返工", "修理", "改建", "隐蔽", "材料", "设备",
    # 其他
    "解除", "无效", "设计", "图纸", "标准",
)

# 每次检索返回的候选上限（注入 prompt 的量，太多会稀释 LLM 注意力）
_LAW_CANDIDATE_LIMIT = 8
_STANDARD_CANDIDATE_LIMIT = 6

# 重叠度下限：低于此值的候选不进入 prompt（防止噪声条款被误选）
_MIN_OVERLAP = 3


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


def build_terms(context: str) -> list[str]:
    """从案情文本里筛出命中的领域术语。

    只保留**确实出现在案情里**的术语，避免用全部术语去检索导致每个条款重叠度趋同。
    注意这不是"抽取关键词"——它是"用法律词汇去对照案情"。
    """
    return [t for t in DOMAIN_TERMS if t in context]


_SQL_LAWS = text("""
    WITH terms(t) AS (SELECT unnest(CAST(:terms AS text[])))
    SELECT a.id            AS article_id,
           l.code          AS law_code,
           l.name          AS law_name,
           a.article_no    AS article_no,
           l.version       AS version,
           l.effective_date AS effective_date,
           a.content       AS content,
           (SELECT count(*) FROM terms WHERE a.content LIKE '%' || terms.t || '%') AS overlap
    FROM law_articles a
    JOIN laws l ON l.id = a.law_id
    WHERE l.status = 'active'
    ORDER BY overlap DESC, length(a.content) ASC
    LIMIT :limit
""")

_SQL_STANDARDS = text("""
    WITH terms(t) AS (SELECT unnest(CAST(:terms AS text[])))
    SELECT c.id               AS clause_id,
           s.code             AS standard_code,
           s.name             AS standard_name,
           c.clause_no        AS clause_no,
           s.version          AS version,
           s.effective_date   AS effective_date,
           c.is_mandatory     AS is_mandatory,
           c.content          AS content,
           (SELECT count(*) FROM terms WHERE c.content LIKE '%' || terms.t || '%') AS overlap
    FROM standard_clauses c
    JOIN standards s ON s.id = c.standard_id
    WHERE s.status = 'active'
    ORDER BY overlap DESC, length(c.content) ASC
    LIMIT :limit
""")


async def retrieve_candidates(
    db: AsyncSession,
    context: str,
    *,
    law_limit: int = _LAW_CANDIDATE_LIMIT,
    standard_limit: int = _STANDARD_CANDIDATE_LIMIT,
) -> EvidenceCandidates:
    """按领域术语重叠度检索候选条款。

    Args:
        db: 会话
        context: 案情文本（facts + 用户输入拼接）
        law_limit: 法条候选上限
        standard_limit: 强条候选上限

    Returns:
        EvidenceCandidates。检索失败不抛错——三依据缺失应当降级为 warning，
        而不是让整轮报告生成失败（consultation-ui.md §3.2a）。
    """
    terms = build_terms(context)
    if not terms:
        logger.info("证据检索：案情中未命中任何领域术语，跳过检索")
        return EvidenceCandidates()

    result = EvidenceCandidates(terms_used=terms)

    try:
        rows = (await db.execute(_SQL_LAWS, {"terms": terms, "limit": law_limit})).mappings()
        for i, r in enumerate(rows, start=1):
            if r["overlap"] < _MIN_OVERLAP:
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

    try:
        rows = (
            await db.execute(_SQL_STANDARDS, {"terms": terms, "limit": standard_limit})
        ).mappings()
        for i, r in enumerate(rows, start=1):
            if r["overlap"] < _MIN_OVERLAP:
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
        "证据检索：术语 %d 个，法条候选 %d 条（可引用 %d），强条候选 %d 条（可引用 %d）",
        len(terms),
        len(result.laws),
        sum(1 for c in result.laws if c.citable),
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
