"""项目路由：W1 极简 CRUD。"""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user
from app.core.exceptions import PermissionDeniedError
from app.models.base import get_db
from app.models.consultation import Consultation
from app.models.project import Project
from app.models.user import User
from app.schemas.consultation import ConsultationListResponse
from app.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
)
from app.services import consultation_engine

router = APIRouter(prefix="/projects", tags=["projects"])


async def _get_owned_project(
    db: AsyncSession, project_id: int, user: User
) -> Project:
    """获取项目（要求当前用户是 owner，否则 404/403）。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise PermissionDeniedError(f"项目不存在: {project_id}")
    if project.owner_id != user.id:
        raise PermissionDeniedError("无权访问该项目")
    return project


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    req: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectResponse:
    """创建项目。W1 同时把合同文本存入 contract_clauses（JSONB 的 contract_text 字段）。"""
    project = Project(
        owner_id=user.id,
        name=req.name,
        code=req.code,
        description=req.description,
        location=req.location,
        contract_amount=req.contract_amount,
        contract_start_date=req.contract_start_date,
        contract_end_date=req.contract_end_date,
        contract_duration_days=req.contract_duration_days,
        owner_org=req.owner_org,
        design_org=req.design_org,
        supervisor_org=req.supervisor_org,
        contractor_org=req.contractor_org,
        role=req.role.value,  # 用户在本项目里的角色，LLM 视角依据
        contract_clauses={"contract_text": req.contract_text} if req.contract_text else None,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return _to_response(project)


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 20,
) -> ProjectListResponse:
    """我的项目列表。"""
    stmt = (
        select(Project)
        .where(Project.owner_id == user.id)
        .order_by(Project.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()
    total = len(items)  # W1 简化，不做 count
    return ProjectListResponse(
        items=[_to_response(p) for p in items],
        total=total,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectResponse:
    """项目详情。"""
    project = await _get_owned_project(db, project_id, user)
    return _to_response(project)


@router.get("/{project_id}/consultations", response_model=ConsultationListResponse)
async def list_project_consultations(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    scenario: str | None = None,
    limit: int = 50,
) -> ConsultationListResponse:
    """列出项目下的问诊（可按 scenario 过滤）。

    用于项目详情页的「历史问诊」列表。
    """
    project = await _get_owned_project(db, project_id, user)

    stmt = (
        select(Consultation)
        .where(Consultation.project_id == project_id)
        .options(
            selectinload(Consultation.conclusions),
            selectinload(Consultation.facts),
        )
        .order_by(Consultation.created_at.desc())
        .limit(limit)
    )
    if scenario:
        stmt = stmt.where(Consultation.scenario == scenario)

    rows = (await db.execute(stmt)).scalars().all()

    items = [consultation_engine.to_list_item(c, project.name) for c in rows]

    return ConsultationListResponse(
        project_id=project_id, items=items, total=len(items)
    )


def _to_response(p: Project) -> ProjectResponse:
    """Project ORM -> ProjectResponse，提取 contract_text。"""
    clauses = p.contract_clauses or {}
    return ProjectResponse(
        id=p.id,
        name=p.name,
        code=p.code,
        description=p.description,
        location=p.location,
        contract_amount=p.contract_amount,
        contract_start_date=p.contract_start_date,
        contract_end_date=p.contract_end_date,
        contract_duration_days=p.contract_duration_days,
        owner_org=p.owner_org,
        design_org=p.design_org,
        supervisor_org=p.supervisor_org,
        contractor_org=p.contractor_org,
        role=p.role,
        contract_text=clauses.get("contract_text"),
        contract_clauses=p.contract_clauses,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )
