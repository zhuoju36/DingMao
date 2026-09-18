"""事实抽取：把用户自然语言转成**规范 fact_key** 的事实卡。

## 为什么需要这个模块

此前 `consultation_engine.chat_turn` 用正则启发式抽"事实类型"，写入的
`fact_key` 是 `chat_turn_{n}`，而 `is_facts_sufficient` 比对的是
`VARIATION_REQUIRED_FACT_KEYS`（英文 snake_case）。两个集合按构造不相交，
导致 `collecting_facts → awaiting_confirm` 永远无法触发、状态机卡死在第一步。

本模块是**唯一的**事实写入口：只产出 `FACT_REGISTRY` 里登记过的键。

## 应用原则 2：LLM 不参与关键数字生成

`w3-w8-state-and-facts.md` §2.4 的置信度闸门在这里落地：

- **过闸门** → 写库（`accepted`）
- **未过闸门** → **不写库**（`pending`），由调用方提示用户手动补

刻意不采用"写一行空值 + `fact_label='⚠️ 待人工确认'`"的原设计：
空值行会让 `is_facts_sufficient` 的 `issubset(keys)` 判定**误判为已齐**
（键在、值为空），这正是要防的。列为 pending 后必填项自然仍是"缺失"，
清单显示 ○、AI 继续追问，语义自洽。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.core.constants import (
    FACT_REGISTRY,
    VARIATION_REQUIRED_FACT_KEYS,
    DesiredOutcome,
    DisputeType,
)
from app.core.exceptions import LLMResponseFormatError
from app.services.llm import LLMMessage, LLMTaskType, get_llm_client

# ===== 输出结构 =====


@dataclass
class ExtractedFact:
    """一条抽取结果（尚未落库）。"""

    fact_key: str
    fact_label: str
    fact_value: str          # 已序列化（json 类型走紧凑 JSON）
    fact_value_type: str
    confidence: float
    reason: str = ""         # 未过闸门时的原因说明


@dataclass
class ExtractionResult:
    """一次抽取的完整结果。"""

    accepted: list[ExtractedFact]     # 过闸门，可写库
    pending: list[ExtractedFact]      # 未过闸门，不写库，UI 提示待人工确认
    rejected: list[str]               # 非法键 / 非法格式，记 warning


# ===== Prompt =====
#
# V1 直接内联常量（AGENTS.md 原则 2：不做预防性抽象）。
# 升级为 app/core/prompts.py 的 PromptStore 时接口不变。

_SYSTEM = """你是工程法律问诊的**事实抽取器**。你的唯一任务是把用户的话转成结构化事实。

铁律：
1. 只输出 JSON，不要任何解释文字、不要 markdown 围栏。
2. 只能使用给定的 fact_key。用户提到的不在列表中的信息一律忽略。
3. 只抽取用户**明确说过**的内容。不要推断、不要补全、不要联想。
4. confidence 的赋值标准：
   - 1.0  = 用户直接、明确地说出了这个值
   - 0.7-0.9 = 用户的话里明确蕴含，但需要一步简单转换
   - 0.3-0.6 = 需要推断，或用户表述模糊
   - 0    = 无法确定
5. 关键数字红线（违反即视为抽取失败）：
   - 用户说「约 120 万」「大概」「左右」时，claimed_amount 的 confidence 必须 ≤ 0.7
   - 用户说「上周」「最近」「前阵子」时，**不要输出** dispute_date
   - 条款号必须能被用户原话直接支持，不要自己编
6. 值为「不知道 / 没说过 / 无法确定」的键，**不要出现在输出里**。

输出格式：{"facts": [{"fact_key": "...", "value": ..., "confidence": 0.0}]}
"""


def _build_user_prompt(
    user_content: str,
    existing_keys: set[str],
    evidence_context: list[str],
) -> str:
    """拼装抽取请求。schema 从 FACT_REGISTRY 生成，杜绝漂移。"""
    lines: list[str] = ["可用的 fact_key："]
    for key, spec in FACT_REGISTRY.items():
        mark = "必填" if spec.required else "选填"
        got = "【已提供】" if key in existing_keys else ""
        lines.append(
            f"- {key}（{spec.label}，类型 {spec.value_type}，{mark}）{got}"
        )

    # 枚举约束
    lines.append("")
    lines.append(f"dispute_type 只能是：{', '.join(e.value for e in DisputeType)}")
    lines.append(
        f"desired_outcome 只能是：{', '.join(e.value for e in DesiredOutcome)}"
    )

    # JSON 子结构
    lines.append("")
    lines.append("parties_in_dispute 格式：[{\"role\": \"owner\", \"name\": \"XX公司\"}]")
    lines.append(
        "evidence_list 格式：[{\"type\": \"photo\", \"ref\": \"现场照片\", "
        "\"description\": \"12 张\"}]"
    )
    lines.append(
        "evidence_list 的 type 只能是：contract_clause / correspondence / "
        "variation_order / inspection / photo / chat_record / other"
    )
    lines.append("dispute_date 必须是 YYYY-MM-DD")

    if existing_keys:
        lines.append("")
        lines.append(
            "标记【已提供】的键**不要重复输出**，除非用户本轮明确修正了它。"
        )

    if evidence_context:
        lines.append("")
        lines.append("以下是本项目档案中可用于本问诊的证据材料（可辅助 evidence_list）：")
        lines.extend(f"  · {e}" for e in evidence_context[:10])

    lines.append("")
    lines.append("用户原话：")
    lines.append(f"「{user_content}」")
    lines.append("")
    lines.append("只输出 JSON：")
    return "\n".join(lines)


# ===== 校验与归一 =====

_RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_JSON_TYPES = {"json"}
_NUM_TYPES = {"number"}


def _coerce(key: str, value: Any, value_type: str) -> Any:
    """把 LLM 给的值转成该 fact_key 期望的类型。

    Returns:
        归一后的值

    Raises:
        ValueError: 值形态非法（调用方记为 rejected）
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError("空值")

    if value_type in _JSON_TYPES:
        if isinstance(value, str):
            # LLM 偶尔把 JSON 当字符串给
            try:
                value = json.loads(value)
            except ValueError as e:
                raise ValueError(f"json 字段不是合法 JSON: {value!r}") from e
        if not isinstance(value, list):
            raise ValueError(f"json 字段应为列表，实得 {type(value).__name__}")
        if not value:
            raise ValueError("空列表")
        return value

    if value_type in _NUM_TYPES:
        if isinstance(value, bool):
            raise ValueError("布尔值不是数字")
        if isinstance(value, str):
            # 「86万」这类交给 LLM 在 prompt 里换算；此处只接受纯数字串
            cleaned = value.replace(",", "").replace("，", "").strip()
            try:
                value = float(cleaned)
            except ValueError as e:
                raise ValueError(f"数字字段无法解析: {value!r}") from e
        if not isinstance(value, (int, float)):
            raise ValueError(f"数字字段应为数字，实得 {type(value).__name__}")
        return value

    if value_type == "date":
        text = str(value).strip()
        if not _RE_DATE.match(text):
            raise ValueError(f"日期格式应为 YYYY-MM-DD，实得 {text!r}")
        return text

    if value_type == "bool":
        if isinstance(value, bool):
            return value
        raise ValueError(f"布尔字段应为 true/false，实得 {value!r}")

    if value_type == "enum":
        if key == "dispute_type":
            allowed = {e.value for e in DisputeType}
        elif key == "desired_outcome":
            allowed = {e.value for e in DesiredOutcome}
        else:
            allowed = set()
        text = str(value).strip()
        if allowed and text not in allowed:
            raise ValueError(f"{key} 取值非法: {text!r}，允许 {sorted(allowed)}")
        return text

    # text
    return str(value).strip()


def _serialize(value: Any, value_type: str) -> str:
    """序列化成 DB 字符串（与 fact_serializer 语义一致，此处避免循环 import）。"""
    if value_type == "json":
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if value_type == "bool":
        return "true" if value else "false"
    if value_type == "number":
        # 整数就不带小数点，便于前端直接展示
        return str(int(value)) if float(value).is_integer() else str(value)
    return str(value)


# ===== 主入口 =====


async def extract_facts(
    *,
    scenario: str,
    user_content: str,
    existing_keys: set[str] | None = None,
    evidence_context: list[str] | None = None,
) -> ExtractionResult:
    """从一轮用户输入中抽取规范事实。

    Args:
        scenario: 问诊场景；当前只对 "variation" 做结构化抽取
        user_content: 用户本轮原话
        existing_keys: 已入库的 fact_key（避免重复抽取）
        evidence_context: 项目档案里可用证据的摘要行（辅助 evidence_list）

    Returns:
        ExtractionResult。LLM 调用失败或 JSON 非法时抛 LLMError，由调用方决定降级。
    """
    if scenario != "variation":
        # 合同审查走另一条链（submit_text + 合同文本），不做事实卡抽取
        return ExtractionResult(accepted=[], pending=[], rejected=[])

    existing = existing_keys or set()
    client = get_llm_client()
    payload = await client.complete_json(
        LLMTaskType.CLAUSE_EXTRACTION,
        [
            LLMMessage("system", _SYSTEM),
            LLMMessage(
                "user",
                _build_user_prompt(user_content, existing, evidence_context or []),
            ),
        ],
        temperature=0.0,
    )

    raw_facts = payload.get("facts")
    if not isinstance(raw_facts, list):
        raise LLMResponseFormatError(
            f"抽取结果缺少 facts 数组。keys={sorted(payload.keys())}"
        )

    accepted: list[ExtractedFact] = []
    pending: list[ExtractedFact] = []
    rejected: list[str] = []
    seen: set[str] = set()

    for item in raw_facts:
        if not isinstance(item, dict):
            rejected.append(f"非对象条目: {item!r}")
            continue

        key = str(item.get("fact_key", "")).strip()
        spec = FACT_REGISTRY.get(key)
        if spec is None:
            rejected.append(f"未登记的 fact_key: {key!r}")
            continue
        if key in seen:
            rejected.append(f"重复的 fact_key: {key}")
            continue
        seen.add(key)

        try:
            value = _coerce(key, item.get("value"), spec.value_type)
        except ValueError as e:
            rejected.append(f"{key}: {e}")
            continue

        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(max(confidence, 0.0), 1.0)

        fact = ExtractedFact(
            fact_key=key,
            fact_label=spec.label,
            fact_value=_serialize(value, spec.value_type),
            fact_value_type=spec.value_type,
            confidence=confidence,
        )

        if confidence < spec.confidence_gate:
            # 应用原则 2：关键数字/日期/条款号的低置信推断值不写库
            fact.reason = (
                f"置信度 {confidence:.2f} 低于闸门 {spec.confidence_gate:.2f}"
            )
            pending.append(fact)
        else:
            accepted.append(fact)

    return ExtractionResult(accepted=accepted, pending=pending, rejected=rejected)


def missing_required_keys(existing_keys: set[str]) -> list[str]:
    """返回尚缺的必填 fact_key（保持登记表顺序，供 UI 与追问用）。"""
    return [
        k
        for k in FACT_REGISTRY
        if k in VARIATION_REQUIRED_FACT_KEYS and k not in existing_keys
    ]
