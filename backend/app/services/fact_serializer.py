"""事实卡序列化（W3-W8 第 1 轮 P2-6 修复）。

统一封装 ConsultationFact.fact_value 的读写序列化：
- json 类型：json.dumps（紧凑格式）
- date 类型：YYYY-MM-DD 字符串
- 其他类型：str()

所有 chat_turn / extract_facts_system 写库前必须调 serialize_fact_value()，
所有读取前必须调 deserialize_fact_value()。避免 json.loads 散落各处。
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any


def serialize_fact_value(value: Any, fact_value_type: str) -> str:
    """序列化为字符串（写库前调用）。

    Args:
        value: 原始值
        fact_value_type: text / number / date / enum / json / bool

    Returns:
        数据库存字符串
    """
    if fact_value_type == "json":
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if fact_value_type == "date":
        if isinstance(value, (date, datetime)):
            return value.isoformat()[:10]
        return str(value)  # 假定已经是字符串
    if fact_value_type in ("number", "bool"):
        return str(value)
    # text / enum
    return str(value)


def deserialize_fact_value(raw: str, fact_value_type: str) -> Any:
    """反序列化（读取时调用）。

    Args:
        raw: 数据库存的字符串
        fact_value_type: 同上

    Returns:
        原始类型的值（json → dict/list，number → float 等）
    """
    if not raw:
        return None
    if fact_value_type == "json":
        return json.loads(raw)
    if fact_value_type == "number":
        return float(raw)
    if fact_value_type == "bool":
        return raw.lower() == "true"
    # text / date / enum 原样返回
    return raw
