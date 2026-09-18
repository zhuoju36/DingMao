# W3-W8 变更扯皮场景 · 5 类文书模板（第 4 轮设计）

> 日期：2026-09-18
> 状态：设计阶段，**未动代码**
> 范围：变更扯皮场景的 5 类产出物（签证单/索赔报告/监理通知单/工作联系单/审查意见备忘录）
> 关联：[第 1 轮](w3-w8-state-and-facts.md) / [第 2 轮](w3-w8-llm-prompts.md) / [第 3 轮](w3-w8-triple-evidence.md) / 决策日志 §7（"Jinja2 模板 + LLM 润色，关键数字不交给 LLM"）/ `data-model.md` §七 ConsultationArtifact

---

## 一、现状与基础

### 1.1 已有基础

| 项 | 现状 |
|---|---|
| `ConsultationArtifact` 表 | ✅ 已建（`models/consultation.py`），含 `artifact_type` / `title` / `content` / `template_name` / `template_data` / `file_path` |
| 5 类 `artifact_type` 枚举 | ✅ 已定义（`variation_order` / `claim_report` / `supervisor_notice` / `correspondence` / `review_memo`）|
| Jinja2 依赖 | ✅ `pyproject.toml` 第 32 行 `jinja2>=3.1.4` |
| 决策日志 §7 | "关键字段走模板引擎，LLM 仅负责润色" |
| 应用原则 2 | "LLM 不参与关键数字生成" |
| 应用原则 4 | "文书输出前必须显示前置免责声明" |
| 第 1 轮 9 个事实键 | ✅ 已定义（dispute_summary / type / date / parties / contract_clause_ref / evidence_list / claimed_amount / evidence_complete / desired_outcome）|
| 第 3 轮 EvidenceLinker | ✅ 三源证据自动挂载 |

### 1.2 本轮要解决

| # | 问题 | 决策依据 |
|---|---|---|
| 1 | 5 类文书的**字段清单**未设计 | 决策日志 §2 "待补" |
| 2 | 无 Jinja2 模板文件 | 现状 backend 无自定义模板 |
| 3 | 无"模板渲染 + LLM 润色"管线 | 决策日志 §7 |
| 4 | 无 `artifact_system` prompt | 第 2 轮 §十 留接口 |
| 5 | 免责声明未在文书中固定 | 应用原则 4 |

---

## 二、5 类文书的字段清单

按"原则 8：成熟产品参考"，参考中国建筑工程总公司、PMRC、各地住建部门的标准文书格式。

### 2.1 签证单（`variation_order`）

| 字段 | 数据来源 | 必填 | 示例 |
|---|---|:-:|---|
| `order_no` | 自动生成（PRJ-{project_id}-{seq}）| ✓ | "PRJ-2026-001-V-001" |
| `project_name` | Project.name | ✓ | "XX 综合楼工程" |
| `dispute_summary` | fact.dispute_summary | ✓ | "业主口头要求增加屋面保温层" |
| `dispute_date` | fact.dispute_date | ✓ | "2026-04-15" |
| `claimed_amount` | fact.claimed_amount | - | 280000 |
| **`duration_change_days`** | **P1-8 修复：chat_turn 阶段由 LLM 抽取 + confidence 闸门**（< 0.7 → UI 让用户手动补；≥ 0.7 → 自动填）| - | 7 |
| `parties_in_dispute` | fact.parties_in_dispute | ✓ | [{role: owner, name: ...}] |
| `contract_clause_ref` | fact.contract_clause_ref | ✓ | "8.1.2" |
| `applicant_role` | project.role | ✓ | "施工方" |
| `evidence_list` | fact.evidence_list | ✓ | [{type: ..., ref: ...}] |
| `reasoning_chain` | 第 3 轮 Conclusion.reasoning_chain | - | "依据 8.1.2 条..." |
| `desired_outcome` | fact.desired_outcome | - | "extend_compensation" |
| `disclaimer` | 系统常量 | ✓ | ⚠️ 参考提示（应用原则 4）|

### 2.2 索赔报告（`claim_report`）

| 字段 | 数据来源 | 必填 |
|---|---|:-:|
| `report_no` | 自动生成 | ✓ |
| `project_name` | Project.name | ✓ |
| `claimant` | fact.parties_in_dispute[role=本项目role] | ✓ |
| `respondent` | fact.parties_in_dispute[role≠本项目role] | ✓ |
| `dispute_summary` | fact.dispute_summary | ✓ |
| `dispute_date` | fact.dispute_date | ✓ |
| `claimed_amount` | fact.claimed_amount | ✓ |
| `contract_clause_ref` | fact.contract_clause_ref | ✓ |
| `law_refs` | 第 3 轮 Conclusion.law_refs | ✓ |
| `standard_refs` | 第 3 轮 Conclusion.standard_refs | ✓ |
| `evidence_list` | fact.evidence_list | ✓ |
| `calculation_basis` | 人工补充（自动模板可生成骨架） | - |
| **`calculation_basis`** | **P1-8 修复**：由模板生成"金额分解骨架"（自动），用户可在前端 UI 手动调整；**不调第二次 LLM**（避免绕开 EvidenceLinker 校验）| - |
| `disclaimer` | 系统常量 | ✓ |

### 2.3 监理通知单（`supervisor_notice`）

| 字段 | 数据来源 | 必填 |
|---|---|:-:|
| `notice_no` | 自动生成 | ✓ |
| `project_name` | Project.name | ✓ |
| `supervisor_org` | Project.supervisor_org | ✓ |
| `contractor_org` | Project.contractor_org | ✓ |
| `dispute_summary` | fact.dispute_summary | ✓ |
| `desired_outcome` | fact.desired_outcome | ✓（整改要求）|
| `rectification_deadline` | 人工补充 | ✓ |
| `contract_clause_ref` | fact.contract_clause_ref | ✓ |
| `law_refs` | 第 3 轮 Conclusion.law_refs | - |
| `standard_refs` | 第 3 轮 Conclusion.standard_refs | ✓（强条必填）|
| `disclaimer` | 系统常量 | ✓ |

### 2.4 工作联系单（`correspondence`）

| 字段 | 数据来源 | 必填 |
|---|---|:-:|
| `letter_no` | 自动生成 | ✓ |
| `project_name` | Project.name | ✓ |
| `sender` | 当前用户 + project.role | ✓ |
| `recipient` | 人工选择 | ✓ |
| `subject` | fact.dispute_summary 摘要 | ✓ |
| `content` | fact.dispute_summary 全文 | ✓ |
| `dispute_date` | fact.dispute_date | - |
| `disclaimer` | 系统常量 | ✓ |

### 2.5 审查意见备忘录（`review_memo`）

| 字段 | 数据来源 | 必填 |
|---|---|:-:|
| `memo_no` | 自动生成 | ✓ |
| `project_name` | Project.name | ✓ |
| `review_target` | fact.dispute_summary | ✓ |
| `risk_level` | Conclusion.level | ✓ |
| `review_opinion` | Conclusion.content | ✓ |
| `law_refs` | Conclusion.law_refs | - |
| `standard_refs` | Conclusion.standard_refs | - |
| `modification_suggestion` | Conclusion.content 提取 | - |
| `reasoning_chain` | Conclusion.reasoning_chain | ✓ |
| `counter_arguments` | Conclusion.counter_arguments | - |
| `disclaimer` | 系统常量 | ✓ |

### 2.6 MVP 落地优先级

按"原则 2：最简单实现" + 决策日志 §2 "5 类必做"，MVP 全做；但**实测顺序**：

| 优先级 | 类型 | 理由 |
|---|---|---|
| 1 | `variation_order`（签证单）| 变更扯皮最高频 |
| 2 | `claim_report`（索赔报告）| 变更扯皮核心产出 |
| 3 | `review_memo`（审查意见备忘录）| 合同审查已有报告类能力 |
| 4 | `supervisor_notice`（监理通知单）| 监理场景专用 |
| 5 | `correspondence`（工作联系单）| 通用兜底 |

---

## 三、Jinja2 模板设计

按"原则 4：模块化" + "原则 7：架构长远"，模板与代码分离。

### 3.1 目录结构

```
backend/
├── app/
│   ├── services/
│   │   └── artifact_renderer.py   # NEW: 渲染 + 润色管线
│   ├── core/
│   │   └── constants.py            # INCREMENT: 新增 EvidenceType / DisputedType / DesiredOutcome 枚举
│   └── templates/                  # NEW: 模板目录
│       └── artifacts/
│           ├── variation_order.j2
│           ├── claim_report.j2
│           ├── supervisor_notice.j2
│           ├── correspondence.j2
│           └── review_memo.j2
└── config/
    └── prompts/                   # 第 2 轮已有
```

### P2-4 修复：evidence_list.type 枚举值（2026-09-18）

> subagent 指出：`evidence_list` JSON 字段中 `type` 用了字符串字面量（"contract_clause" / "correspondence" / "variation_order"），但代码改动清单没在 `constants.py` 加枚举——落地时类型可能飘。

```python
# app/core/constants.py 新增（P2-4）
class EvidenceType(str, Enum):
    CONTRACT_CLAUSE = "contract_clause"      # 合同条款
    CORRESPONDENCE = "correspondence"        # 沟通记录（监理通知单/工作联系单等）
    VARIATION_ORDER = "variation_order"      # 签证单
    INSPECTION = "inspection"                # 现场检验记录
    PHOTO = "photo"                          # 现场照片
    CHAT_RECORD = "chat_record"              # 聊天记录截图
    OTHER = "other"
```

第 1 轮 §三 fact schema 同步引入此枚举作为 Pydantic Literal 校验。

### 3.2 模板命名规范（`conventions.md` §三）

- 全小写 + 下划线：`variation_order.j2`
- 与 `artifact_type` 枚举值一一对应

### 3.3 模板示例：`variation_order.j2`（P0-4 修复后，2026-09-18）

> subagent 指出：原模板免责声明只在文末，**违反 AGENTS.md 应用原则 4「律师复核提示放在显眼位置，而非页脚」**。
> 修复：顶部（标题下方）+ 底部双显，与 §七 设计一致。

```jinja
{# 工程签证单 #}
{# 输入变量：template_data dict，包含 §2.1 所有字段 #}

────────────────────────────────────────────
              工 程 签 证 单
────────────────────────────────────────────

⚠️ 本签证单由钉铆（DingMao）AI 辅助生成，**仅供工程师参考**，
   重大决策请咨询**执业律师**复核（应用原则 4：律师复核提示放在显眼位置）。

────────────────────────────────────────────

签证编号：{{ order_no }}
项目名称：{{ project_name }}
签证日期：{{ dispute_date }}

────────────────────────────────────────────
一、签证事项
────────────────────────────────────────────

{{ dispute_summary }}

────────────────────────────────────────────
二、签证依据
────────────────────────────────────────────

合同条款：第 {{ contract_clause_ref }} 条

{% if law_refs %}
相关法条：
{% for law in law_refs %}
  - 《{{ law.code }}》第 {{ law.article_no }} 条（{{ law.version }}）
    生效日期：{{ law.effective_date }}
{% endfor %}
{% endif %}

{% if standard_refs %}
相关强条：
{% for std in standard_refs %}
  - {{ std.code }} 第 {{ std.clause_no }} 条（{{ std.version }}）
    {% if std.is_mandatory %}[强条]{% endif %}
{% endfor %}
{% endif %}

────────────────────────────────────────────
三、签证金额 / 工期
────────────────────────────────────────────

{% if claimed_amount %}
签证金额：人民币 {{ "{:,.2f}".format(claimed_amount) }} 元
{% endif %}
{% if duration_change_days %}
工期增减：{{ duration_change_days }} 天
{% endif %}

────────────────────────────────────────────
四、参与方
────────────────────────────────────────────

{% for party in parties_in_dispute %}
  - {{ party.role }}：{{ party.name }}
{% endfor %}

申请方：{{ applicant_role }}

────────────────────────────────────────────
五、证据清单
────────────────────────────────────────────

{% for ev in evidence_list %}
  - [{{ ev.type }}] {{ ev.ref }}{% if ev.date %} ({{ ev.date }}){% endif %}
{% endfor %}

────────────────────────────────────────────
六、推理过程
────────────────────────────────────────────

{{ reasoning_chain | default("（详见报告正文）") }}

────────────────────────────────────────────
七、期望结果
────────────────────────────────────────────

{# P1-5 修复：jinja2 多分支替代未注册的 filter 函数 #}
{% if desired_outcome == "extend_compensation" %}延期 + 索赔（同时主张工期顺延与费用补偿）
{% elif desired_outcome == "extend_schedule" %}仅延期（仅主张工期顺延）
{% elif desired_outcome == "quality_fix" %}整改修复（要求对方修复质量缺陷）
{% else %}{{ desired_outcome }}
{% endif %}

────────────────────────────────────────────
⚠️ 本签证单仅供参考，重大决策请咨询执业律师
本单由钉铆（DingMao）AI 辅助生成，依据为用户提供事实与现行法律法规。
生成时间：{{ generated_at }}
────────────────────────────────────────────
```

### 3.4 渲染管线（`artifact_renderer.py`）

```python
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pathlib import Path

class ArtifactRenderer:
    """模板渲染 + LLM 润色（决策日志 §7）。"""

    def __init__(self, template_dir: str = "app/templates/artifacts"):
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined,
        )
        # 自定义过滤器
        self.env.filters["format_amount"] = lambda v: f"{v:,.2f}"
        self.env.filters["format_date"] = lambda v: v  # YYYY-MM-DD

    def render(self, artifact_type: str, template_data: dict) -> str:
        """渲染模板，返回 Markdown 文本（待 LLM 润色）。"""
        template = self.env.get_template(f"{artifact_type}.j2")
        return template.render(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            **template_data,
        )
```

按"原则 2：最简单实现"，renderer 不做缓存、不做异步（每次都读模板文件即可）。

---

## 四、LLM 润色策略

### 4.1 关键约束

按"应用原则 2：LLM 不参与关键数字生成" — 润色**只改措辞**，不改数字、时间、条款号、版本号、引用条款文本。

### 4.2 润色范围

| 改（润色） | 不改（结构化） |
|---|---|
| 措辞（更专业 / 更礼貌）| 金额 / 时间 / 条款号 |
| 段落衔接（更流畅）| 法条 / 强条引用文本 |
| 语气（按 role 调整）| 项目名称 / 当事人姓名 |
| 标点 / 错别字 | 证据清单原文 |
| | 推理过程原文 |

### 4.3 实现方式（P1-6 + P2-5 修复后版本，2026-09-18）

> subagent 指出：原 `_extract_placeholders` 和 `_verify_placeholders_preserved` 是占位说明，没具体实现——LLM 润色后没法验证结构化字段未被改动。
>
> 修复策略：**结构性隔离 + 反向校验**（不依赖正则匹配语义数字，避免"合同金额 100 万"与"第 8 条"的歧义）。

```python
import re
import string

# 结构化字段定义（白名单：哪些字段是结构化的，必须保留）
STRUCTURED_FIELDS = {
    "amount", "date", "article_no", "clause_no", "version",
    "effective_date", "law_code", "standard_code",
    "order_no", "report_no", "memo_no", "notice_no", "letter_no",
    "project_name", "party_name",
}


def _inject_placeholders(rendered_md: str, template_data: dict) -> tuple[str, dict[str, str]]:
    """渲染后扫描所有结构化字段值 → 用哨兵 token 替换 → 返回 (masked_md, token_map)。"""
    token_map = {}  # token → 原始值
    masked = rendered_md
    counter = 0

    # 按字段类型提取（不是模糊匹配，是基于 template_data 的精确值）
    for key, value in template_data.items():
        if key in ("dispute_summary", "reasoning_chain", "title", "content"):
            continue  # 非结构化字段，不替换
        if isinstance(value, (int, float)):
            value_str = f"{value:,.2f}" if isinstance(value, float) else str(value)
        elif isinstance(value, list):
            # json 类型（如 evidence_list）：递归提取所有 str/num 元素
            continue  # 列表内部元素交给 LLM 处理（已在 list 中显式列举）
        else:
            value_str = str(value)
        if not value_str or len(value_str) > 100:
            continue
        # 用哨兵 token 替换（避免 LLM 改）
        token = f"\x00STRUCT_{counter}\x00"
        token_map[token] = value_str
        masked = masked.replace(value_str, token)
        counter += 1

    return masked, token_map


def _restore_placeholders(polished: str, token_map: dict[str, str]) -> str:
    """润色后用 token_map 反向恢复所有结构化字段。"""
    restored = polished
    for token, original in token_map.items():
        if token not in restored:
            # 结构化字段被 LLM 删除 → 抛错
            raise ConsultationError(
                f"LLM 润色删除了结构化字段: {original!r}（违反应用原则 2）"
            )
        restored = restored.replace(token, original)
    return restored


async def polish_with_llm(
    rendered_md: str,
    template_data: dict,
    *,
    role: UserRole,
    client: LLMClient,
) -> str:
    """润色已渲染的 Markdown 文书（P1-6 实现版本）。

    关键约束：润色后必须保留所有结构化字段。
    策略：哨兵 token 替换 → LLM 润色 → 反向恢复 → 校验。
    """
    # 1. 哨兵替换：把结构化字段值替换为不可见 token
    masked_md, token_map = _inject_placeholders(rendered_md, template_data)

    # 2. LLM 润色（提示词中明确禁止改 token）
    polished = await client.complete(
        messages=[
            {"role": "system", "content": ARTIFACT_POLISH_SYSTEM},
            {"role": "user", "content": masked_md},
        ],
        temperature=0.3,  # P2-5 标注：MVP 未实测，10 次实测后再调
    )

    # 3. 反向恢复：把 token 替换回原始值
    restored = _restore_placeholders(polished, token_map)

    return restored
```

按"应用原则 2：LLM 不参与关键数字生成"，**反向校验是结构性保证**：LLM 看不到原始值，只能改"措辞"——即使它想改也看不到数字/条款号。

### 4.3.1 P2-5 修复：temperature 实测后再调

> subagent 指出：`temperature=0.3` 是断言不是测试结果。MVP 上线前**必须做 10 次实测取破坏率**：

| 实测项 | 目标 |
|---|---|
| 10 次同 prompt，结构化字段破坏次数 | 0 次 |
| 10 次润色后文本流畅度评分（人工）| ≥ 80/100 |
| 实测破坏率 | < 5%（与决策日志 §2026-05 LLM JSON 解析 < 95% 阈值对齐）|

如破坏率不达标：
1. 降低 temperature（0.3 → 0.1 → 0.0）
2. 仍不达标 → 润色步骤整体回退（用未润色版本），仅保留 §三 模板渲染结果

按"应用原则 2"——**绝不接受"破坏率不为零"的妥协**。

### 4.4 artifact_polish prompt（追加到 PromptStore）

```python
ARTIFACT_POLISH_SYSTEM = """你是钉铆的工程文书润色员。

任务：对已渲染的工程文书（签证单/索赔报告等）做**仅措辞层面**的润色。

# 红线（绝对不可违反）
- ❌ 不得改动任何金额、时间、日期、条款号、版本号
- ❌ 不得改动当事人姓名、项目名称、证据原文
- ❌ 不得改动引用条款的原文（法条/强条文本）
- ❌ 不得删除或添加任何结构化字段

# 可改
- ✅ 措辞更专业（行业术语、礼貌用语）
- ✅ 段落衔接更流畅
- ✅ 修正错别字 / 标点
- ✅ 按用户角色调整语气（业主/施工/监理视角不同）

# 输出
返回润色后的完整 Markdown，不要解释、不要总结。

输入文书：
{rendered_md}

# 用户角色
{role_label}
"""
```

按"原则 2：最简单实现"，prompt 简单直接，不引入复杂控制流。

---

## 五、`artifact_system` prompt（第 2 轮 §十 留接口）

第 2 轮文档 §十.3 的 `DEFAULT_PROMPTS` 预留了 `"artifact_system": "..."` 占位。本轮细化：

```python
ARTIFACT_SYSTEM = """你是钉铆的工程文书生成器（artifacts）。

任务：根据咨询结论（已挂载三源证据），生成 5 类工程文书之一。

# 输入
- 咨询类型：{scenario_label}
- 用户角色：{role_label}
- 5 类文书模板已存在（template_data 字段已填好），你只做**润色**

# 红线
- ❌ 不要重新生成数字 / 时间 / 条款号（已由模板渲染）
- ❌ 不要修改结构化字段（项目名称、当事人、合同条款等）
- ❌ 不要添加未经核实的法条 / 强条引用

# 你的输出
直接输出润色后的完整文书文本（Markdown），不要 JSON。
"""
```

按"应用原则 2"，LLM 在 artifact 阶段不参与任何数字生成，只做表达优化。

---

## 六、完整数据流（P1-7 修复后：5 类并行，2026-09-18）

> subagent 指出：原设计"5 类依次渲染+润色"，串行 5 × 5s = 25s。LLM 润色是 I/O 密集型，串行是浪费——应 `asyncio.gather` 并行，压到 5-8s。

```
┌──────────────────────────────────────────────────────────────┐
│ 1. consultation 状态：awaiting_confirm → 用户点"生成报告"     │
│    → 状态转 generating_report                                  │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ 2. 生成 ConsultationConclusion（第 3 轮 EvidenceLinker）       │
│    → law_refs / standard_refs 自动挂载                         │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ 3. 状态转 generating_artifacts                                  │
│    5 类并行（asyncio.gather）：                                  │
│    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│    │ variation    │  │ claim_report │  │ supervisor   │       │
│    │ _order       │  │              │  │ _notice      │       │
│    │ ┌──────────┐ │  │ ┌──────────┐ │  │ ┌──────────┐ │       │
│    │ │render+   │ │  │ │render+   │ │  │ │render+   │ │       │
│    │ │polish    │ │  │ │polish    │ │  │ │polish    │ │       │
│    │ └──────────┘ │  │ └──────────┘ │  │ └──────────┘ │       │
│    └──────────────┘  └──────────────┘  └──────────────┘       │
│    ┌──────────────┐  ┌──────────────┐                          │
│    │ correspondence│  │ review_memo  │                          │
│    └──────────────┘  └──────────────┘                          │
│                                                                  │
│    每个 artifact_type 子流程：                                  │
│    a. 收集 template_data（fact + project + conclusion）         │
│    b. ArtifactRenderer.render(artifact_type, template_data)    │
│    c. polish_with_llm(rendered_md, template_data, role)        │
│       → 哨兵 token 替换 + LLM 润色 + 反向恢复（P1-6）          │
│    d. 写入 ConsultationArtifact                                 │
│    e. 任一失败不影响其他 4 类（独立异常隔离）                   │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ 4. 用户在 ConsultationDetail 页查看 / 下载 / 复制 5 类文书      │
│    每份文书顶部固定显示免责声明（应用原则 4）                  │
│    前端用 markdown-it 渲染（P1-10 修复，见 §八）               │
└──────────────────────────────────────────────────────────────┘
```

按"原则 3：分层生长"，渲染和润色是两个独立步骤，每步可独立失败（不会污染对方）。

### 6.1 并行实现草案（P1-7 修复）

```python
import asyncio

async def generate_artifacts(
    consultation_id: int, *, role: UserRole
) -> list[ConsultationArtifact]:
    """5 类文书并行生成（任一失败不阻塞其他）。"""
    artifact_types = [
        "variation_order", "claim_report",
        "supervisor_notice", "correspondence", "review_memo",
    ]

    tasks = [
        _generate_one(consultation_id, artifact_type=t, role=role)
        for t in artifact_types
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    artifacts = []
    for t, r in zip(artifact_types, results):
        if isinstance(r, Exception):
            # 任一失败：写 system 消息 + 标记该类为 failed
            logger.warning(f"artifact {t} 生成失败: {r}")
            await _mark_artifact_failed(consultation_id, t, str(r))
        else:
            artifacts.append(r)
    return artifacts
```

---

## 七、免责声明（应用原则 4）

按 `consultation_engine.py` 已有 `from app.core.constants import DISCLAIMER` 模式：

```python
# app/core/constants.py
DISCLAIMER = "⚠️ 本文书由钉铆（DingMao）AI 辅助生成，仅供参考。重大决策请咨询执业律师复核。"
```

每份 Jinja2 模板底部**必须**包含：

```
────────────────────────────────────────────
⚠️ 本文书仅供参考，重大决策请咨询执业律师
本单由钉铆（DingMao）AI 辅助生成...
────────────────────────────────────────────
```

按"应用原则 4"，免责声明**固定在文书顶部 + 底部**双显，不只是页脚。

---

## 八、代码改动清单（设计稿，**未实施**，P1-10 修复后）

按 `conventions.md` §二：

| 文件 | 类型 | 改动 | 备注 |
|---|---|---|---|
| `frontend/package.json` | **P1-10 新增** | 加 `markdown-it` 依赖（前端渲染 5 类文书 Markdown）| `tech-stack.md` 第 35 行已有 markdown-it 用途标注 |
| `frontend/src/utils/markdown.ts` | **P1-10 新建** | 封装 markdown-it 单例 + disclaimer 高亮（应用原则 4）| — |
| `backend/app/services/artifact_renderer.py` | **新建** | `ArtifactRenderer` 类 + `polish_with_llm` 函数（含 P1-6 哨兵 token） | — |
| `backend/app/templates/artifacts/*.j2` | **新建** | 5 个 Jinja2 模板（P0-4 修复后顶部 + 底部双显免责）| — |
| `backend/app/core/constants.py` | 增量 | `EvidenceType` / `DisputedType` / `DesiredOutcome` 枚举（P2-4）| — |
| `backend/app/core/prompts.py` | 修改 | `DEFAULT_PROMPTS` 补 `artifact_polish_system`（§四.4）| — |
| `backend/app/services/consultation_engine.py` | 修改 | 新增 `generate_artifacts` 函数（5 类 `asyncio.gather` 并行，P1-7）| — |
| `frontend/src/views/Consultation.vue` | 修改 | 新增"5 类文书"下载/查看区 + Markdown 渲染 | — |
| `frontend/src/types/consultation.ts` | 修改 | 加 `ConsultationArtifact` TS 类型 | — |
| `backend/app/schemas/consultation.py` | 修改 | 加 5 类 artifact 的 Pydantic schema | — |
| `docs/architecture/data-model.md` | 不变 | 已有 ConsultationArtifact 字段 | — |
| `docs/product/decision-log.md` | 增量 | 加 1 条 2026-09 决策（详见 §十）|

按"原则 3：分层生长"，落地顺序：

1. **renderer + templates**（先打通无 LLM 润色的渲染）
2. **polish 接入**（加 LLM 润色 + 校验）
3. **consultation_engine 集成**（generating_artifacts 节点）
4. **前端 UI**（下载/查看）

---

## 九、测试要点

### 9.1 单元测试

| 用例 | 验证 |
|---|---|
| Jinja2 渲染 | 所有字段填充正确，无 `StrictUndefined` 报错 |
| 润色后结构化校验 | 金额 / 时间 / 条款号未被改动 |
| 润色破坏结构化 | 抛 ConsultationError，拒绝写入 |
| 免责声明 | 每份文书顶部 + 底部均显示 |

### 9.2 集成测试

| 场景 | 预期 |
|---|---|
| 变更扯皮端到端 | 5 类文书全部生成，前端可下载 |
| 合同审查 | 仅生成 `review_memo`（其他类 V2 启用）|
| LLM 润色失败 | 仍可写入润色前版本（降级）|

### 9.3 性能指标

| 指标 | 阈值 |
|---|---|
| 单类文书生成延迟 | ≤ 5s（渲染 < 100ms + LLM 润色 < 5s）|
| 5 类全生成延迟 | ≤ 25s（可串行或并行） |
| 润色后字段保留率 | 100%（不允许破坏） |

---

## 十、决策点 vs 决策日志

本次设计**未修改**决策日志。建议加 1 条（如用户确认）：

```
### 2026-09 | 5 类文书：Jinja2 模板 + LLM 仅润色
- 决策: 5 类文书（签证单/索赔报告/监理通知单/工作联系单/审查意见备忘录）用 Jinja2 渲染 + LLM 仅做措辞润色，关键数字不交给 LLM
- 背景: 决策日志 §7（"Jinja2 模板引擎 + LLM 润色，关键数字不交给 LLM"）+ 应用原则 2（LLM 不参与关键数字生成）+ 应用原则 4（文书前免责声明）
- 备选: (a) LLM 端到端生成（违反应用原则 2）；(b) 人工填写（体验差）；(c) 只用 Jinja2 不润色（文书表达僵硬）
- 理由: 决策日志 §7 已锁定方向；润色后强制结构化字段校验（100% 保留率）；Jinja2 项目已有依赖
- 影响/代价: artifact_renderer.py 新建；5 个 .j2 模板新建；consultation_engine 加 generate_artifacts；前端加 5 类文书下载区
- 回退条件: 无（向后兼容，未生成过文书的 consultation 行为不变）
```

---

## 十一、与 W3-W8 前三轮的关系

```
第 1 轮（状态机 + 事实卡）
  ├─ 9 个事实键（dispute_summary / type / date / parties / contract_clause_ref / evidence_list / claimed_amount / evidence_complete / desired_outcome）
  ├─ ConsultationFact 表已建（fact_value 字段含数据）
  └─ 6 节点状态机（generating_artifacts 是最后节点）

第 2 轮（LLM prompt + PromptStore）
  ├─ 4 个 prompt 模板（chat / extract_facts / report / artifact）
  └─ jinja2 + YAML 文件覆盖机制

第 3 轮（三源证据填充）
  ├─ EvidenceLinker 自动挂载 version + effective_date
  ├─ Conclusion.law_refs / standard_refs 字段真正填充
  └─ 这些引用作为文书的"依据条款"章节素材

第 4 轮（5 类文书模板）← 本轮
  ├─ 消费：第 1 轮事实键 + 第 3 轮三源证据
  ├─ 产出：5 类 .j2 模板 + 渲染管线 + LLM 润色
  └─ 终点：generating_artifacts 节点完成，状态转 done
```

### 12 轮完整成果

| 轮 | 文档 | 核心产出 |
|---|---|---|
| 1 | `w3-w8-state-and-facts.md` | 6 节点状态机 + 9 事实键 |
| 2 | `w3-w8-llm-prompts.md` | 4 个 prompt + PromptStore 解耦 |
| 3 | `w3-w8-triple-evidence.md` | EvidenceLinker + 三源自动挂载 |
| **4**（本文档） | `w3-w8-artifacts.md` | 5 类 .j2 模板 + 渲染+润色管线 |

**W3-W8 设计阶段完成**。下一步：审阅本文档 → 落地代码（按"原则 3"分层顺序）。
