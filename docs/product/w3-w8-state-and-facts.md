# W3-W8 变更扯皮场景 · 状态机与事实采集卡（第 1 轮设计）

> 日期：2026-09-18
> 状态：设计阶段，**未动代码**
> 范围：变更扯皮场景（`scenario="variation"`）的最小端到端可用版本
> 关联：`consultation_engine.py` 现状、`docs/product/ia.md` §六、`docs/architecture/data-model.md` §六/七

---

## 一、现状回顾（基于 `consultation_engine.py`）

### 1.1 已实现

| 能力 | 函数 | 备注 |
|---|---|---|
| 创建问诊 | `create_consultation` | `current_step="await_text"` 硬编码 |
| 一次性提交合同文本 | `submit_contract_text` | 写 `fact_key="contract_text"` |
| 多轮对话 | `chat_turn` | 写 ConsultationMessage + 自动抽取 facts |
| 启发式事实抽取 | `extract_fact_labels`（chat.py）| 强语气词匹配，confidence=0.8 |
| 报告就绪判断 | `is_information_sufficient`（chat.py）| 通用阈值法 |
| 流式生成报告 | `stream_report` | JSON Schema 严格模式 |
| 知识库检索 | `search_laws` | **仅合同审查**，未检索强条 |

### 1.2 关键问题（驱动本轮设计）

| # | 问题 | 影响 |
|---|---|---|
| 1 | `current_step` 字段未在状态流转时更新 | 状态机只在代码注释里 |
| 2 | 通用阈值判断不适用于变更扯皮 | "信息充分" 需要场景语义 |
| 3 | `law_refs` / `standard_refs` 始终空数组 | 三源证据（应用原则 1）断了 |
| 4 | 启发式抽取准确率低（置信度 0.8 偏乐观）| 变更扯皮事实结构化不达标 |
| 5 | 知识库检索只查 laws | 变更扯皮需要查强条（standards）|

---

## 二、变更扯皮状态机（6 节点）

### 2.1 状态流转图

```
   ┌──────────┐
   │  init    │  Consultation 创建
   └─────┬────┘
         │ 用户描述争议
         ▼
   ┌──────────────┐
   │ collecting   │  循环收集事实
   │   _facts     │  每轮 chat_turn + LLM JSON 抽取
   └─────┬────────┘
         │ 必填 fact_key 全部齐
         ▼
   ┌──────────────┐
   │ awaiting     │  用户确认"开始生成报告"
   │  _confirm    │  可继续补充事实
   └─────┬────────┘
         │ 用户点"确认生成"
         ▼
   ┌──────────────┐
   │ generating   │  LLM 流式生成报告
   │   _report    │  JSON Schema 严格模式
   └─────┬────────┘
         │ 流结束 + JSON 解析成功 + 三源证据填充
         ▼
   ┌──────────────┐
   │ generating   │  5 类文书（仅变更扯皮）
   │  _artifacts  │  Jinja2 模板 + LLM 润色
   └─────┬────────┘
         │ 完成
         ▼
   ┌──────────────┐
   │    done      │  status=completed
   └──────────────┘

异常路径：
   任意状态 ─user_abandon─▶ abandoned（用户主动 / 30 天无活动）
```

### 2.2 状态迁移触发表（P0-5 修复补全，2026-09-18）

> subagent 独立审阅指出：原设计只画了状态流转图，**6 个状态迁移的触发函数与触发条件完全没设计**——落地时 `current_step` 字段依旧形同虚设。本节补齐。

| # | 源状态 | 目标状态 | 触发函数 | 触发条件 |
|---|---|---|---|---|
| 1 | (无) | `init` | `create_consultation` | API 调用 `POST /consultations` |
| 2 | `init` | `collecting_facts` | `chat_turn` | 用户**首次**发送非空消息 |
| 3 | `collecting_facts` | `collecting_facts` | `chat_turn` | 必填 fact_key 未齐 + 用户继续输入 |
| 4 | `collecting_facts` | `awaiting_confirm` | `is_facts_sufficient` | 必填 fact_key 全部齐（variation 6 个）|
| 5 | `awaiting_confirm` | `collecting_facts` | `chat_turn` | 用户继续补充事实 |
| 6 | `awaiting_confirm` | `generating_report` | `POST /consultations/:id/confirm` | 用户点"确认生成报告" |
| 7 | `generating_report` | `generating_artifacts` | `generate_artifacts` | `stream_report` 完成 + JSON 解析成功 + 三源证据挂载通过 |
| 8 | `generating_report` | `failed` | `generate_report` | LLM 3 次 retry 仍失败（兜底）|
| 9 | `generating_artifacts` | `done` | `generate_artifacts` | 5 类文书全部生成 + 入库 |
| 10 | `generating_artifacts` | `failed` | `generate_artifacts` | 任意一类文书连续 3 次润色失败 |
| 11 | 任意非 done | `abandoned` | `abandon_consultation` | 用户主动 / 30 天无活动 |

### 2.3 节点定义（建议新增 `app/core/consultation_state.py`）

```python
class ConsultationStep(str, Enum):
    INIT = "init"
    COLLECTING_FACTS = "collecting_facts"
    AWAITING_CONFIRM = "awaiting_confirm"
    GENERATING_REPORT = "generating_report"
    GENERATING_ARTIFACTS = "generating_artifacts"
    DONE = "done"
    ABANDONED = "abandoned"


def is_facts_sufficient(scenario: str, facts: list[ConsultationFact]) -> bool:
    """场景特定义'信息充分'判断。"""
    if scenario == "variation":
        required = {"dispute_summary", "dispute_type", "dispute_date",
                    "parties_in_dispute", "evidence_list", "contract_clause_ref"}
        have = {f.fact_key for f in facts}
        return required.issubset(have) and any(
            f.fact_key == "evidence_list" and json.loads(f.fact_value)
            for f in facts
        )
    # contract_review: 复用现有 is_information_sufficient
    return is_information_sufficient(
        fact_count=len(facts),
        last_messages=[],  # 调用方传入
    )
```

### 2.3 与合同审查场景的关系

| 场景 | 状态机 | 复用 |
|---|---|---|
| `contract_review` | 现有简化（await_text → generating_report → done） | 不变 |
| `variation` | 6 节点新状态机 | 共享 `chat_turn` / `stream_report` 底层 |

按"原则 2：最简单实现"，**两场景状态机独立**，但共享底层函数。

---

## 三、事实采集卡（变更扯皮 9 个键）

### 3.1 字段定义

| fact_key | fact_label | fact_value_type | 必填 | 来源 |
|---|---|---|:-:|---|
| `dispute_summary` | 争议摘要 | text | ✓ | 用户 + AI 提炼 |
| `dispute_type` | 争议类型 | enum | ✓ | AI 推断 |
| `dispute_date` | 争议发生日期 | date | ✓ | 用户输入 |
| `parties_in_dispute` | 争议方 | json | ✓ | AI 抽取 |
| `contract_clause_ref` | 合同依据条款 | text | ✓ | 用户 + AI 引用 |
| `evidence_list` | 证据清单 | json | ✓ | AI 抽取 + 用户补充 |
| `evidence_complete` | 证据齐全确认 | bool | - | 用户确认 |
| `claimed_amount` | 索赔金额 | number | - | 用户输入 |
| `desired_outcome` | 期望结果 | enum | - | 用户选择 |

### 3.2 枚举值（新增 `app/core/constants.py`）

```python
class DisputeType(str, Enum):
    PAYMENT = "payment"          # 付款争议
    QUALITY = "quality"          # 质量争议
    SCHEDULE = "schedule"        # 工期争议
    SCOPE = "scope"              # 工程范围争议
    OTHER = "other"

class DesiredOutcome(str, Enum):
    EXTEND_COMPENSATION = "extend_compensation"   # 延期 + 索赔
    EXTEND_SCHEDULE = "extend_schedule"           # 仅延期
    QUALITY_FIX = "quality_fix"                   # 整改
    OTHER = "other"
```

### 3.3 JSON 字段 schema

#### `parties_in_dispute`（json）

```json
[
  {"role": "owner", "name": "XX 房地产开发公司"},
  {"role": "contractor", "name": "YY 建设集团"}
]
```

#### `evidence_list`（json）

```json
[
  {"type": "contract_clause", "ref": "8.1.2", "description": "付款方式条款"},
  {"type": "correspondence", "ref": "监理通知单 #005", "date": "2026-04-22"},
  {"type": "variation_order", "ref": "签证单 #012", "amount": "120万"}
]
```

---

## 四、LLM JSON 模式抽取策略

### 4.1 为什么用 LLM JSON 模式

按用户决策（2026-09-18）：**LLM JSON 模式抽取事实卡**。

理由：
- 启发式抽取（强语气词）准确率低（实测 confidence=0.8 偏乐观）
- LLM JSON Schema 严格模式 + retry，可控性高
- MiniMax-M3 支持 OpenAI 兼容 JSON mode（`tech-stack.md` 第 20 行）

### 4.2 Prompt 草案（实际写代码时细化）

```
你是一名工程争议顾问助手，需要从用户的最新一轮对话中抽取结构化事实。

【已知事实】
{facts_already_known}

【用户最新输入】
{new_user_content}

【支持的 fact_key】（仅从以下 9 个中抽取）
- dispute_summary (text): 争议摘要，一段话
- dispute_type (enum): payment / quality / schedule / scope / other
- dispute_date (date): YYYY-MM-DD
- parties_in_dispute (json): [{"role": "owner|contractor|...", "name": "..."}]
- contract_clause_ref (text): 合同条款号，如 "8.1.2"
- evidence_list (json): [{"type": "...", "ref": "...", "date": "..."}]
- evidence_complete (bool): 用户明确说"证据齐全"时为 true
- claimed_amount (number): 索赔金额（元），纯数字
- desired_outcome (enum): extend_compensation / extend_schedule / quality_fix / other

【输出格式】（严格 JSON，不要任何额外文字）
{
  "extracted_facts": [
    {
      "fact_key": "...",
      "fact_label": "...",
      "fact_value": "...",
      "fact_value_type": "...",
      "confidence": 0.0-1.0
    }
  ]
}

【抽取规则】
- 只抽取用户**明确陈述**的事实，不推断
- 多个事实分别列出
- 置信度：用户直说=1.0；从上下文推断=0.7-0.9；不确定<0.6
- 没有新事实时输出 {"extracted_facts": []}
```

### 4.3 兜底策略（P2-7 修复：confidence 阈值 0.7 硬闸门，2026-09-18）

> subagent 指出：原策略 confidence < 0.7 只 UI 标记，DB 仍写入——**绕过应用原则 2「LLM 不参与关键数字生成」**。
> 修复：service 层加 confidence 闸门，关键数字类 fact（`claimed_amount` / `dispute_date` / `contract_clause_ref`）< 0.7 直接落 `fact_value=""` + `fact_label="⚠️ 待人工确认"`，**不写库 LLM 推断的关键数字**。

| fact_key | 类型 | confidence 闸门 | < 0.7 行为 |
|---|---|---|---|
| `claimed_amount` | number | 0.7 | `fact_value=""` + `fact_label="⚠️ 待人工确认"`（不写库 LLM 推断金额）|
| `dispute_date` | date | 0.7 | 同上（不写库 LLM 推断日期）|
| `contract_clause_ref` | text | 0.7 | 同上（不写库 LLM 推断条款号）|
| `dispute_summary` | text | 0.5 | UI 标记（文本容忍度高）|
| `parties_in_dispute` | json | 0.6 | UI 标记 |
| `evidence_list` | json | 0.5 | UI 标记 |

#### P2-6 修复：fact_value 序列化策略统一封装

按 subagent 指出：第 1 轮文档没明确 fact_value 写库侧的序列化策略——json 类型的 fact（如 `evidence_list`）需要 `json.dumps()`，不统一封装会到处出错。

```python
# backend/app/services/fact_serializer.py (NEW)
import json
from datetime import date, datetime

def serialize_fact_value(value, fact_value_type: str) -> str:
    """统一序列化：写库前必须过这一层。

    - json 类型：json.dumps（紧凑格式）
    - date 类型：转 YYYY-MM-DD 字符串
    - 其他类型：str(value)
    """
    if fact_value_type == "json":
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    elif fact_value_type == "date":
        if isinstance(value, (date, datetime)):
            return value.isoformat()[:10]
        return str(value)  # 假定已经是字符串
    elif fact_value_type in ("number", "bool"):
        return str(value)
    else:  # text, enum
        return str(value)


def deserialize_fact_value(raw: str, fact_value_type: str):
    """读取时反序列化。"""
    if fact_value_type == "json":
        return json.loads(raw) if raw else None
    elif fact_value_type == "number":
        return float(raw) if raw else None
    elif fact_value_type == "bool":
        return raw.lower() == "true" if raw else None
    return raw  # text / date / enum
```

**强制约束**：所有 `chat_turn` / `extract_facts_system` 写库前必须调 `serialize_fact_value()`，所有读取前必须调 `deserialize_fact_value()`。

---

## 五、数据模型增量

### 5.1 Consultation 表（无新增字段）

现有 `current_step str(50)` 字段已够用，**只需在状态流转时更新**。

### 5.2 ConsultationFact 表（无新增字段）

现有字段够用 9 个事实键。`fact_value` 用 text 存（JSON/数字以字符串存）。

### 5.3 知识库查询（需补）

`knowledge_search.py` 现有 `search_laws` / `search_standards` 两函数已实现，**变更扯皮场景需同时调两者**（不只查 laws）。

变更：在 `stream_report` / `chat_turn` 中把 `search_laws` 改为：

```python
knowledge_hits = {
    "laws": await search_laws(db, search_text, limit=3),
    "standards": await search_standards(db, search_text, limit=3),
}
```

---

## 六、代码改动清单（设计稿，**未实施**）

按 `conventions.md` §二，新代码放对位置：

| 文件 | 类型 | 改动 |
|---|---|---|
| `backend/app/core/consultation_state.py` | 新建 | `ConsultationStep` 枚举 + `is_facts_sufficient` |
| `backend/app/core/constants.py` | 增量 | `DisputeType` / `DesiredOutcome` 枚举 |
| `backend/app/services/consultation_engine.py` | 修改 | `chat_turn` 改用 LLM JSON 抽取；`current_step` 状态流转 |
| `backend/app/services/chat.py` | 修改 | `extract_fact_labels` 升级为 `extract_facts_llm` |
| `backend/app/services/knowledge_search.py` | 修改 | 新增 `search_standards`（已有）+ `search_combined` |
| `backend/app/schemas/consultation.py` | 修改 | 新增事实卡的 Pydantic 类型 |
| `backend/app/api/v1/consultations.py` | 修改 | 暴露 `current_step` 字段、确认生成端点 |
| `frontend/src/types/consultation.ts` | 修改 | 新增事实键 TS 类型 |
| `frontend/src/views/Consultation.vue` | 修改 | 6 节点状态机 UI 渲染 |

按"原则 3：分层生长"，建议落地顺序：
1. **后端先**：枚举 + `consultation_state.py` + `extract_facts_llm`
2. **API 联通**：流式 + 状态字段
3. **前端 UI**：状态徽章 + 确认按钮
4. **端到端测试**

---

## 七、测试要点

| 项 | 验证 |
|---|---|
| 状态流转 | init → collecting_facts → ... → done 完整路径 |
| 异常路径 | 任意状态 → abandoned |
| 事实抽取 | 用户陈述事实 → LLM 输出 JSON → 写入 facts 表 |
| 抽取兜底（P2-7）| LLM 幻觉（金额/日期）→ confidence ≤ 0.7 → fact_value=""（不写库 LLM 推断的关键数字）|
| 序列化（P2-6）| json 类型 fact 走 `serialize_fact_value` → 写库；读取走 `deserialize_fact_value` |
| 信息充分 | 必填 6 个键齐 → 转 awaiting_confirm |
| 知识库 | laws + standards 都检索 → 三源证据完整 |

### P2-8 修复：MVP 不做的非功能性需求（2026-09-18）

> subagent 指出：4 轮文档缺失并发 / 限流 / 审计 / 缓存 / 监控的明确标注。本节集中声明 MVP 不做项。

| 需求 | MVP 是否做 | V2 评估 |
|---|:-:|---|
| **并发**：同一 consultation 多标签页同时打开 | ❌ | 评估 Postgres advisory lock |
| **限流**：用户狂点"重新生成报告" | ❌ | 评估 Redis 令牌桶（防 LLM 成本失控）|
| **审计**：输入输出日志（含完整 facts / 证据）| ❌ | 评估结构化日志 + 归档 7 天 |
| **缓存**：laws / standards 表频繁读 | ❌ | 评估 Redis 缓存（TTL 1h）|
| **监控**：LLM 调用成功率 / 延迟 | ❌ | 评估 Prometheus + Grafana |
| **降级**：LLM 失败时回退到 mock | ❌ | 违反应用原则 1（数据确凿优先）|

**为什么 MVP 不做**：1 人开发 + 12 周红线（决策日志 §2026-05），非功能性需求优先级低于核心场景端到端。**所有上述需求在 V2 阶段单独立项评估**，不在本设计范围内。

---

---

## 八、决策点 vs 决策日志

本次设计**未修改**决策日志。沿用：
- §1 数据确凿优先（事实卡 + confidence）
- §应用原则 2 LLM 不生成关键数字（金额/日期 confidence 兜底）
- §7 知识库与代码解耦（事实卡可重建，不依赖容器状态）

未来如需扩展（如增加事实键、加 V2 ProjectNote/ProjectClause 关联），先改决策日志再动代码。

---

## 九、与本轮相关的下一步

| 轮次 | 主题 | 输出 |
|---|---|---|
| ✅ 第 1 轮（本文档） | 状态机 + 事实卡 | 本文档 |
| ⏭ 第 2 轮 | LLM prompt 模板（变更扯皮）| `docs/ai-collab/prompt-templates.md` 增量 |
| ⏭ 第 3 轮 | 三源证据填充（law_refs / standard_refs / fact_refs）| `data-model.md` §七 增量 |
| ⏭ 第 4 轮 | 5 类文书模板 | `backend/app/services/templates.py` 设计稿 |
