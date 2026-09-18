"""LLM 路由层。

实现:
- 任务路由（按场景/任务选择模型）
- 降级链（主模型失败自动降级）
- 统一接口抽象（业务代码不直接依赖 SDK）
"""

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.exceptions import LLMAllProvidersFailedError, LLMResponseFormatError

# ===== LLM 输出清洗 =====
#
# 实测（2026-09-19，MiniMax-M3）：
#   chat() + response_format=json_object        → 先吐 <think>…</think>，再吐 JSON（764 字符）
#   chat() + thinking disabled                  → 不吐 <think>，但 JSON 被 ```json 围栏包裹（138 字符）
#   stream_chat(json_mode=True)                 → 已禁用 thinking，行为正确
#
# 两条路径都必须清洗。剥离 <think> 不只是为了解析：它同时省 5.5× 输出 token，
# 且避免思考过程混进流式报告被用户看到。
#
# 注意 <think> 必须在抽 JSON **之前**剥离：贪婪的 \{.*\} 遇到含花括号的思考块会抽错。

_RE_THINK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.DOTALL | re.IGNORECASE)
_RE_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """剥离 <think>…</think> 思考块与 markdown 代码围栏。"""
    if not text:
        return ""
    return _RE_FENCE.sub("", _RE_THINK.sub("", text)).strip()


def extract_json_object(text: str) -> str | None:
    r"""从 LLM 输出中鲁棒提取第一个**完整**的 JSON 对象。

    先剥思考块与代码围栏，再做**括号深度配对**（感知字符串与转义），
    而非贪婪 `\{.*\}`。

    为什么不能用贪婪匹配：输出被 max_tokens 截断、或模型吐了未闭合的
    `<think>` 时，贪婪匹配会从第一个 `{` 一直取到最后一个 `}`，
    跨度里混入非 JSON 内容，解析必失败（实测 E2E 出现过
    `Expecting ',' delimiter: char 257`）。深度配对只认真正闭合的那一段，
    截断时返回 None，由调用方走重试——这比交出一段坏 JSON 更容易诊断。
    """
    cleaned = strip_reasoning(text)
    start = cleaned.find("{")
    if start < 0:
        return None

    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : i + 1]

    # 括号未闭合（多为输出被截断）→ 返回 None，交给重试
    return None


class LLMTaskType(StrEnum):
    """任务类型 - 用于路由。"""

    CONSULTATION_DIALOG = "consultation.dialog"      # 律师问诊对话
    CONSULTATION_REASONING = "consultation.reasoning"  # 推理链生成
    DOCUMENT_PARSING = "document.parsing"            # 文档解析
    CLAUSE_EXTRACTION = "clause.extraction"          # 条款抽取
    DOCUMENT_GENERATION = "document.generation"      # 文书起草
    SUMMARY = "summary"                              # 摘要
    EMBEDDING = "embedding"                          # 语义检索


# 任务类型 -> 模型路由
TASK_MODEL_MAP: dict[LLMTaskType, str] = {
    LLMTaskType.CONSULTATION_DIALOG: "minimax",
    LLMTaskType.CONSULTATION_REASONING: "minimax",
    LLMTaskType.DOCUMENT_PARSING: "deepseek",
    LLMTaskType.CLAUSE_EXTRACTION: "deepseek",
    LLMTaskType.DOCUMENT_GENERATION: "minimax",
    LLMTaskType.SUMMARY: "deepseek",
    LLMTaskType.EMBEDDING: "deepseek",
}

# 降级链
FALLBACK_CHAIN: list[str] = ["minimax", "deepseek", "openai"]


@dataclass
class LLMMessage:
    role: str  # system / user / assistant
    content: str


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] | None = None


class LLMClient:
    """统一 LLM 客户端。

    用法:
        client = LLMClient()
        resp = await client.chat(
            task=LLMTaskType.CONSULTATION_DIALOG,
            messages=[...],
        )
    """

    def __init__(self) -> None:
        self._clients: dict[str, AsyncOpenAI] = {}
        self._model_map: dict[str, str] = {
            "minimax": settings.minimax_model,
            "deepseek": settings.deepseek_model,
            "openai": settings.openai_model,
        }
        self._base_url_map: dict[str, str] = {
            "minimax": settings.minimax_base_url,
            "deepseek": settings.deepseek_base_url,
            "openai": settings.openai_base_url,
        }
        self._api_key_map: dict[str, str] = {
            "minimax": settings.minimax_api_key,
            "deepseek": settings.deepseek_api_key,
            "openai": settings.openai_api_key,
        }

    def _get_client(self, provider: str) -> AsyncOpenAI:
        """懒加载 OpenAI 兼容客户端。"""
        if provider not in self._clients:
            api_key = self._api_key_map[provider]
            if not api_key:
                raise ValueError(f"{provider} API key 未配置")
            self._clients[provider] = AsyncOpenAI(
                api_key=api_key,
                base_url=self._base_url_map[provider],
                timeout=settings.llm_timeout,
            )
        return self._clients[provider]

    def _select_provider(self, task: LLMTaskType) -> str:
        """根据任务选择 provider。"""
        preferred = TASK_MODEL_MAP.get(task, settings.llm_default)
        if preferred in FALLBACK_CHAIN:
            return preferred
        return settings.llm_default

    @retry(
        stop=stop_after_attempt(settings.llm_max_retries + 1),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _call_provider(
        self,
        provider: str,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """实际调用单个 provider。带重试。"""
        client = self._get_client(provider)
        model = self._model_map[provider]

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": cast(
                list[ChatCompletionMessageParam],
                [{"role": m.role, "content": m.content} for m in messages],
            ),
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format
        # M3 thinking 控制：JSON 模式禁用（与 stream_chat 对齐）。
        # 不禁用会多花 5.5× 输出 token，且思考块混进 content 需额外剥离。
        if provider == "minimax" and (json_mode or response_format is not None):
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        completion = await client.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        usage = {}
        if completion.usage:
            usage = {
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens,
            }

        return LLMResponse(
            content=choice.message.content or "",
            provider=provider,
            model=model,
            usage=usage,
        )

    async def chat(
        self,
        task: LLMTaskType,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """调用 LLM，自动按降级链切换。

        任务 -> 首选 provider -> 失败 -> 下一个 provider -> 全部失败 -> 抛异常

        Args:
            json_mode: True 时禁用 provider 的思考模式（M3 需显式关闭），
                仍返回原始 content —— 解析请用 complete_json()。
        """
        preferred = self._select_provider(task)
        chain = [preferred] + [p for p in FALLBACK_CHAIN if p != preferred]

        last_error: Exception | None = None
        for provider in chain:
            try:
                return await self._call_provider(
                    provider,
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    json_mode=json_mode,
                )
            except Exception as e:  # noqa: BLE001
                last_error = e
                continue

        raise LLMAllProvidersFailedError(
            f"所有 LLM provider 调用失败。最后错误: {last_error}"
        ) from last_error

    async def complete_json(
        self,
        task: LLMTaskType,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """调用 LLM 并返回解析后的 JSON 对象。

        自动完成三件事：禁用思考模式、剥离 <think>/代码围栏、解析 JSON。

        Raises:
            LLMAllProvidersFailedError: provider 全失败
            LLMResponseFormatError: 返回内容无法解析为 JSON 对象
        """
        resp = await self.chat(
            task,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            json_mode=True,
        )
        raw = extract_json_object(resp.content)
        if raw is None:
            raise LLMResponseFormatError(
                f"LLM 未返回 JSON 对象。provider={resp.provider} "
                f"content_head={strip_reasoning(resp.content)[:200]!r}"
            )
        try:
            parsed = json.loads(raw)
        except ValueError as e:
            raise LLMResponseFormatError(f"LLM 返回的 JSON 无法解析: {e}") from e
        if not isinstance(parsed, dict):
            raise LLMResponseFormatError(f"LLM 返回的不是 JSON 对象: {type(parsed).__name__}")
        return parsed

    async def stream_chat(
        self,
        task: LLMTaskType,
        messages: list[LLMMessage],
        *,
        temperature: float = 1.0,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        """流式调用 LLM（用于长文本生成/对话实时输出）。

        参数:
        - json_mode: True 时启用 JSON Schema + 禁用 thinking（M3 推荐）

        降级策略（与 chat() 对齐）：
        - 仅在**尚未产出任何 chunk** 时才允许切到下一个 provider
        - 一旦开始输出，中途失败无法回退（用户已看到部分内容），
          此时直接抛错，由调用方决定是否重试整轮
        """
        preferred = self._select_provider(task)
        chain = [preferred] + [p for p in FALLBACK_CHAIN if p != preferred]

        last_error: Exception | None = None
        for provider in chain:
            if not self._api_key_map.get(provider):
                continue  # 未配置 key，跳过

            emitted = False
            try:
                client = self._get_client(provider)
                model = self._model_map[provider]

                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": cast(
                        list[ChatCompletionMessageParam],
                        [{"role": m.role, "content": m.content} for m in messages],
                    ),
                    "temperature": temperature,
                    "stream": True,
                }
                if max_tokens is not None:
                    kwargs["max_tokens"] = max_tokens
                if response_format:
                    kwargs["response_format"] = response_format
                # M3 thinking 控制：JSON 模式禁用，普通模式分离
                if provider == "minimax":
                    if json_mode:
                        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
                    else:
                        kwargs["extra_body"] = {"reasoning_split": True}

                raw_stream = await client.chat.completions.create(**kwargs)

                async for chunk in raw_stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        emitted = True
                        yield chunk.choices[0].delta.content
                return  # 正常结束
            except Exception as e:  # noqa: BLE001
                last_error = e
                if emitted:
                    # 已输出部分内容 → 不能回退，直接抛出
                    raise
                continue  # 未输出任何内容 → 尝试下一个 provider

        raise LLMAllProvidersFailedError(
            f"所有 LLM provider 流式调用失败。最后错误: {last_error}"
        ) from last_error


# 单例
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例。"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
