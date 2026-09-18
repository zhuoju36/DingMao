"""ARQ 任务队列客户端（P0-7-B）。

上传/重解析时把 MinerU 解析任务丢进队列，HTTP 请求立即返回。
队列不可用时**不阻断上传**：返回 False，文档保持 pending，用户可稍后点「重新解析」。
"""

from __future__ import annotations

import logging

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings

logger = logging.getLogger(__name__)

# 惰性单例：首次入队时建连接池
_pool: ArqRedis | None = None


async def get_pool() -> ArqRedis:
    """获取（或创建）ARQ Redis 连接池。"""
    global _pool  # noqa: PLW0603
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _pool


async def close_pool() -> None:
    """关闭连接池（应用 shutdown 时调用）。"""
    global _pool  # noqa: PLW0603
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def enqueue_parse_document(document_id: int) -> bool:
    """入队一个解析任务。

    Returns:
        True = 已入队；False = 队列不可用或任务已存在（重复入队被去重）

    设计说明（去重）：
        用 _job_id=f"parse:{document_id}" 做去重，配合 WorkerSettings.keep_result=0，
        去重窗口 = 「排队中 + 执行中」。因此：
        - 上传后立刻连点两次「重新解析」不会跑两遍
        - 任务结束后再次重解析不会被静默吞掉
    """
    try:
        pool = await get_pool()
        job = await pool.enqueue_job(
            "parse_document_task", document_id, _job_id=f"parse:{document_id}"
        )
    except Exception as exc:  # noqa: BLE001
        # Redis 挂了不应阻断上传：记录并让调用方决定（文档保持 pending）
        logger.warning("入队解析任务失败 doc=%s: %s", document_id, exc)
        return False

    if job is None:
        logger.info("解析任务已存在，跳过重复入队 doc=%s", document_id)
        return False
    return True
