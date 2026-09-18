"""项目档案路由（P0-7-A 上传 / P0-7-B 解析 / P0-7-C 下载 + 轻量列表）。

端点：
- POST   /api/v1/projects/{project_id}/documents                上传（自动入队解析）
- GET    /api/v1/projects/{project_id}/documents                列项目档案（轻量，不含 markdown）
- GET    /api/v1/projects/{project_id}/documents/{id}           详情（含 parsed_content.markdown）
- GET    /api/v1/projects/{project_id}/documents/{id}/download  下载源文件
- POST   /api/v1/projects/{project_id}/documents/{id}/reparse   重新解析
- DELETE /api/v1/projects/{project_id}/documents/{id}           删除（含文件 + 解析产物）

解析流水线见 app/worker.py；状态机与 UI 规约见 docs/product/upload-flow.md §五/§七。
"""

import shutil
import tempfile
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.exceptions import DocumentValidationError, PermissionDeniedError
from app.models.base import get_db
from app.models.document import DocumentType, ProjectDocument
from app.models.project import Project
from app.models.user import User
from app.schemas.document import (
    DocumentListItem,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    ParseStatus,
    ReparseResponse,
)
from app.services import ingest, storage, task_queue

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])


async def _get_owned_project(db: AsyncSession, project_id: int, user: User) -> Project:
    """获取项目（要求当前用户是 owner）。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise PermissionDeniedError(f"项目不存在: {project_id}")
    if project.owner_id != user.id:
        raise PermissionDeniedError("无权访问该项目")
    return project


async def _get_owned_document(
    db: AsyncSession, project_id: int, document_id: int, user: User
) -> ProjectDocument:
    """获取项目下的档案（同时校验项目归属）。"""
    await _get_owned_project(db, project_id, user)
    doc = await db.get(ProjectDocument, document_id)
    if doc is None or doc.project_id != project_id:
        raise PermissionDeniedError(f"档案不存在: {document_id}")
    return doc


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    project_id: int,
    file: UploadFile = File(..., description="PDF / 图片文件（≤ 50MB）"),
    document_type: DocumentType = Form(...),
    title: str = Form(..., min_length=1, max_length=300),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentUploadResponse:
    """上传文件到项目档案，并自动入队 MinerU 解析任务。

    返回时 parse_status=pending；解析在 ARQ worker 中异步执行
    （见 app/worker.py）。队列不可用时仍返回 201，用户可稍后点「重新解析」。
    """
    await _get_owned_project(db, project_id, user)

    # 1. 保存到临时文件（UploadFile 一次读完 → tmp）
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "").suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        # 2. 创建 DB 行（拿 id）
        doc = ProjectDocument(
            project_id=project_id,
            uploader_id=user.id,
            document_type=document_type,
            title=title,
            file_name=file.filename or "unnamed",
            file_size=0,  # 稍后更新
            mime_type=file.content_type or "application/octet-stream",
            storage_path="",  # 稍后更新
            storage_provider="local",
            parse_status="pending",
        )
        db.add(doc)
        await db.flush()  # 拿 doc.id

        # 3. 移到正式存储位置（用 doc.id 命名）
        try:
            rel_path, file_size = storage.save_file(
                project_id=project_id,
                document_id=doc.id,
                file_name=doc.file_name,
                source_path=tmp_path,
            )
        except ValueError as e:
            # 文件过大等校验失败：回滚插入，避免残留指向不存在文件的孤儿行
            await db.delete(doc)
            await db.commit()
            raise DocumentValidationError(str(e)) from e

        # 4. 更新存储路径 + 大小
        doc.storage_path = rel_path
        doc.file_size = file_size
        await db.commit()
        await db.refresh(doc)

        # 5. 入队解析（best-effort：失败不影响上传成功）
        await task_queue.enqueue_parse_document(doc.id)

        # ORM 的 str 列 → Pydantic 的 Literal/Enum 字段由 model_validate 做运行时校验
        return DocumentUploadResponse.model_validate(doc)
    finally:
        # 清理临时文件（如果 save_file 失败或没移到正式位置）
        if tmp_path.exists():
            tmp_path.unlink()


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentListResponse:
    """列项目下所有档案（按上传时间倒序）。

    返回**轻量列表项**：不含 parsed_content.markdown（避免列表响应膨胀），
    只给解析结果的标量摘要（页数 / 字数 / 耗时）。
    """
    await _get_owned_project(db, project_id, user)

    result = await db.execute(
        select(ProjectDocument)
        .where(ProjectDocument.project_id == project_id)
        .order_by(ProjectDocument.created_at.desc())
    )
    items = result.scalars().all()
    return DocumentListResponse(
        items=[_to_list_item(d) for d in items],
        total=len(items),
    )


def _to_list_item(doc: ProjectDocument) -> DocumentListItem:
    """ORM -> 轻量列表项（从 parsed_content 提取标量摘要）。"""
    parsed: dict[str, Any] = doc.parsed_content or {}
    return DocumentListItem(
        id=doc.id,
        project_id=doc.project_id,
        uploader_id=doc.uploader_id,
        document_type=cast(DocumentType, doc.document_type),
        title=doc.title,
        file_name=doc.file_name,
        file_size=doc.file_size,
        mime_type=doc.mime_type,
        parse_status=cast(ParseStatus, doc.parse_status),
        parse_error=doc.parse_error,
        page_count=int(parsed.get("page_count") or 0),
        markdown_chars=int(parsed.get("markdown_chars") or 0),
        parse_elapsed_sec=parsed.get("elapsed_sec"),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentResponse:
    """档案详情（含 parsed_content：Markdown 正文 + 解析元信息）。"""
    doc = await _get_owned_document(db, project_id, document_id, user)
    return DocumentResponse.model_validate(doc)


@router.get("/{document_id}/download")
async def download_document(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """下载原始文件（P0-7-C）。

    文件名走 Content-Disposition；用 RFC 5987 的 filename* 编码中文名，
    避免部分浏览器把中文文件名变成乱码。
    """
    doc = await _get_owned_document(db, project_id, document_id, user)

    abs_path = storage.get_storage_root() / doc.storage_path
    if not abs_path.exists():
        raise DocumentValidationError(f"源文件已丢失: {doc.storage_path}")

    from urllib.parse import quote

    quoted = quote(doc.file_name)
    return FileResponse(
        path=abs_path,
        media_type=doc.mime_type or "application/octet-stream",
        headers={
            # filename= 给老浏览器兜底；filename*= 给现代浏览器（支持 UTF-8）
            "Content-Disposition": (
                f"attachment; filename=\"{doc.id}\"; filename*=UTF-8''{quoted}"
            )
        },
    )


@router.post("/{document_id}/reparse", response_model=ReparseResponse)
async def reparse_document(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReparseResponse:
    """重新解析：清空解析结果 → 重置 pending → 重新入队。

    用于：解析失败后重试、换 MinerU 档位后重跑、文件被替换后续解析。
    """
    doc = await _get_owned_document(db, project_id, document_id, user)

    # 源文件必须还在（避免入队后才失败，白跑一趟）
    if not storage.file_exists(doc.storage_path):
        raise DocumentValidationError(f"源文件已丢失，无法重新解析: {doc.storage_path}")

    doc.parse_status = "pending"
    doc.parse_error = None
    doc.parsed_content = None
    await db.commit()

    queued = await task_queue.enqueue_parse_document(doc.id)
    return ReparseResponse(
        document_id=doc.id,
        parse_status=cast(ParseStatus, doc.parse_status),
        queued=queued,
        message=(
            "已重新入队解析"
            if queued
            else "解析任务已在队列中，或任务队列不可用（请检查 Redis 与 worker）"
        ),
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除档案：DB 行 + 源文件 + 解析产物。

    注意：已生成的结论/文书中对该档案的引用不会回滚（MVP 接受）。
    """
    doc = await _get_owned_document(db, project_id, document_id, user)

    # 先删文件，再删 DB 行。文件删失败不阻断（避免残留 DB 行指向已丢失的文件更糟）
    storage.delete_file(doc.storage_path)
    ingest.delete_parsed_output(doc.project_id, doc.id)

    await db.delete(doc)
    await db.commit()
