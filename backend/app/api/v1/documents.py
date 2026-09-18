"""项目档案路由（P0-7-A 最小切片）。

P0-7-A 包含：
- POST   /api/v1/projects/{project_id}/documents        上传文件（不解析，状态=pending）
- GET    /api/v1/projects/{project_id}/documents        列项目档案
- GET    /api/v1/projects/{project_id}/documents/{id}   详情

P0-7-B 后续：
- POST /reparse（MinerU 异步任务）
- DELETE /{id}（v2）
"""
import shutil
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.exceptions import PermissionDeniedError
from app.models.base import get_db
from app.models.document import DocumentType, ProjectDocument
from app.models.project import Project
from app.models.user import User
from app.schemas.document import (
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
)
from app.services import storage

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])


async def _get_owned_project(
    db: AsyncSession, project_id: int, user: User
) -> Project:
    """获取项目（要求当前用户是 owner）。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise PermissionDeniedError(f"项目不存在: {project_id}")
    if project.owner_id != user.id:
        raise PermissionDeniedError("无权访问该项目")
    return project


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
    """上传文件到项目档案（P0-7-A）。

    P0-7-A 不解析文件：写入 DB 后状态=pending，等 P0-7-B 异步任务处理。
    """
    await _get_owned_project(db, project_id, user)

    # 1. 保存到临时文件（UploadFile 一次读完 → tmp）
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=Path(file.filename or "").suffix
    ) as tmp:
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
            # 文件过大
            db.delete(doc)
            await db.commit()
            raise PermissionDeniedError(str(e))

        # 4. 更新存储路径 + 大小
        doc.storage_path = rel_path
        doc.file_size = file_size
        await db.commit()
        await db.refresh(doc)

        return DocumentUploadResponse(
            id=doc.id,
            project_id=doc.project_id,
            document_type=doc.document_type,
            title=doc.title,
            file_name=doc.file_name,
            file_size=doc.file_size,
            mime_type=doc.mime_type,
            storage_path=doc.storage_path,
            storage_provider=doc.storage_provider,
            parse_status=doc.parse_status,
            created_at=doc.created_at,
        )
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
    """列项目下所有档案（按上传时间倒序）。"""
    await _get_owned_project(db, project_id, user)

    result = await db.execute(
        select(ProjectDocument)
        .where(ProjectDocument.project_id == project_id)
        .order_by(ProjectDocument.created_at.desc())
    )
    items = result.scalars().all()
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in items],
        total=len(items),
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentResponse:
    """档案详情。"""
    await _get_owned_project(db, project_id, user)

    doc = await db.get(ProjectDocument, document_id)
    if doc is None or doc.project_id != project_id:
        raise PermissionDeniedError(f"档案不存在: {document_id}")
    return DocumentResponse.model_validate(doc)
