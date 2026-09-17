"""真实 LLM 集成测试。

不依赖 DB。验证 MiniMax-M3 + DeepSeek-V4-Flash 在本场景的能力。

测试维度：
1. 连通性 - 三个 provider 都能调用
2. 中文法律场景 - 法条引用准确性
3. JSON Schema 输出 - 能否稳定输出结构化结论
4. 长上下文 - 能否处理 1000+ 字合同
5. 推理链质量 - reasoning_split 分离的思维链是否可用
6. 延迟 - P50/P95

需要 API Key（在环境变量中，不要硬编码、不要 print）：
- MINIMAX_API_KEY (Token Plan Key)
- DEEPSEEK_API_KEY
- OPENAI_API_KEY (可选)

用法:
    export MINIMAX_API_KEY=...
    uv run python -m scripts.test_real_llm
"""

import asyncio
import json
import os
import re
import time
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings

# 显式从 os.environ 读取（settings 也读，但不暴露值）
MINIMAX_KEY = os.environ.get("MINIMAX_API_KEY", "") or settings.minimax_api_key
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "") or settings.deepseek_api_key
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "") or settings.openai_api_key


# FIX#8: 干净的 re 导入，不再用 __import__("re")
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
# FIX#7: 通用脱敏模式，兜底替换疑似 key / bearer token
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{6,}|Bearer\s+[A-Za-z0-9._\-]+)", re.IGNORECASE)


def _key_status(key: str) -> str:
    """返回 Key 的安全状态摘要（不打印 Key 本身）。"""
    if not key:
        return "✗ 未配置"
    if len(key) < 8:
        return "⚠ 异常短"
    return f"✓ 已配置 (长度 {len(key)}, 前缀 {key[:4]}****)"


def _redact(text: str, *extra_secrets: str) -> str:
    """把异常文本中可能的密钥脱敏。

    FIX#7: 先按已知 key 精确替换，再用正则兜底替换疑似密钥片段。
    """
    out = text
    for s in extra_secrets:
        if s:
            out = out.replace(s, "***KEY***")
    out = _SECRET_RE.sub("***REDACTED***", out)
    return out


def _strip_think_tags(content: str) -> str:
    """剥离 MiniMax-M3 在 content 里嵌入的 <think>...</think> 块。

    注意（对应文档）：
    - reasoning_split=False 时，thinking 会保留在 content 的 <think> 标签内；
    - reasoning_split=True 时，thinking 拆到 reasoning_content/reasoning_details，
      content 理论上不应再出现 <think>。
    这里仅作为防御性清洗保留，主要服务于关闭 thinking 失败或上游拼接异常的场景。
    """
    return _THINK_RE.sub("", content).strip()


# ===== 测试用例 =====

TEST_CASES: list[dict[str, Any]] = [
    {
        "name": "Q1-基础法律问答",
        "system": "你是钉铆法律助手。请用中文回答。",
        "user": "建设工程合同纠纷中，'背靠背付款'条款的效力如何？",
        "expect_keys": ["背靠背", "效力", "风险", "条件"],
    },
    {
        "name": "Q2-法条引用",
        "system": (
            "你是钉铆法律助手。请引用民法典具体条文回答。"
            "输出 JSON 格式：{\"article_no\": \"第XXX条\", \"summary\": \"...\"}"
        ),
        "user": "违约金约定过高时可以怎么处理？请引用民法典具体条文。",
        "expect_json_keys": ["article_no", "summary"],
        # 允许格式：
        #   "第X条" / "第X条第Y款" / "第X条（修订）"
        #   "《法名》第X条" / "《法名》第X条第Y款"
        #   "第五百八十五条" / "《法名》第五百八十五条第二款"（中国法律标准格式）
        # 关键：必须包含"第N条"或"第N百M条"，可带"《法名》"前缀和"第Y款/项/（备注）"后缀
        "expect_article_pattern": (
            r"^(《.+?》)?"
            r"(第[一二三四五六七八九十百零〇\d]+条"
            r"|[一二三四五六七八九十百]+条)"
            r"(第[一二三四五六七八九十百零〇\d]+款)?"
            r"(第[一二三四五六七八九十百零〇\d]+项)?"
            r"(（[^）]+）)?$"
        ),
    },
    {
        "name": "Q3-长合同分析（JSON Schema）",
        "system": (
            "你是钉铆法律助手。分析合同条款，输出 JSON："
            '{"risks": [{"clause": "条款摘要", "level": "red|yellow|green", "reason": "..."}], '
            '"summary": "一句话总结"}'
        ),
        "user": (
            "分析以下合同条款：\n\n"
            "1. 付款采用背靠背方式，业主付款后再支付施工方。\n"
            "2. 暂定价以审计机关审计结果为准。\n"
            "3. 逾期违约金按日万分之五计算（年化 18.25%）。\n"
            "4. 保修期 2 年。"
        ),
        "expect_json_keys": ["risks", "summary"],
        "expect_min_risks": 2,
    },
    {
        "name": "Q4-长合同全文（~1500 字）",
        "system": (
            "你是钉铆法律助手。阅读合同正文，列出 3 条最重要的风险，"
            "输出 JSON：{\"top_risks\": [{\"title\": \"...\", \"reason\": \"...\", \"level\": \"...\"}], \"overall\": \"...\"}"
        ),
        "user": """本合同为建设工程施工合同，主要条款如下：

第一条 工程概况。本工程为 XX 综合楼工程，地上 18 层，地下 2 层，建筑面积约 45,000 平方米。
工程地点位于广州市天河区，计划开工日期 2026 年 3 月 1 日，计划竣工日期 2027 年 8 月 30 日，
合同工期总日历天数 550 天。

第二条 合同价款。本合同采用固定总价方式，合同总价为人民币壹亿贰仟捌佰万元整（¥128,000,000.00），
其中安全文明施工费为人民币 256 万元，不得作为竞争性费用。

第三条 付款方式。本工程无预付款。进度款按月支付，每月按当月完成合格工程量的 70% 支付。
工程款支付以建设单位收到业主方付款为前提条件，即施工方同意背靠背付款。
变更签证款在审计完成后支付，审计周期不超过 24 个月。

第四条 工期顺延。因非施工方原因造成的工期延误，经监理确认后可顺延工期。
连续 7 天以上停工补偿按 1,500 元/天计算，但需提供监理签证。

第五条 工程质量。本工程质量标准为合格，一次性验收合格率不低于 95%。
返工导致的费用由责任方承担，但监理认定的隐蔽工程验收必须在下一道工序开始前完成。

第六条 安全生产。施工方承担施工现场的安全管理责任，
发生安全事故的，事故责任与费用由责任方承担。

第七条 违约责任。施工方逾期竣工的，按合同总价日万分之五支付违约金，
最高不超过合同总价的 10%。建设单位逾期付款的，
按全国银行间同业拆借中心公布的同期 LPR 利率支付利息。

第八条 争议解决。因本合同引起的争议，双方协商解决；
协商不成的，提交广州仲裁委员会按其现行仲裁规则进行仲裁。

第九条 合同生效。本合同自双方签字盖章之日起生效。
""",
        "expect_json_keys": ["top_risks", "overall"],
        "expect_min_risks": 3,
    },
]


# ===== 客户端缓存 =====
# FIX#9: 按 provider 复用 AsyncOpenAI 客户端，避免每个用例重新建连接池/TLS。
_CLIENTS: dict[str, AsyncOpenAI] = {}


def _get_client(provider: str, api_key: str, base_url: str) -> AsyncOpenAI:
    if provider not in _CLIENTS:
        _CLIENTS[provider] = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=60)
    return _CLIENTS[provider]


# ===== LLM 调用封装 =====

async def call_llm(
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    system: str,
    user: str,
    *,
    response_format: dict[str, str] | None = None,
    max_tokens: int = 2000,
    use_reasoning_split: bool = False,
) -> tuple[str, str, float]:
    """调用 LLM，返回 (content, reasoning_content, latency_seconds)。

    reasoning_content 仅在 provider=MiniMax + use_reasoning_split=True 时填充。
    其他 provider / 不启用时返回 ""。
    """
    if not api_key:
        return ("[SKIP: no API key]", "", 0.0)

    client = _get_client(provider, api_key, base_url)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 1.0,  # MiniMax 推荐值，DeepSeek 也支持
        # FIX#1: 使用新字段 max_completion_tokens（文档：新接入建议使用此字段）
        "max_completion_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format
    if provider == "minimax":
        # MiniMax 特有：thinking + reasoning_split 控制
        # 参考 hermes-agent 的 MiniMax profile 实现
        #
        # 注意：该分支仅适用于 MiniMax-M3。
        # M2.x 系列（M2 / M2.1 / M2.5 / M2.7）thinking 无法关闭，
        # 即使传 disabled 仍会保持开启，此处传入不会报错但也无效。
        if response_format:
            # JSON 任务：关闭 thinking，避免 thinking 消耗 max_tokens 并污染 JSON 输出
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        elif use_reasoning_split:
            # 开放问答：分离思考内容到 reasoning_content / reasoning_details 字段
            kwargs["extra_body"] = {"reasoning_split": True}

    # FIX#10: 用 perf_counter 避免系统时钟跳变影响延迟测量
    t = time.perf_counter()
    completion = await client.chat.completions.create(**kwargs)
    latency = time.perf_counter() - t

    msg = completion.choices[0].message
    content = msg.content or ""

    # FIX#2: reasoning_split=true 时，thinking 可能出现在 reasoning_content
    # 或 reasoning_details 两个字段中，优先取 reasoning_content，再回落到 details。
    reasoning = getattr(msg, "reasoning_content", "") or ""
    if not reasoning:
        details = getattr(msg, "reasoning_details", None)
        if details and isinstance(details, list):
            texts = [
                d.get("text", "")
                for d in details
                if isinstance(d, dict) and d.get("text")
            ]
            reasoning = "\n".join(texts)

    return content, reasoning, latency


# ===== 测试驱动 =====

def _extract_risks_count(parsed: dict[str, Any]) -> int:
    for key in ("risks", "top_risks"):
        v = parsed.get(key)
        if isinstance(v, list):
            return len(v)
    return 0


_JSON_OBJECT_RE = __import__("re").compile(r"\{.*\}", __import__("re").DOTALL)


def _extract_json(content: str) -> str | None:
    """从 content 里鲁棒提取第一个完整 JSON 对象。

    M3 thinking 模式经常不闭合 <think> 标签，所以不能只依赖 strip。
    用正则找第一个 { 到最后一个 } 之间的内容。
    """
    cleaned = _strip_think_tags(content)
    match = _JSON_OBJECT_RE.search(cleaned)
    return match.group(0).strip() if match else None


async def run_case(
    provider: str, api_key: str, base_url: str, model: str, case: dict[str, Any]
) -> dict[str, Any]:
    """跑一个测试用例。"""
    # FIX#6: 只要用例声明了 expect_json_keys，就走 JSON 模式；
    # 不再依赖对具体 key 名的硬编码判断。
    response_format = None
    if case.get("expect_json_keys"):
        response_format = {"type": "json_object"}

    content, reasoning, latency = await call_llm(
        provider, api_key, base_url, model,
        case["system"], case["user"],
        response_format=response_format,
        max_tokens=6000 if "Q4" in case["name"] else 4000,
        use_reasoning_split=True,
    )

    result: dict[str, Any] = {
        "case": case["name"],
        "latency_s": round(latency, 2),
        "content_len": len(content),
        "content_preview": content[:200].replace("\n", " "),
        "reasoning_len": len(reasoning),
        "reasoning_preview": reasoning[:200].replace("\n", " "),
        "json_valid": None,
        "json_keys": [],
        "json_missing_keys": [],
        "risks_count": 0,
        "keyword_hits": [],
        "keyword_miss": [],
        "assertions_failed": [],
    }

    # FIX#3: Q1 的 expect_keys 现在真的会被校验
    expected_keys: list[str] = case.get("expect_keys", []) or []
    if expected_keys:
        hits = [k for k in expected_keys if k in content]
        miss = [k for k in expected_keys if k not in content]
        result["keyword_hits"] = hits
        result["keyword_miss"] = miss
        if miss:
            result["assertions_failed"].append(f"keyword_miss={miss}")

    # 校验 JSON Schema
    if response_format:
        # M3 thinking 标签经常不闭合 → 用正则提取首个 JSON 对象
        json_text = _extract_json(content)
        if not json_text:
            result["json_valid"] = False
            result["assertions_failed"].append("no_json_found")
        else:
            try:
                parsed = json.loads(json_text)
            except (json.JSONDecodeError, TypeError):
                result["json_valid"] = False
                result["assertions_failed"].append("json_parse_error")
            else:
                if not isinstance(parsed, dict):
                    result["json_valid"] = False
                    result["assertions_failed"].append("json_not_object")
                else:
                    # FIX#4: 校验结构完整性，而不仅仅是"能解析"
                    expected_json_keys: list[str] = case.get("expect_json_keys", []) or []
                    missing = [k for k in expected_json_keys if k not in parsed]
                    result["json_keys"] = list(parsed.keys())
                    result["json_missing_keys"] = missing
                    if missing:
                        result["json_valid"] = False
                        result["assertions_failed"].append(f"missing_keys={missing}")
                    else:
                        result["json_valid"] = True

                result["risks_count"] = _extract_risks_count(parsed)

                min_risks = case.get("expect_min_risks")
                if isinstance(min_risks, int) and result["risks_count"] < min_risks:
                    result["assertions_failed"].append(
                        f"risks_count={result['risks_count']}<{min_risks}"
                    )

                # 额外：法条编号格式校验
                pat = case.get("expect_article_pattern")
                if pat and isinstance(parsed.get("article_no"), str) and not re.match(
                    pat, parsed["article_no"].strip()
                ):
                    result["assertions_failed"].append(
                        f"article_no_format={parsed['article_no']!r}"
                    )

    return result


async def main() -> None:
    print("=" * 70)
    print("真实 LLM 集成测试")
    print("=" * 70)

    providers = [
        ("MiniMax-M3", "minimax", MINIMAX_KEY, settings.minimax_base_url, settings.minimax_model),
        ("DeepSeek-V4-Flash", "deepseek", DEEPSEEK_KEY, settings.deepseek_base_url, settings.deepseek_model),
        ("GPT-4o (兜底)", "openai", OPENAI_KEY, settings.openai_base_url, settings.openai_model),
    ]

    print("\nProvider 状态（不打印 Key 本身）：")
    for name, _, key, _, _ in providers:
        print(f"  {name:25s} {_key_status(key)}")
    if not any(p[2] for p in providers):
        print("\n⚠️  所有 provider 都未配置。请通过环境变量或 .env 提供 API Key。")
        return

    # 汇总统计：P50 / P95 / 断言通过率
    all_latencies: list[float] = []
    all_assertions_total = 0
    all_assertions_failed = 0

    # 对每个 provider 跑全部测试用例
    for prov_name, prov_id, key, base_url, model in providers:
        if not key:
            continue
        print(f"\n{'─' * 70}")
        print(f"📡 Provider: {prov_name} ({model})")
        print(f"   base_url: {base_url}")
        print(f"   reasoning_split: {'on' if prov_id == 'minimax' else 'off (only MiniMax)'}")
        print("─" * 70)

        for case in TEST_CASES:
            try:
                result = await run_case(prov_name, key, base_url, model, case)
                all_latencies.append(result["latency_s"])

                status_parts = [f"{result['latency_s']}s"]
                if result["json_valid"] is True:
                    status_parts.append(f"JSON✓({len(result['json_keys'])} keys)")
                    if result["risks_count"] > 0:
                        status_parts.append(f"{result['risks_count']} risks")
                elif result["json_valid"] is False:
                    status_parts.append("JSON✗")
                if result["keyword_hits"]:
                    status_parts.append(f"kw={len(result['keyword_hits'])}")
                if result["reasoning_len"] > 0:
                    status_parts.append(f"thinking={result['reasoning_len']}字")

                # 每个用例的断言数量 = 关键词期望 + JSON 结构期望
                n_assert = len(case.get("expect_keys", []) or []) + len(
                    case.get("expect_json_keys", []) or []
                ) + (1 if case.get("expect_min_risks") else 0)
                all_assertions_total += n_assert
                all_assertions_failed += len(result["assertions_failed"])

                marker = "✅" if not result["assertions_failed"] else "❌"
                print(
                    f"  {marker} {result['case']:28s} {' '.join(status_parts):40s}"
                )
                if result["assertions_failed"]:
                    print(f"      failed: {result['assertions_failed']}")
                if result["json_valid"] is False:
                    cleaned = _strip_think_tags(result["content_preview"])
                    print(f"      raw_head:  {result['content_preview'][:80]}")
                    print(f"      raw_tail:  {result['content_preview'][-80:]}")
                    print(f"      cleaned:   {cleaned[:200]}")
                elif result["reasoning_len"] > 100:
                    print(f"      thinking(预览): {result['reasoning_preview'][:120]}...")
            except Exception as e:  # noqa: BLE001
                # FIX#7: 统一走 _redact，同时对 type(e).__name__ 与 message 脱敏
                safe_msg = _redact(str(e), key)
                safe_type = _redact(type(e).__name__, key)
                print(f"  ❌ {case['name']:28s} {safe_type}: {safe_msg[:200]}")
                all_assertions_total += 1
                all_assertions_failed += 1

    # 汇总统计
    if all_latencies:
        s = sorted(all_latencies)
        p50 = s[len(s) // 2]
        p95 = s[min(len(s) - 1, int(len(s) * 0.95))]
        pass_rate = (
            (all_assertions_total - all_assertions_failed) / all_assertions_total * 100
            if all_assertions_total
            else 0.0
        )
        print(f"\n{'═' * 70}")
        print(f"延迟  P50={p50:.2f}s  P95={p95:.2f}s  N={len(s)}")
        print(
            f"断言  {all_assertions_total - all_assertions_failed}/"
            f"{all_assertions_total} 通过 ({pass_rate:.1f}%)"
        )
        print("═" * 70)


if __name__ == "__main__":
    asyncio.run(main())
