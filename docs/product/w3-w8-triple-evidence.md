# W3-W8 变更扯皮场景 · 三源证据填充（第 3 轮设计）

> 日期：2026-09-18
> 状态：设计阶段，**未动代码**
> 范围：变更扯皮场景的 🟦 用户事实 + 🟨 法条 + 🟥 强条 三源证据填充
> 关联：[第 1 轮](w3-w8-state-and-facts.md) / [第 2 轮](w3-w8-llm-prompts.md) / `data-model.md` §七/八 / `consultation_engine.py` / `knowledge_search.py`

---

## 一、现状与问题

### 1.1 现状（基于代码实测）

| 文件 | 现状 | 问题 |
|---|---|---|
| `models/knowledge.py:12-39` `Law` | 无 `version` 字段 | 法条引用缺版本号 |
| `models/knowledge.py:84-107` `Standard` | 有 `version: Mapped[str]` | OK |
| `knowledge_search.py:18-45` `search_laws` | 返回 dict 无 `version` | Law 表缺字段，函数也未补 |
| `knowledge_search.py:48-78` `search_standards` | 返回 dict **有** `effective_date` 但**无** `version` | **bug**，未返回 Standard.version |
| `consultation_engine.py:419-421` `stream_report` | `law_refs=[]` `standard_refs=[]` | **永远空数组**，三源证据断了 |
| `data-model.md:241-253` `ConsultationConclusion` | 字段已设计（fact_refs / law_refs / standard_refs）| OK，但未实际填充 |

### 1.2 问题驱动

按 AGENTS.md "应用原则 1：数据确凿优先"（每个结论必须挂 🟦🟨🟥）+"应用原则 3：法条/强条引用必须有版本号 + 生效日期"：

1. ❌ `Law` 表无 `version` 字段 → 法条引用缺版本号（违反应用原则 3）
2. ❌ `stream_report` 写 `law_refs=[]` → 结论无证据（违反应用原则 1）
3. ⚠ `search_standards` 未返回 `version` → 字段定义与实际不符（bug）

---

## 二、三源证据数据流

### 2.1 完整流程

```
┌──────────────────────────────────────────────────────────────┐
│ 1. 知识库检索（chat_turn / stream_report 之前）                  │
│    laws_hits = search_laws(db, query, limit=3)               │
│    standards_hits = search_standards(db, query, limit=3)     │
│    → 注入到 LLM context 作为"参考"                             │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ 2. LLM 生成报告（report_system，generating_report 节点）       │
│    LLM 输出 JSON:                                             │
│    {                                                         │
│      "risks": [                                              │
│        {                                                     │
│          "level": "red|yellow|green",                       │
│          "title": "...",                                     │
│          "content": "...",                                   │
│          "fact_refs": [<从 ConsultationFact.id 选>],         │
│          "law_refs": [                                       │
│            {"code": "民法典", "article_no": "580", ...}      │ ← LLM 引用
│          ],                                                  │
│          "standard_refs": [...]                              │
│        }                                                     │
│      ]                                                       │
│    }                                                         │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ 3. EvidenceLinker 服务（NEW）                                │
│    输入: LLM JSON + knowledge_hits                           │
│    行为:                                                     │
│      a. fact_refs: 校验 ID 是否属于该 consultation           │
│      b. law_refs: 对每个 (code, article_no)，               │
│                   在 laws_hits 中查匹配，填充 version +      │
│                   effective_date                              │
│      c. standard_refs: 同 law_refs，从 standards_hits 匹配   │
│      d. 校验版本号非空（应用原则 3）                          │
│    输出: validated refs                                       │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ 4. 写入 ConsultationConclusion                                │
│    law_refs = [{"code": "民法典", "article_no": "580",       │
│                 "version": "2020", "effective_date": "2021-01-01"}] │
│    standard_refs = [{"code": "GB 55001-2021", "clause_no": "4.1.1",│
│                     "version": "2021", "is_mandatory": true}]       │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ 5. 前端展示（ChatView / ReportCard）                          │
│    每个 risk 卡片下展示引用徽章：                              │
│    🟦 事实 1, 2, 3                                            │
│    🟨 民法典 第 580 条（2020）                                │
│    🟥 GB 55001-2021 第 4.1.1 条（强条）                       │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 LLM vs EvidenceLinker 的责任划分

| 职责 | LLM | EvidenceLinker | 理由 |
|---|---|---|---|
| 选哪些事实/法条/强条 | ✅ | ❌ | LLM 基于语义判断最合适 |
| 写 `(code, article_no)` | ✅ | ❌ | LLM 看知识库文本生成 |
| 填 `version` / `effective_date` | ❌ | ✅ | **关键数字必须结构化**（应用原则 2）|
| 校验 ID 有效性 | ❌ | ✅ | LLM 可能编造 fact_id（防御性）|
| 校验版本号非空 | ❌ | ✅ | 不允许"未知版本"的引用（应用原则 3）|

按"应用原则 2：LLM 不参与关键数字生成"，`version` / `effective_date` 必须由 EvidenceLinker 从 DB 填充，不让 LLM 写。

按"应用原则 1：数据确凿优先"，三源挂载在 EvidenceLinker 层做强校验，**不允许任何一条 risk 缺少 fact_refs + (law_refs 或 standard_refs)**。

---

## 三、数据模型增量（P0-3 修复后版本，2026-09-18）

### 3.1 `Law` 表补 `version` + `aliases` 字段

按应用原则 3 + `Standard.version` 已有先例，`Law` 需补同款字段。**同时新增 `aliases` 字段**（P0-1 修复）——用于解决 LLM 输出"中华人民共和国民法典"与 DB 存"民法典"的命名差异。

#### `models/knowledge.py` 增量

```python
class Law(Base, TimestampMixin):
    __tablename__ = "laws"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    issuing_org: Mapped[str | None] = mapped_column(String(200))

    # ====== 本次增量（P0-3 + P0-1 修复）======
    version: Mapped[str | None] = mapped_column(String(20))  # 法律版本/颁布年份
    aliases: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # aliases 示例: ["民法典", "中华人民共和国民法典", "MFC"]
    # 三源证据匹配时遍历 aliases + code + name 全部命中
    # ====== /本次增量 ======

    effective_date: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="active")
    replaced_by: Mapped[str | None] = mapped_column(String(64))
    tsv: Mapped[str | None] = mapped_column(TSVECTOR)

    articles: Mapped[list["LawArticle"]] = relationship(...)
```

#### Alembic migration 草案（P0-3 修复：**只加列，不硬编码 UPDATE**）

```python
# alembic/versions/<hash>_add_law_version_and_aliases.py
def upgrade():
    # 加 version 列（nullable=True，允许后续导入时填充）
    op.add_column("laws", sa.Column("version", sa.String(20), nullable=True))
    # 加 aliases 列（JSONB 数组，默认空）
    op.add_column(
        "laws",
        sa.Column("aliases", postgresql.JSONB, nullable=False, server_default="[]"),
    )
    # 严禁在 migration 里硬编码 UPDATE（违反决策日志 §2026-09「应用原则 7」）
    # version + aliases 的回填放在知识库导入脚本（knowledge-base/scripts/import_laws.py）

def downgrade():
    op.drop_column("laws", "aliases")
    op.drop_column("laws", "version")
```

按"应用原则 7：知识库与代码解耦，可重建"，**version / aliases 是数据本身的属性，应在知识库导入脚本里跟法条一同入库**——参考 `Standard.version` 的现有做法（导入脚本直接入库，不是 migration 后填）。

### 3.2 `knowledge-base/scripts/import_laws.py` 增量（替代硬编码 UPDATE）

```python
# 知识库导入时一并填 version + aliases
LAW_RECORDS = [
    {
        "code": "民法典",
        "name": "中华人民共和国民法典",
        "version": "2020",
        "aliases": ["民法典", "中华人民共和国民法典", "MFC", "Civil Code"],
        "effective_date": "2021-01-01",
        ...
    },
    {
        "code": "招标投标法",
        "version": "2018",
        "aliases": ["招标投标法", "中华人民共和国招标投标法", "Bidding Law"],
        ...
    },
    ...
]
```

### 3.3 `data-model.md` §八增量

```markdown
### Law（法律）
| 字段 | 类型 | 说明 |
|---|---|---|
| ... | ... | ... |
| **version** | **str(20)?** | **法律版本/颁布年份（如 "2020"），三源证据必填** |
| **aliases** | **list[str]** | **同义词/缩写/英文名（用于 LLM 输出归一化匹配）** |
| effective_date | str(10)? | YYYY-MM-DD |
| ... | ... | ... |
```

### 3.4 `LawArticle` / `StandardClause` 不变

两者都已有 `article_no` / `clause_no`，可唯一定位。`is_mandatory` / `keywords` / `tsv` 都有，无需补。

`article_no` 匹配规则统一在 EvidenceLinker 加归一化层（P1-9 修复，见 §4.2）。

---

## 四、EvidenceLinker 服务设计

按"原则 4：模块化"，新服务放 `app/services/evidence_linker.py`，与 `consultation_engine.py` 并列。

### 4.1 函数签名

```python
from typing import Any

async def link_evidence(
    *,
    consultation_id: int,
    risks: list[dict[str, Any]],          # LLM 输出的 risks
    law_hits: list[dict[str, Any]],       # 来自 search_laws
    standard_hits: list[dict[str, Any]],  # 来自 search_standards
    fact_lookup: dict[int, ConsultationFact],  # 已加载的 facts（按 id 索引）
) -> list[dict[str, Any]]:
    """校验 + 增强 + 挂载三源证据。

    每个 risk 经过：
    1. fact_refs 校验：所有 id 必须属于本 consultation
    2. law_refs 增强：从 law_hits 匹配 (code, article_no) 补充 version + effective_date
    3. standard_refs 增强：同 law_refs
    4. 兜底：缺失 law_refs + standard_refs 时按应用原则 1 标记 warning
    """
```

### 4.2 匹配逻辑（P0-1 + P1-9 修复后版本，2026-09-18）

> subagent 独立审阅指出：原 `_match_law_ref` 用 `hit["law_code"] == raw.get("code")` 字符串相等匹配，会大面积 silent failure：
> - LLM 看到的 `law_name` 是"中华人民共和国民法典"，DB `Law.code` 存"民法典"——直接不等
> - LLM 输出 `article_no="第 577 条"`（阿拉伯数字），DB 存"第五百七十七条"（汉字数字）——直接不等
>
> 修复方案：`Law.aliases JSONB` 字段（§3.1）+ article_no 归一化层。

```python
import re

_CN_DIGITS = "零一二三四五六七八九十百千万〇两"
_CN_NUM_MAP = {d: i for i, d in enumerate("零一二三四五六七八九")}
_CN_UNIT_MAP = {"十": 10, "百": 100, "千": 1000, "万": 10000, "〇": 0, "两": 2}


def _normalize_article_no(article_no: str) -> set[str]:
    """article_no 归一化：返回所有等价形式。"""
    forms = {article_no}
    # 提取数字（阿拉伯）
    m = re.search(r"\d+", article_no)
    if m:
        forms.add(m.group())
    # 汉字数字转阿拉伯
    def _cn_to_int(s: str) -> int | None:
        result, current, last_unit = 0, 0, 1
        for ch in s:
            if ch in _CN_NUM_MAP:
                current = _CN_NUM_MAP[ch]
            elif ch in _CN_UNIT_MAP:
                unit = _CN_UNIT_MAP[ch]
                if current == 0:
                    current = 1
                if unit >= last_unit:
                    result += current
                    last_unit = unit
                    current = 0
                else:
                    current *= unit
                    last_unit = 1
            else:
                return None
        return result + current
    # 简化：只取核心数字（"第五百七十七条" → "577"）
    cn_digits_only = "".join(c for c in article_no if c in _CN_DIGITS)
    if cn_digits_only:
        # 粗略归一：取最后 4 位数字对应的汉字
        arabic = _cn_to_int(cn_digits_only)
        if arabic:
            forms.add(str(arabic))
    return forms


def _match_law_ref(
    raw: dict, law_hits: list[dict]
) -> dict | None:
    """从 law_hits 找匹配 (code, article_no) 的命中，补充 version + effective_date。

    匹配规则（按优先级）：
    1. raw.code 命中 hit.law_code / hit.law_name / hit.aliases 任一
    2. article_no 经 _normalize_article_no 后命中 hit.article_no
    """
    raw_code = raw.get("code", "")
    raw_article = raw.get("article_no", "")
    article_forms = _normalize_article_no(raw_article)

    for hit in law_hits:
        # code 匹配：DB code / name / aliases 任一命中
        code_match = (
            hit["law_code"] == raw_code
            or hit.get("law_name") == raw_code
            or raw_code in hit.get("aliases", [])
        )
        if not code_match:
            continue
        # article_no 匹配：归一化形式命中
        hit_article = hit.get("article_no", "")
        if hit_article in article_forms or raw_article == hit_article:
            version = hit.get("version", "")
            if not version:
                # P0-2 修复：version 缺失是硬错误，由调用方 raise
                raise ConsultationError(
                    f"Law {hit['law_code']} 缺少 version 字段，无法满足应用原则 3"
                )
            return {
                "code": raw_code,
                "article_no": raw_article,
                "version": version,
                "effective_date": hit.get("effective_date", ""),
            }
    return None


def _match_standard_ref(
    raw: dict, standard_hits: list[dict]
) -> dict | None:
    """标准匹配（GB 55001 等）：code 比对标准编号，clause_no 归一化比对。"""
    raw_code = raw.get("code", "")
    raw_clause = raw.get("clause_no", "")
    # 强条 code 通常格式固定（GB 55001-2021），直接等
    for hit in standard_hits:
        if (
            hit["standard_code"] == raw_code
            or raw_code in hit.get("standard_aliases", [])
        ):
            if hit.get("clause_no") == raw_clause:
                version = hit.get("version", "")
                if not version:
                    raise ConsultationError(
                        f"Standard {hit['standard_code']} 缺少 version 字段"
                    )
                return {
                    "code": raw_code,
                    "clause_no": raw_clause,
                    "version": version,
                    "is_mandatory": hit.get("is_mandatory", False),
                    "effective_date": hit.get("effective_date", ""),
                }
    return None
```

按"应用原则 1：数据确凿优先"，匹配失败必须**可观测**——上层 `link_evidence` 聚合所有失败，写入 `consultation.system_warning`（不阻塞）。

### 4.3 校验规则（P0-2 修复：硬抛错而非软警告，2026-09-18）

> subagent 指出：原 `_validate_risk` 对 `missing_law_version` 仅返回 warning 而非抛错——软警告意味着 DB 仍会写入 version 缺失的 law_refs，**违反 AGENTS.md 应用原则 3「引用必须有版本号 + 生效日期」红线**。
>
> 修复：version / effective_date 缺失直接 `raise ConsultationError`，由 `link_evidence` 上层决定重试 / 降级。

```python
class EvidenceValidationError(ConsultationError):
    """三源证据校验失败：违反 AGENTS.md 应用原则 1 / 3 红线。"""


def _validate_risk(risk: dict, valid_fact_ids: set[int]) -> None:
    """硬校验：失败直接 raise，由上层决定降级。

    违反应用原则 3（version 缺失）→ 直接抛错，绝不写入 DB。
    """
    fact_refs = risk.get("fact_refs", [])
    if not fact_refs:
        raise EvidenceValidationError(
            "risk 缺少 fact_refs（违反应用原则 1：数据确凿优先）"
        )
    for fid in fact_refs:
        if fid not in valid_fact_ids:
            raise EvidenceValidationError(
                f"无效 fact_id: {fid}（不属于本 consultation）"
            )
    law_refs = risk.get("law_refs", [])
    standard_refs = risk.get("standard_refs", [])
    if not law_refs and not standard_refs:
        raise EvidenceValidationError(
            "risk 缺少法律依据（违反应用原则 1：必须挂法条或强条）"
        )
    # 应用原则 3 红线：version 缺失直接抛错
    for ref in law_refs:
        if not ref.get("version"):
            raise EvidenceValidationError(
                f"law_refs 中 {ref.get('code')} 缺少 version（违反应用原则 3）"
            )
        if not ref.get("effective_date"):
            raise EvidenceValidationError(
                f"law_refs 中 {ref.get('code')} 缺少 effective_date（违反应用原则 3）"
            )
    for ref in standard_refs:
        if not ref.get("version"):
            raise EvidenceValidationError(
                f"standard_refs 中 {ref.get('code')} 缺少 version（违反应用原则 3）"
            )
    if not law_refs and not standard_refs:
        warnings.append("no_legal_basis")  # 应用原则 1：必须有法律依据
    for ref in law_refs:
        if not ref.get("version"):
            warnings.append(f"missing_law_version:{ref.get('code')}")
        if not ref.get("effective_date"):
            warnings.append(f"missing_law_effective_date:{ref.get('code')}")
    # 同 standard_refs
    return warnings
```

按"原则 8：成熟产品参考"，参考 Anthropic Citations API 的"必须可追溯到源文档"原则。

### 4.4 `knowledge_search.py` 增量

补 `search_laws` / `search_standards` 返回 `version` 字段：

```python
# search_laws
return [
    {
        ...,
        "version": a.law.version,  # 新增
        "effective_date": a.law.effective_date,
    }
    for a in result.scalars().all()
]

# search_standards
return [
    {
        ...,
        "version": c.standard.version,  # 新增（之前漏了）
        "effective_date": c.standard.effective_date,
    }
    for c in result.scalars().all()
]
```

按"原则 2：最简单实现"，`Standard.version` 已经有，函数只需补一行。

---

## 五、LLM prompt 改造（`report_system`）

第 2 轮文档 §五 已设计 `report_system` 包含 `law_refs` / `standard_refs` 字段。本轮**不动 prompt 主体**，仅加一段输出指引：

```python
# 增量（追加到 report_system 的"红线"部分）
"""
# 三源证据挂载规则
- fact_refs: 必填，从已收集事实的 fact.id 选
- law_refs / standard_refs: 必填至少一项（应用原则 1）
- 你只填 (code, article_no / clause_no)；version 和 effective_date 由系统自动补充
- 不要编造 code / article_no！如果知识库没找到，写空数组并在 reasoning_chain 说明
"""
```

按"应用原则 2：LLM 不参与关键数字生成"，LLM 不填 `version` / `effective_date`。

---

## 六、JSON Schema 调整

第 2 轮文档 §五.3 的 `REPORT_SCHEMA` 已含 `law_refs` / `standard_refs` 字段。本轮**Schema 不变**，但加 `additionalProperties: false` 强校验。

```python
# 每个 ref 对象必填字段
LAW_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "code": {"type": "string", "maxLength": 64},
        "article_no": {"type": "string", "maxLength": 20},
        # version / effective_date 不在 LLM 输出 schema 中（由 EvidenceLinker 填充）
    },
    "required": ["code", "article_no"],
    "additionalProperties": False,
}

STANDARD_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "code": {"type": "string", "maxLength": 64},
        "clause_no": {"type": "string", "maxLength": 20},
    },
    "required": ["code", "clause_no"],
    "additionalProperties": False,
}
```

按"原则 6：诚实优先" — schema 故意不约束 `version` 字段，避免 LLM 编造。

---

## 七、可重建性（决策日志 §7）

按"应用原则 7：知识库与代码解耦，可重建"：

```
LLM 删除 → 用 consultation_id + consultation.facts 重建三源证据
    ↓
    重新调 LLM（同一 prompt + 同一 fact 值）→ 同样输出 fact_refs/law_refs 引用
    ↓
    重新过 EvidenceLinker → 重新从 laws/standards 表匹配 version/effective_date
```

EvidenceLinker 是**纯函数**（无副作用），可重复调用，结果幂等。

---

## 八、代码改动清单（设计稿，**未实施**）

按 `conventions.md` §二，新代码放对位置：

| 文件 | 类型 | 改动 |
|---|---|---|
| `backend/app/models/knowledge.py` | 修改 | `Law` 类加 `version: Mapped[str \| None]` |
| `alembic/versions/<hash>_add_law_version.py` | 新建 | 加列 + 回填已知法律版本 |
| `backend/app/services/knowledge_search.py` | 修改 | `search_laws` / `search_standards` 返回 `version` 字段 |
| `backend/app/services/evidence_linker.py` | **新建** | `link_evidence` 函数 + `_match_law_ref` / `_match_standard_ref` / `_validate_risk` |
| `backend/app/services/consultation_engine.py` | 修改 | `stream_report` 调用 `link_evidence` 替换硬编码 `[]` |
| `backend/app/services/chat.py` | 修改 | `build_report_messages` 不变（已在 §五.3 处理）；`search_combined` 函数可加 |
| `docs/architecture/data-model.md` | 修改 | §八 Law 表加 `version` 字段 |
| `docs/product/decision-log.md` | 增量 | 加 1 条 2026-09 决策（详见 §十）|

按"原则 3：分层生长"，建议落地顺序：
1. **数据模型先行**：`Law.version` 加列 + 回填 + `knowledge_search.py` 补字段
2. **新服务**：`evidence_linker.py` 单测
3. **集成**：`consultation_engine.py` 调用新服务
4. **测试**：端到端三源证据验证

---

## 九、测试要点

### 9.1 单元测试（`evidence_linker.py`）

| 用例 | 输入 | 预期 |
|---|---|---|
| law_refs 匹配成功 | LLM 输出 `{code: "民法典", article_no: "580"}` + law_hits 含同条 | 输出 `{code, article_no, version: "2020", effective_date: "2021-01-01"}` |
| law_refs 匹配失败 | LLM 输出不存在的 code | 输出 None + warning `no_legal_basis` |
| fact_refs 校验 | fact_id 不属于本 consultation | warning `invalid_fact_id` |
| version 缺失 | law.version=None（DB 未填） | warning `missing_law_version` |
| 三源齐全 | fact_refs + law_refs + standard_refs 全有 | 无 warning |

### 9.2 集成测试

| 场景 | 预期 |
|---|---|
| 合同审查场景 | `law_refs` 自动填充 `version` + `effective_date` |
| 变更扯皮场景 | `fact_refs` 关联 9 个事实键的 id |
| LLM 幻觉（编造 code）| EvidenceLinker 丢弃该 ref，标 warning |
| LLM 漏填 law_refs | 标 `no_legal_basis` warning（不阻塞，写入 DB）|

### 9.3 性能指标

| 指标 | 阈值 |
|---|---|
| EvidenceLinker 调用延迟 | < 50ms（纯 DB 查询 + 字典匹配）|
| 三源证据完整率（生产数据）| ≥ 95% |
| LLM 幻觉（编造 code）拦截率 | 100% |

---

## 十、决策点 vs 决策日志

本次设计**未修改**决策日志。建议加 1 条（如用户确认）：

```
### 2026-09 | 三源证据填充：EvidenceLinker 自动挂载 version + effective_date
- 决策: LLM 只填 (code, article_no/clause_no)；version/effective_date 由 EvidenceLinker 从 DB 匹配填充
- 背景: 应用原则 1（数据确凿）+ 应用原则 2（LLM 不生成关键数字）+ 应用原则 3（引用必须有版本）
- 备选: (a) LLM 直接填 version（违反应用原则 2）；(b) 手动让用户填（体验差）；(c) 不填 version（违反应用原则 3）
- 理由: EvidenceLinker 纯函数可重建（决策日志 §7）；防 LLM 幻觉；匹配快（<50ms）
- 影响/代价: Law 表加 version 列 + 回填；search_laws/search_standards 补字段；evidence_linker.py 新建
- 回退条件: 无（向后兼容，老数据 law_refs=[] 仍可写）
```

---

## 十一、与 W3-W8 前三轮的关系

| 轮 | 主题 | 输出 | 状态 |
|---|---|---|---|
| 1 | 状态机 + 事实卡 | `w3-w8-state-and-facts.md` | ✅ |
| 2 | LLM prompt 模板 + PromptStore | `w3-w8-llm-prompts.md` | ✅ |
| **3**（本文档） | 三源证据填充 | `w3-w8-triple-evidence.md` | ✅ |
| ⏭ 4 | 5 类文书模板（Jinja2）| `templates.py` 设计稿 | 待启动 |

### 4 轮的依赖关系

```
第 1 轮（状态机 + 事实卡）
  ↓
第 2 轮（LLM prompt）
  ↓
第 3 轮（三源证据）← 本轮
  ↓
第 4 轮（5 类文书）—— 文书生成依赖"已确认的事实 + 三源证据结论"
```
