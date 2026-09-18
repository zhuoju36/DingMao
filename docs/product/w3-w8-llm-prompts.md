# W3-W8 变更扯皮场景 · LLM Prompt 模板（第 2 轮设计）

> 日期：2026-09-18
> 状态：设计阶段，**未动代码**
> 范围：变更扯皮场景的 4 个核心 LLM prompt 模板
> 关联：[第 1 轮](w3-w8-state-and-facts.md)、`chat.py` 现状、`consultation_engine.py`

---

## 一、现状回顾（基于 `chat.py`）

### 1.1 已实现的 prompt 模板

| 函数 | 用途 | 关键问题 |
|---|---|---|
| `build_chat_messages` | 多轮对话 system prompt | 角色 + 事实 + 知识库（仅 laws） |
| `build_report_messages` | 生成报告 system prompt | 角色 + 事实 + 知识库 + JSON 输出 |
| `extract_fact_labels` | 启发式事实抽取 | 关键词正则，无 schema |

### 1.2 现状不足（驱动第 2 轮）

| # | 问题 | 影响 |
|---|---|---|
| 1 | `build_chat_messages` 知识库只查 laws | 变更扯皮需要强条（standards）|
| 2 | `build_report_messages` JSON schema 简单 | 变更扯皮需要 law_refs / standard_refs / fact_refs 三源证据 |
| 3 | `extract_fact_labels` 是启发式（无 schema）| 第 1 轮决定用 LLM JSON 模式替换 |
| 4 | 没有专门的事实抽取 prompt | 第 1 轮需要 |
| 5 | 没有 5 类文书的生成 prompt | 第 4 轮需要，本轮先留接口 |

---

## 二、4 个核心 Prompt 模板（设计稿）

### 2.1 模板清单

| # | 模板名 | 触发节点 | 用途 |
|---|---|---|---|
| 1 | `chat_system` | `collecting_facts` | 多轮对话（追问 / 补充信息）|
| 2 | `extract_facts_system` | `collecting_facts` 每轮 chat_turn 后 | JSON Schema 抽取事实卡 |
| 3 | `report_system` | `generating_report` | 生成红黄绿报告 + 三源证据 |
| 4 | `artifact_system` | `generating_artifacts` | 5 类文书（仅变更扯皮，第 4 轮细化）|

按"原则 2：最简单实现"，本轮只细化 1/2/3，第 4 轮细化 `artifact_system`。

---

## 三、模板 1：chat_system（多轮对话）

### 3.1 触发场景

- 用户在 `collecting_facts` 状态输入新内容
- LLM 回复：追问 / 确认 / 建议补充
- **不**生成结构化报告

### 3.2 System Prompt

```python
SYSTEM_PROMPT = """你是钉铆（DingMao）的工程争议顾问助手。

# 当前场景
- 问诊类型：{scenario_label}
- 用户角色：{role_label}
- 当前状态：collecting_facts（事实收集阶段）

# 已收集的事实（按时间排列）
{facts_text}

如上述事实为空或不足 3 项，主动询问"请描述争议的核心事项"。

# 相关知识库（供参考，可信度依 🟨 法条 > 🟥 强条）
## 法条
{laws_text}

## 强条
{standards_text}

# 你的任务
1. 基于已收集事实 + 知识库，给出有针对性的反馈
2. **不重复**已知事实，只补充新视角或新问题
3. **关键询问清单**（按需追问）：
   - 若无 dispute_summary → "请用一段话描述争议"
   - 若无 dispute_date → "争议发生在哪一天？"
   - 若无 parties_in_dispute → "涉及哪些主体？业主/施工/监理？"
   - 若无 contract_clause_ref → "依据合同的哪一条？"
   - 若无 evidence_list → "您手头有哪些证据？合同/签证单/聊天记录等"
   - 若 claimed_amount 缺失且涉及金钱 → "索赔金额是多少？"
4. 如果所有**必填**事实已齐，明确告诉用户"信息已充分，可以生成报告"
5. 回答简洁（≤200 字），中文，专业但不晦涩

# 红线
- ❌ 不要编造法条或强条编号（只能引用知识库给的）
- ❌ 不要给出金额、时间、条款号的精确值（仅在用户已说明时引用）
- ❌ 不要长篇大论（≤200 字）
"""
```

### 3.3 Messages 拼接

```python
messages = [
    {"role": "system", "content": SYSTEM_PROMPT.format(...)},
    # 历史对话（最近 10 轮）
    *[{"role": m.role, "content": m.content} for m in recent_messages[-10:]],
    # 当前用户输入
    {"role": "user", "content": new_user_content},
]
```

---

## 四、模板 2：extract_facts_system（事实抽取）

### 4.1 触发场景

- `chat_turn` 每轮 LLM 回复后调用
- 输入：用户最新一轮 + 已收集事实
- 输出：JSON Schema 严格的 fact 列表

### 4.2 System Prompt

```python
EXTRACT_FACTS_SYSTEM = """你是钉铆的事实抽取器（不是顾问）。只做一件事：
从用户最新输入中抽取**结构化事实**，不推断、不解释、不补全。

# 已收集事实（避免重复抽取）
{existing_facts}

# 用户最新输入
{new_user_content}

# 支持的 fact_key（仅以下 9 个）
| fact_key | 类型 | 说明 | 示例 |
|---|---|---|---|
| dispute_summary | text | 争议摘要（一段话）| "业主拖延支付进度款 90 天" |
| dispute_type | enum | 争议类型 | payment / quality / schedule / scope / other |
| dispute_date | date | 争议发生日期 YYYY-MM-DD | "2026-04-15" |
| parties_in_dispute | json | 争议方 | [{"role": "owner", "name": "XX 公司"}] |
| contract_clause_ref | text | 合同条款号 | "8.1.2" |
| evidence_list | json | 证据清单 | [{"type": "contract_clause", "ref": "8.1.2"}] |
| evidence_complete | bool | 证据齐全确认 | true / false |
| claimed_amount | number | 索赔金额（元）| 1200000 |
| desired_outcome | enum | 期望结果 | extend_compensation / extend_schedule / quality_fix / other |

# 输出格式（严格 JSON，不要任何额外文字、不要 markdown 围栏）
{{
  "extracted_facts": [
    {{
      "fact_key": "...",
      "fact_label": "...",
      "fact_value": "...",
      "fact_value_type": "...",
      "confidence": 0.0-1.0
    }}
  ]
}}

# 抽取规则
- 只抽取用户**明确陈述**的事实，不推断
- 多个事实分别列出
- 置信度：
  - 1.0 = 用户直说
  - 0.7-0.9 = 用户陈述隐含
  - <0.6 = 不太确定（仍可抽取但前端标记 ⚠️）
- 已抽取的事实不重复
- 没新事实时输出 {{"extracted_facts": []}}

# 红线（应用原则 2：LLM 不生成关键数字）
- ❌ 不要把"约 120 万"转换为 1200000（confidence 必须 ≤0.7）
- ❌ 不要把"上周"转换为具体日期（discard，让用户输入）
- ❌ 合同条款号格式不符 X.Y.Z 时 discard
"""
```

### 4.3 JSON Schema（严格模式）

```python
EXTRACT_FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "extracted_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact_key": {"type": "string", "enum": [
                        "dispute_summary", "dispute_type", "dispute_date",
                        "parties_in_dispute", "contract_clause_ref",
                        "evidence_list", "evidence_complete",
                        "claimed_amount", "desired_outcome"
                    ]},
                    "fact_label": {"type": "string", "maxLength": 200},
                    "fact_value": {"type": "string"},
                    "fact_value_type": {"type": "string", "enum": [
                        "text", "number", "date", "enum", "json", "bool"
                    ]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["fact_key", "fact_label", "fact_value", "fact_value_type", "confidence"],
                "additionalProperties": False,
            }
        }
    },
    "required": ["extracted_facts"],
    "additionalProperties": False,
}
```

### 4.4 调用方式

```python
# 在 chat_turn 末尾追加
extracted = await client.json_completion(
    task=LLMTaskType.FACT_EXTRACTION,
    messages=[{"role": "system", "content": system}, {"role": "user", "content": user_input}],
    schema=EXTRACT_FACTS_SCHEMA,
    temperature=0.0,  # 抽取任务确定性
)

# 写入 facts（按规则过滤）
for f in extracted["extracted_facts"]:
    if not _passes_guard(f):  # 检查金额/日期/条款号合规
        f["confidence"] = min(f["confidence"], 0.6)
    db.add(ConsultationFact(...))
```

---

## 五、模板 3：report_system（生成报告 + 三源证据）

### 5.1 触发场景

- 用户在 `awaiting_confirm` 点"确认生成"
- 状态转 `generating_report`
- 输出：完整红黄绿报告 + 🟦🟨🟥 三源证据

### 5.2 System Prompt

```python
REPORT_SYSTEM = """你是钉铆的争议分析报告生成器。基于已收集事实 + 知识库，输出**结构化 JSON 报告**。

# 场景
- 问诊类型：{scenario_label}
- 用户角色：{role_label}

# 已收集事实
{facts_text}

# 知识库
## 法条
{laws_text}

## 强条
{standards_text}

# 输出 Schema（严格 JSON，不要任何额外文字）
{{
  "summary": "一句话结论（≤50 字）",
  "risks": [
    {{
      "level": "red|yellow|green",
      "title": "风险/争议要点（≤20 字）",
      "content": "详细分析（200-500 字）",
      "fact_refs": [<从已收集事实中选 fact.id>],
      "law_refs": [
        {{
          "code": "<法条 code>",
          "article_no": "<条款号>",
          "version": "<法律版本/年份>",
          "effective_date": "<生效日期 YYYY-MM-DD>"
        }}
      ],
      "standard_refs": [
        {{
          "code": "<标准 code>",
          "clause_no": "<强条号>",
          "version": "<标准版本/年份>",
          "is_mandatory": true
        }}
      ],
      "reasoning_chain": "推理过程（100-300 字）",
      "counter_arguments": "反方观点（100-200 字）"
    }}
  ]
}}

# 红黄绿分级标准
- 🔴 red：明确违法 / 合同无效 / 必须立即整改
- 🟡 yellow：风险较高 / 建议修改 / 有争议空间
- 🟢 green：风险可控 / 合规 / 可保留

# 三源证据原则（应用原则 1：数据确凿优先）
- 每个 risk **必须**挂 fact_refs + law_refs/standard_refs（至少一项）
- 如果知识库没有相关条款，把 law_refs 和 standard_refs 留空，但 reasoning_chain 必须说明"无明确依据"
- 绝不可凭印象编造条款号！

# 写作要求
- 中文专业但不晦涩
- 内容具体可执行（不要"建议加强管理"这种空话）
- 引用法条/强条时**严格按知识库**给出的 code 和 article_no
- 反方观点（counter_arguments）必须有，体现辩证思维
- 数量：3-7 条 risks，过多合并，过少补充
- summary **≤ 100 中文字符**（约 ≤ 200 字节）

# P2-1 trade-off 标注（MVP 不优化）
> 当前设计把所有 laws_hits + standards_hits 全量塞 system prompt，无场景化筛选。
> 估算：3 laws + 3 standards × 200 字符 + facts × 9 × 300 字符 ≈ 5-6K system prompt 长度。
> M3 1M 上下文放得下，但每次传完整知识库碎片有冗余。
> **MVP 不优化**，V2 可按 dispute_type 场景化筛选（如 `payment` 只塞付款相关法条）。
"""
```

### 5.3 JSON Schema（严格模式，P1-2 修复后版本，2026-09-18）

> subagent 指出：原 prompt 写 `≤50 字`、schema 写 `maxLength: 200`（字符）—— prompt 与 schema 漂移。修复：统一为 `summary ≤ 100 中文字符`（约 ≤ 200 字节）。
>
> 同时第 3 轮 §6 决定 LLM **不写** version / effective_date（应用原则 2），所以 `LAW_REF_SCHEMA` 只约束 `code` + `article_no`——`version` 由 EvidenceLinker 从 DB 填。

```python
REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        # P1-2 修复：maxLength 200 字符对应 ≤100 中文字
        "summary": {"type": "string", "maxLength": 200, "description": "一句话结论，≤100 中文字"},
        "risks": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "level": {"type": "string", "enum": ["red", "yellow", "green"]},
                    "title": {"type": "string", "maxLength": 100},
                    "content": {"type": "string", "minLength": 50, "maxLength": 2000},
                    "fact_refs": {"type": "array", "items": {"type": "integer"}},
                    # law_refs / standard_refs：LLM 只填 code + article_no/clause_no
                    # version / effective_date / is_mandatory 由 EvidenceLinker 填
                    "law_refs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string", "maxLength": 64},
                                "article_no": {"type": "string", "maxLength": 20},
                            },
                            "required": ["code", "article_no"],
                            "additionalProperties": False,  # P0-2 修复：禁 version 字段
                        },
                    },
                    "standard_refs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string", "maxLength": 64},
                                "clause_no": {"type": "string", "maxLength": 20},
                            },
                            "required": ["code", "clause_no"],
                            "additionalProperties": False,  # P0-2 修复：禁 version 字段
                        },
                    },
                    "reasoning_chain": {"type": "string"},
                    "counter_arguments": {"type": "string"},
                },
                "required": ["level", "title", "content", "fact_refs"],
            },
        },
    },
    "required": ["summary", "risks"],
}
```

### 5.4 三源证据填充（关键改进，P1-3 修复：委托 EvidenceLinker）

按现状 `stream_report` 第 419-421 行 `law_refs=[]` `standard_refs=[]` 是空数组，本轮必须修。**P1-3 修复**：原 `_attach_evidence` 是 `_match_law_ref` 的早期版本，且 `version` 字段依赖 Law 表未实装的字段——本轮直接**委托第 3 轮的 `EvidenceLinker.link_evidence`**：

```python
# 不再独立实现 _attach_evidence，直接复用第 3 轮的 EvidenceLinker
from app.services.evidence_linker import link_evidence

async def attach_evidence_to_conclusion(
    *,
    consultation_id: int,
    risks: list[dict],
    law_hits: list[dict],
    standard_hits: list[dict],
    fact_lookup: dict[int, ConsultationFact],
) -> list[ConsultationConclusion]:
    """委托 EvidenceLinker（详见第 3 轮 §四）实现三源证据自动挂载。"""
    validated_risks = await link_evidence(
        consultation_id=consultation_id,
        risks=risks,
        law_hits=law_hits,
        standard_hits=standard_hits,
        fact_lookup=fact_lookup,
    )
    return [
        ConsultationConclusion(
            consultation_id=consultation_id,
            level=r["level"],
            title=r["title"],
            content=r["content"],
            fact_refs=r["fact_refs"],
            law_refs=r.get("law_refs", []),
            standard_refs=r.get("standard_refs", []),
            reasoning_chain=r.get("reasoning_chain"),
            counter_arguments=r.get("counter_arguments"),
        )
        for r in validated_risks
    ]
```

P1-3 修复说明：`_match_law_ref` 在第 3 轮 §4.2 已经升级为支持 aliases + article_no 归一化（P0-1 修复），本节不再重复实现。
    # 同上 standard_refs
    return ConsultationConclusion(
        ...,
        fact_refs=fact_refs,
        law_refs=law_refs,
        standard_refs=standard_refs,
    )
```

按"原则 7：架构长远"，`knowledge_search.py` 的 `search_laws` / `search_standards` 需补 `version` 字段（`data-model.md` 第 230 行 Law 表有 `effective_date`，但没 `version`）— 这是数据模型增量。

---

## 六、Retry 与兜底策略

### 6.1 决策日志回退条件

决策日志 §2026-05 LLM 决策：
> **回退条件**: 实测 JSON 解析成功率 < 95% 或推理链人工评分 < 80% 时切换

### 6.2 Retry 策略

```python
async def call_with_retry(
    client: LLMClient,
    messages: list[dict],
    schema: dict,
    *,
    max_retries: int = 3,
) -> dict:
    """3 次重试：JSON 解析失败 → schema 不匹配 → 仍失败则降级"""
    for attempt in range(max_retries):
        try:
            text = await client.complete(messages, json_mode=True, schema=schema)
            return json.loads(text)
        except JSONDecodeError as e:
            logger.warning(f"JSON parse fail attempt {attempt+1}: {e}")
            if attempt == max_retries - 1:
                raise
            # 把错误塞进下一轮，让 LLM 修复
            messages = messages + [{"role": "user", "content": f"上次输出不是合法 JSON: {e}. 请重新输出。"}]
    raise ConsultationError("LLM 输出持续无法解析")
```

### 6.3 兜底降级

3 次失败后的兜底：
- **不**直接报错给用户（体验差）
- **不**用 mock 数据（违反应用原则 1）
- 写入一条 `system` 消息："⚠️ 因网络/服务问题暂无法生成完整报告，已保留您提供的所有事实。建议稍后重试。"
- 状态置 `failed`，**不**自动转 `done`

按"应用原则 4：文书前免责声明"，任何报告输出顶部必须有：

```python
DISCLAIMER = "⚠️ 以下报告仅供参考，重大决策请咨询执业律师复核。"
```

---

## 七、测试要点

### 7.1 单元测试

| 项 | 验证 |
|---|---|
| System prompt 模板渲染 | 输入参数填充正确，无 key 缺失 |
| JSON Schema 校验 | LLM 输出严格符合 schema |
| 三源证据挂载 | law_refs / standard_refs 字段正确填充 |
| 兜底路径 | LLM 持续失败 → 写 system 消息 + 状态 failed |

### 7.2 集成测试

| 场景 | 预期 |
|---|---|
| 完整 6 节点流程 | init → collecting_facts → awaiting_confirm → generating_report → done |
| LLM JSON 解析失败 | 3 次 retry 后降级，状态 failed |
| 合同审查场景（兼容性） | 不受影响，继续走现有 `chat_turn` 逻辑 |

### 7.3 性能指标（决策日志 §2026-05）

| 指标 | 阈值 | 测量方式 |
|---|---|---|
| JSON 解析成功率 | ≥ 95% | 100 份测试样本 |
| 推理链人工评分 | ≥ 80% | 5 份样本由项目所有者评分 |
| 单轮 chat_turn 延迟 | ≤ 8s | 端到端计时 |
| 报告生成延迟 | ≤ 30s | 端到端计时 |

---

## 八、决策点 vs 决策日志

本次设计**未修改**决策日志。沿用：
- §1 数据确凿优先（事实卡 + confidence + 三源证据）
- §应用原则 2 LLM 不生成关键数字（金额/日期/条款号 confidence 兜底）
- §应用原则 4 文书前免责声明
- §2026-05 LLM 决策的回退条件（JSON 解析 < 95% 切换）

数据模型增量（待第 3 轮细化）：
- `laws` 表补 `version` 字段（`data-model.md` 第 230 行缺）
- `standards` 表 `version` 字段已有（第 257 行）

---

## 九、与本轮相关的下一步

| 轮次 | 主题 | 输出 | 状态 |
|---|---|---|---|
| ✅ 第 1 轮 | 状态机 + 事实卡 | `w3-w8-state-and-facts.md` | 完成 |
| ✅ 第 2 轮（本文档） | LLM prompt 模板 | `w3-w8-llm-prompts.md` | 完成 |
| ⏭ 第 3 轮 | 三源证据填充 | `data-model.md` §七 增量 | 待启动 |
| ⏭ 第 4 轮 | 5 类文书模板 | `templates.py` 设计稿 | 待启动 |

---

## 十、System Prompt 解耦设计（2026-09-18 用户决策后追加）

### 10.1 为什么需要解耦

按 AGENTS.md "原则 7（架构长远眼光）" + `conventions.md` 第 14 行（"不写死魔法值，常量集中管理"）：

| 场景 | 需求 |
|---|---|
| A/B 测试不同 prompt | 改 prompt 不改代码 |
| 调整措辞（业务/法务）| 不让开发人员每次参与 |
| 加公司级免责声明 | 部署后调整 |
| 新增场景 | 加 prompt 不改 service 逻辑 |
| 审计/版本管理 | 看谁改过、什么时候改 |

### 10.2 三层 PromptStore 架构（P1-4 修复：拆 V1/V2 两阶段落地，2026-09-18）

> subagent 指出：MVP 阶段三层架构是过度设计，违反 AGENTS.md 原则 2「最简单实现」——V1 只需要"代码默认"就够。修复：拆 V1/V2 两阶段，V1 只交付 `DEFAULT_PROMPTS dict + render()` 接口，V2 再加 YAML 文件覆盖层。

```
优先级（高 → 低）：
  [V2+] 数据库 PromptStore     (未来支持 A/B、运行时改)
  [V2 ] 文件 PromptStore       ←── config/prompts/*.yaml（PROMPT_DIR 环境变量）
  [V1 ] 代码默认 PromptStore   ←── app/core/prompts.py（DEFAULT_PROMPTS 常量）
```

调用方无感：始终 `prompt_store.render(key, **vars)`，内部按优先级查找。

### 10.3 代码层（`app/core/prompts.py`，P1-4 修复 V1 简化版）

```python
"""Prompt 配置管理：V1 只用代码默认（V2 再加文件 / DB 覆盖）。

调用方：
    from app.core.prompts import prompt_store
    text = prompt_store.render("chat_system", scenario_label=..., role_label=..., facts_text=...)
"""
from jinja2 import Environment, StrictUndefined

# ====== V1：代码默认（与现有 prompt 等价，作为唯一来源）======
DEFAULT_PROMPTS: dict[str, str] = {
    "chat_system": """你是钉铆（DingMao）的工程争议顾问助手。
# 当前场景
- 问诊类型：{{ scenario_label }}
- 用户角色：{{ role_label }}
...""",
    "extract_facts_system": """你是钉铆的事实抽取器...""",
    "report_system": """你是钉铆的争议分析报告生成器...""",
    "artifact_system": """你是钉铆的文书生成器...""",  # 第 4 轮细化
}


class PromptStore:
    """V1：单层（代码默认）。V2 升级为多层（DB > 文件 > 代码）。"""

    def __init__(self) -> None:
        # V1 单一 jinja2 环境，所有 prompt 都用同一个 Environment
        self._env = Environment(
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined,  # 缺失变量报错（防静默错误）
        )

    def render(self, key: str, /, **vars) -> str:
        """渲染指定 key 的 prompt。V1 只查代码默认。"""
        if key not in DEFAULT_PROMPTS:
            raise KeyError(f"Prompt key '{key}' 不在 DEFAULT_PROMPTS 中")
        template = self._env.from_string(DEFAULT_PROMPTS[key])
        return template.render(**vars)

    # V2 扩展点（不在 V1 落地）：
    # def __init__(self, prompt_dir: str | None = None, db_session=None):
    #     self._file_env = ... if prompt_dir else None
    #     self._db_session = db_session


# 单例（整个进程共享）
prompt_store = PromptStore()
```

### 10.3.1 V2 升级路径（P1-4 修复预留）

V2 升级时**只改 `PromptStore` 类内部**，调用方 `prompt_store.render(key, **vars)` 不变。YAML 文件层和 DB 层作为 `__init__` 参数注入即可。

```python
# V2 伪代码（不实现，仅说明扩展方向）
class PromptStore:
    def __init__(
        self,
        prompt_dir: str | None = None,  # V2 YAML 文件覆盖
        db_session_factory=None,        # V2 DB 覆盖（A/B test）
    ):
        self._file_env = Environment(loader=FileSystemLoader(prompt_dir)) if prompt_dir else None
        self._db = db_session_factory

    def render(self, key, /, **vars):
        # 优先级：DB > 文件 > 代码默认
        if self._db:
            override = self._db.query(PromptOverride).filter_by(key=key).first()
            if override:
                return self._env.from_string(override.template).render(**vars)
        if self._file_env:
            try:
                source = self._file_env.loader.get_source(self._file_env, f"{key}.yaml")[0]
                return self._env.from_string(source).render(**vars)
            except Exception:
                pass
        return self._env.from_string(DEFAULT_PROMPTS[key]).render(**vars)
```

### 10.4 文件层（`config/prompts/chat_system.yaml`）

管理员可改：覆盖代码默认，**不影响部署**。

```yaml
# 钉铆 - 多轮对话 prompt（覆盖默认值）
name: chat_system
version: "1.0.0"        # 便于审计
updated_at: "2026-09-18"
author: "ops"
template: |
  你是钉铆（DingMao）的工程争议顾问助手。

  # 当前场景
  - 问诊类型：{{ scenario_label }}
  - 用户角色：{{ role_label }}
  - 当前状态：collecting_facts（事实收集阶段）

  # 已收集的事实（按时间排列）
  {{ facts_text }}

  # 相关知识库
  ## 法条
  {{ laws_text }}

  ## 强条
  {{ standards_text }}

  # 你的任务
  1. 基于已收集事实 + 知识库，给出有针对性的反馈
  2. ...
```

### 10.5 环境变量（`backend/.env.example` 增量）

```bash
# ====== Prompt 配置 ======
# 可选：自定义 prompt 目录（YAML 文件覆盖代码默认）
# 不设置则全部用代码默认（app/core/prompts.py DEFAULT_PROMPTS）
# PROMPT_DIR=/etc/dingmao/prompts
```

### 10.6 占位符引擎：jinja2

| 选项 | 选择 | 理由 |
|---|---|---|
| `jinja2>=3.1.4` | ✅ | 项目已有依赖（`pyproject.toml` 第 32 行）；支持控制流/循环/过滤器；与文书生成 Jinja2 同技术栈 |
| `str.format` | ❌ | prompt 内 `{}` 与 JSON 示例会冲突 |
| 无引擎 | ❌ | 调用方需自行渲染，复杂度上移 |

`undefined=StrictUndefined` 保证变量缺失**报错**而非静默渲染空字符串（防 prompt 漏字段导致 LLM 幻觉）。

### 10.7 与现状的兼容性

| 现状 | 改造后 | 影响 |
|---|---|---|
| `app/core/constants.py` 的 `DISCLAIMER` | **保留不动** | 常量级，与 PromptStore 并列 |
| `chat.py` 的 `build_chat_messages` 字符串拼接 | 改为 `prompt_store.render("chat_system", ...)` | 调用方式变，逻辑不变 |
| `consultation_engine.py` 现有调用 | **无需改动** | chat.py 是中间层 |
| `app/core/prompts.py` 新增 | **新增** | 与 constants.py 平级 |

按"原则 3：分层生长"，这是**增量改造**，不重写现有 service。

### 10.8 代码改动清单（更新，P1-1 + P1-4 + P2-2 修复后，2026-09-18）

> P1-1 修复：`LLMClient` 接口扩展（`json_completion` / `complete`）作为**前置依赖**列出——否则第 2 轮 + 第 3 轮 + 第 4 轮全部依赖新接口但没列改动清单。
>
> P1-4 修复：V1 只落地 `app/core/prompts.py` + DEFAULT_PROMPTS dict，**V2 再加 YAML 文件层**——避免 MVP 阶段过度设计。
>
> P2-2 修复：清理 `search_laws` 双定义（`chat.py:137` vs `knowledge_search.py:18`），统一保留 `knowledge_search.py` 一份。

| 文件 | 类型 | 改动 | 优先级 |
|---|---|---|:-:|
| **`backend/app/services/llm.py`** | **前置依赖：接口扩展** | `LLMClient` 加 `async def complete(messages, json_mode=False, schema=None) -> str` + `async def json_completion(messages, schema, **kwargs) -> dict`；原有 `stream_chat` 保留 | P0 前置 |
| `backend/app/core/prompts.py` | **新建（V1）** | `DEFAULT_PROMPTS` 常量 + `PromptStore` 类（V1 单层）+ `prompt_store` 单例 | P0 |
| `backend/app/services/chat.py` | 修改 | `build_chat_messages` 改用 `prompt_store.render("chat_system", ...)`；**删除**本地 `search_laws` 函数（迁移到 `knowledge_search.py`，P2-2 修复）| P0 |
| `backend/app/services/consultation_engine.py` | 修改 | `stream_report` 的 report_system 也走 `prompt_store.render("report_system", ...)` | P0 |
| `backend/app/services/knowledge_search.py` | 修改（P2-2）| `search_laws` 增加 `version` 字段返回（修复 §4.4 search_standards 的同类 bug）| P0 |
| `config/prompts/*.yaml` | **V2 暂不建** | V2 升级时再建 4 个 YAML（按 §10.3.1 升级路径）| V2 |
| `backend/.env.example` | V2 增量 | V2 升级时再加 `PROMPT_DIR` 配置项；V1 不需要 | V2 |
| `docs/architecture/data-model.md` | 不变 | 无 | — |
| `docs/product/decision-log.md` | 增量 | 加 1 条 2026-09 决策（详见 §10.9）| P1 |

### 10.9 决策点 vs 决策日志

本次设计**未修改**决策日志。建议加 1 条（如用户确认）：

```
### 2026-09 | System Prompt 解耦：代码默认 + 文件覆盖（jinja2）
- 决策: PromptStore 三层架构（DB V2+ > 文件 MVP > 代码默认 MVP），用 jinja2 渲染占位符
- 背景: 运维需要 A/B test、调措辞、加公司免责声明；AGENTS.md 原则 7 + conventions.md 第 14 行
- 备选: (a) 全 .env（KV 不适合多行）；(b) 只文件覆盖（部署需拷全套默认）；(c) 数据库（V2 过重）
- 理由: 业内共识（LangChain Hub、Anthropic Prompt Library）；代码默认保证开箱可用；文件覆盖给运维自由度；jinja2 项目已有依赖
- 影响/代价: app/core/prompts.py 新增；chat.py 改造调 prompt_store.render()；新增 4 个 YAML；undefined=StrictUndefined 防静默错误
- 回退条件: 无（向后兼容，未设 PROMPT_DIR 时与原 prompt 等价）
```
