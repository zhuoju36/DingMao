"""流式 LLM 调用测试 - 不依赖 DB。

直接调 LLMClient.stream_chat()，验证：
1. 流式 chunk 增量到达
2. JSON 鲁棒提取（处理 <think> 标签）
3. 完整响应结构

用法:
    uv run python -m scripts.test_stream_llm
"""

import asyncio
import json
import re
import time

from app.core.config import settings  # noqa: F401  触发 .env
from app.services.llm import LLMMessage, LLMTaskType, get_llm_client

CONTRACT_TEXT = """本合同付款采用背靠背方式，业主付款后再支付施工方。
暂定价以审计机关审计结果为准。逾期违约金按日万分之五计算。"""

SYSTEM = (
    "你是钉铆争议顾问。分析合同文本，输出 JSON："
    '{"risks": [{"clause": "条款摘要", "level": "red|yellow|green", "reason": "..."}], '
    '"summary": "一句话总结"}'
)


def extract_json(text: str) -> str | None:
    """鲁棒提取首个完整 JSON 对象。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0).strip() if match else None


async def main() -> None:
    if not settings.minimax_api_key:
        print("⚠️  MINIMAX_API_KEY 未配置（检查 .env）")
        return

    client = get_llm_client()
    messages = [
        LLMMessage(role="system", content=SYSTEM),
        LLMMessage(role="user", content=f"分析以下合同条款：\n\n{CONTRACT_TEXT}"),
    ]

    print("=" * 70)
    print("流式输出测试 - MiniMax-M3")
    print("=" * 70)

    chunks: list[str] = []
    chunk_count = 0
    first_chunk_at: float | None = None
    t0 = time.time()

    print("\n--- 流式 chunk 实时输出 ---")
    try:
        async for piece in client.stream_chat(
            task=LLMTaskType.CONSULTATION_REASONING,
            messages=messages,
            temperature=1.0,
            max_tokens=8000,
            json_mode=True,  # JSON Schema + 禁用 thinking
        ):
            now = time.time() - t0
            if first_chunk_at is None:
                first_chunk_at = now
            chunks.append(piece)
            chunk_count += 1
            if chunk_count <= 20:
                print(f"  [{now:5.2f}s] chunk#{chunk_count:3d} | {piece!r}")
            elif chunk_count == 21:
                print("  ... (后续 chunk 不再展示)")
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ LLM 调用失败: {e}")
        return

    total_time = time.time() - t0
    full_content = "".join(chunks)

    print("\n--- 统计 ---")
    print(f"  总 chunk 数:  {chunk_count}")
    print(f"  首 chunk 延迟: {first_chunk_at:.2f}s")
    print(f"  总耗时:     {total_time:.2f}s")
    print(f"  内容总长度: {len(full_content)} 字符")

    print("\n--- JSON 提取 ---")
    json_text = extract_json(full_content)
    if json_text:
        print(f"  ✓ 找到 JSON (长度 {len(json_text)})")
        try:
            report = json.loads(json_text)
            print("  ✓ 解析成功")
            print(f"    - summary: {report.get('summary', '')[:80]}")
            print(f"    - risks 数量: {len(report.get('risks', []))}")
            for i, risk in enumerate(report.get("risks", []), 1):
                print(f"    - risk {i}: [{risk.get('level', '?')}] {risk.get('clause', '')[:50]}")
        except json.JSONDecodeError as e:
            print(f"  ✗ JSON 解析失败: {e}")
    else:
        print("  ✗ 未找到 JSON")

    print("\n--- 完整内容预览 ---")
    print(f"  head: {full_content[:150]}")
    print(f"  tail: {full_content[-150:]}")


if __name__ == "__main__":
    asyncio.run(main())
