"""文档解析服务（P0-7-B）：MinerU subprocess 薄封装。

【架构约束】
MinerU 依赖 7.3 GB，不装进 backend venv（737 MB）。因此本模块通过 subprocess
调用「装了 MinerU 的解释器」（settings.mineru_python）执行仓库内的
scripts/mineru_parse.py，再读它产出的 manifest.json。

【产物落盘布局】
    storage/parsed/{project_id}/{document_id}/
        document.md       Markdown 正文
        middle.json       MiddleJson（bbox 定位）
        images/           图片（如有）
        manifest.json     解析元信息

【为什么用 asyncio subprocess 而非 subprocess.run】
解析单文件可达数分钟。ARQ worker 是 async 的，同步 subprocess 会阻塞事件循环，
导致同一 worker 进程内其他任务无法推进。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.core.config import settings
from app.services.storage import get_storage_root

logger = logging.getLogger(__name__)

IngestStatus = Literal["success", "failed"]


@dataclass
class IngestResult:
    """解析结果（成功或失败统一返回，不抛异常给调用方）。"""

    status: IngestStatus
    output_dir: Path
    markdown: str | None = None
    page_count: int = 0
    markdown_chars: int = 0
    middle_json_bytes: int = 0
    images: int = 0
    elapsed_sec: float = 0.0
    error: str | None = None
    # 失败时用于日志排查（如 "timeout" / "not_configured"）
    error_kind: str | None = None


def parsed_dir_for(project_id: int, document_id: int) -> Path:
    """解析产物目录：storage/parsed/{project_id}/{document_id}/"""
    return get_storage_root() / "parsed" / str(project_id) / str(document_id)


def _resolve_mineru_python() -> Path | None:
    """解析 MinerU 解释器路径。未配置或不存在时返回 None。"""
    raw = (settings.mineru_python or "").strip()
    if not raw:
        return None
    p = settings.resolve_path(raw)
    return p if p.exists() else None


async def parse_document(
    *,
    project_id: int,
    document_id: int,
    file_path: Path,
) -> IngestResult:
    """调用 MinerU 解析单个文件。

    永不抛异常：所有失败都收敛成 IngestResult(status="failed", error=...)。
    调用方（ARQ task）据此更新 project_documents.parse_status / parse_error。
    """
    out_dir = parsed_dir_for(project_id, document_id)

    # 每次重解析前清空旧产物，避免残留导致误判（如上次成功、这次失败但文件还在）
    if out_dir.exists():
        for child in out_dir.iterdir():
            if child.is_file():
                child.unlink()
            else:
                import shutil

                shutil.rmtree(child)
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- 前置校验：MinerU 是否可用 ---
    mineru_python = _resolve_mineru_python()
    if mineru_python is None:
        return IngestResult(
            status="failed",
            output_dir=out_dir,
            error_kind="not_configured",
            error=(
                "MinerU 未配置或解释器不存在。请设置环境变量 MINERU_PYTHON "
                "指向装了 mineru 的 Python 解释器（本地开发示例："
                "../experiments/mineru-test/.venv/bin/python）"
            ),
        )

    script = settings.resolve_path(settings.mineru_parse_script)
    if not script.exists():
        return IngestResult(
            status="failed",
            output_dir=out_dir,
            error_kind="script_missing",
            error=f"解析脚本不存在: {script}",
        )

    if not file_path.exists():
        return IngestResult(
            status="failed",
            output_dir=out_dir,
            error_kind="file_missing",
            error=f"源文件不存在: {file_path}",
        )

    # --- 调用 MinerU ---
    cmd = [
        str(mineru_python),
        str(script),
        "--input",
        str(file_path),
        "--output",
        str(out_dir),
        "--tier",
        settings.mineru_tier,
    ]
    logger.info("MinerU 解析开始: doc=%s file=%s", document_id, file_path.name)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return IngestResult(
            status="failed",
            output_dir=out_dir,
            error_kind="spawn_failed",
            error=f"无法启动 MinerU 进程: {exc}",
        )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=settings.mineru_timeout
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return IngestResult(
            status="failed",
            output_dir=out_dir,
            error_kind="timeout",
            error=(
                f"MinerU 解析超时（>{settings.mineru_timeout}s）。大文件可调大 MINERU_TIMEOUT。"
            ),
        )

    stdout = stdout_b.decode("utf-8", errors="replace").strip()
    stderr = stderr_b.decode("utf-8", errors="replace").strip()

    # --- 读 manifest（脚本的唯一可信输出）---
    manifest_path = out_dir / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("manifest.json 解析失败: %s", exc)

    if proc.returncode != 0 or manifest.get("status") != "success":
        err = manifest.get("error") or stderr or stdout or "MinerU 解析失败（无输出）"
        logger.warning("MinerU 解析失败 doc=%s: %s", document_id, err)
        return IngestResult(
            status="failed",
            output_dir=out_dir,
            error_kind="parse_failed",
            error=str(err)[:1000],
            elapsed_sec=float(manifest.get("elapsed_sec") or 0.0),
        )

    # --- 读正文 ---
    md_path = out_dir / "document.md"
    if not md_path.exists():
        return IngestResult(
            status="failed",
            output_dir=out_dir,
            error_kind="output_missing",
            error="MinerU 报告成功但未找到 document.md",
        )
    markdown = md_path.read_text(encoding="utf-8")

    result = IngestResult(
        status="success",
        output_dir=out_dir,
        markdown=markdown,
        page_count=int(manifest.get("page_count") or 0),
        markdown_chars=int(manifest.get("markdown_chars") or len(markdown)),
        middle_json_bytes=int(manifest.get("middle_json_bytes") or 0),
        images=int(manifest.get("images") or 0),
        elapsed_sec=float(manifest.get("elapsed_sec") or 0.0),
    )
    logger.info(
        "MinerU 解析成功 doc=%s pages=%s chars=%s elapsed=%.1fs",
        document_id,
        result.page_count,
        result.markdown_chars,
        result.elapsed_sec,
    )
    return result


def delete_parsed_output(project_id: int, document_id: int) -> bool:
    """删除某文档的解析产物目录。返回是否真的删了。"""
    out_dir = parsed_dir_for(project_id, document_id)
    if not out_dir.exists():
        return False
    import shutil

    shutil.rmtree(out_dir)
    return True
