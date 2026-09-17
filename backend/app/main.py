"""FastAPI 应用入口。

启动顺序：
1. 加载配置
2. 创建应用实例
3. 注册中间件
4. 注册路由
5. 注册全局异常处理器
6. 启动/关闭事件
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import auth, consultations, health, knowledge, projects
from app.core.config import settings
from app.core.exceptions import AppError


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期。MVP 暂不做复杂初始化。"""
    # 启动事件
    yield
    # 关闭事件


app = FastAPI(
    title="建工法律顾问 API",
    version="0.1.0",
    description="面向建工行业的 AI 法律助手 - MVP",
    lifespan=lifespan,
    debug=settings.app_debug,
)

# ====== 中间件 ======
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ====== 全局异常处理 ======
@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """统一处理业务异常。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
        },
    )


# ====== 路由 ======
app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(consultations.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "建工法律顾问",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/api/v1/health",
    }
