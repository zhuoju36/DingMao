"""ARQ worker（P0-7-B）：MinerU 文档解析任务。

启动：
    cd backend && .venv/bin/arq app.worker.WorkerSettings

状态机（与 docs/product/upload-flow.md §五 对齐）：
    pending ──enqueue──▶ parsing ──success──▶ parsed
                            └────failure────▶ failed_parse

设计要点：
- 任务内自己开 DB 会话（ARQ 不共享 FastAPI 的 Depends）
- 解析失败不抛异常：写 failed_parse + parse_error，任务算「完成」
  （抛异常会让 ARQ 重试；解析失败重试无意义，且会白烧 CPU）
- 文档在排队期间被删除 → 静默跳过
"""

from __future__ import annotations

import logging
from typing import Any

from arq.connections import RedisSettings
from sqlalchemy import select

from app.core.config import settings
from app.models.base import AsyncSessionLocal
from app.models.document import ProjectDocument
from app.services import ingest
from app.services.storage import get_storage_root

# ARQ 默认只放行 WARNING 以上，本模块的 logger.info（解析开始/成功）会被丢弃。
# 排查解析问题时看不到「开始/成功」很难判断卡在哪一步，故显式配置。
# basicConfig 对已配置过的 root logger 是 no-op，不会覆盖 uvicorn 的日志设置。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


async def parse_document_task(ctx: dict[str, Any], document_id: int) -> dict[str, Any]:
    """解析单个项目档案（MinerU Flash 档）。"""
    async with AsyncSessionLocal() as db:
        doc = (
            await db.execute(select(ProjectDocument).where(ProjectDocument.id == document_id))
        ).scalar_one_or_none()

        if doc is None:
            logger.info("文档已删除，跳过解析 doc=%s", document_id)
            return {"document_id": document_id, "status": "skipped"}

        # 1. 置 parsing
        doc.parse_status = "parsing"
        doc.parse_error = None
        await db.commit()

        project_id = doc.project_id
        storage_path = doc.storage_path

    # 2. 解析（subprocess，不持有 DB 会话 —— 可达数分钟）
    file_path = get_storage_root() / storage_path
    result = await ingest.parse_document(
        project_id=project_id,
        document_id=document_id,
        file_path=file_path,
    )

    # 3. 回写结果
    async with AsyncSessionLocal() as db:
        doc = (
            await db.execute(select(ProjectDocument).where(ProjectDocument.id == document_id))
        ).scalar_one_or_none()
        if doc is None:
            logger.info("文档在解析期间被删除 doc=%s", document_id)
            return {"document_id": document_id, "status": "deleted"}

        if result.status == "success":
            doc.parse_status = "parsed"
            doc.parse_error = None
            # parsed_content 只内联 markdown（供 LLM / 检索），middle_json 等留盘
            # 原因：middle.json 单文件可达数百 KB，内联进 JSONB 会明显膨胀 DB
            doc.parsed_content = {
                "markdown": result.markdown,
                "page_count": result.page_count,
                "markdown_chars": result.markdown_chars,
                "middle_json_bytes": result.middle_json_bytes,
                "images": result.images,
                "elapsed_sec": result.elapsed_sec,
                "tier": settings.mineru_tier,
                # 完整产物（middle.json / images/）的落盘目录，相对 storage_root
                "parsed_dir": str(result.output_dir.relative_to(get_storage_root())),
            }
        else:
            doc.parse_status = "failed_parse"
            doc.parse_error = (result.error or "解析失败")[:1000]
            logger.warning(
                "解析失败 doc=%s kind=%s: %s",
                document_id,
                result.error_kind,
                result.error,
            )

        await db.commit()

    return {
        "document_id": document_id,
        "status": "parsed" if result.status == "success" else "failed_parse",
        "pages": result.page_count,
        "elapsed_sec": result.elapsed_sec,
        "error_kind": result.error_kind,
    }


async def _on_startup(ctx: dict[str, Any]) -> None:  # noqa: ARG001
    logger.info(
        "ARQ worker 启动 | mineru_tier=%s | mineru_python=%s",
        settings.mineru_tier,
        settings.mineru_python or "(未配置)",
    )


async def _on_shutdown(ctx: dict[str, Any]) -> None:  # noqa: ARG001
    logger.info("ARQ worker 关闭")


class WorkerSettings:
    """arq app.worker.WorkerSettings"""

    functions = [parse_document_task]
    on_startup = _on_startup
    on_shutdown = _on_shutdown

    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.worker_job_timeout
    # keep_result=0：解析结果不回写 Redis（我们不查任务结果，只查 DB 状态）
    # 副作用（正是所需）：_job_id 去重窗口 = 排队中+执行中，不会因结果缓存吞掉后续重解析
    keep_result = 0
