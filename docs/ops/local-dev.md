# 本地开发环境

> 1 人开发本地一键启动指南。

---

## 一、环境要求

| 工具 | 版本 | 用途 |
|---|---|---|
| Python | 3.11+ | 后端（用 uv 管理依赖） |
| Node.js | 20+ | 前端构建 |
| pnpm | 9+ | 前端包管理（不用 npm/yarn） |
| uv | 0.5+ | 后端包管理（不用 pip/poetry） |
| Docker | 24+ | PostgreSQL / Redis |
| Docker Compose | v2+ | 一键启动 |
| Git | 2.30+ | 版本控制 |

## 二、一键启动

```bash
# 1. 克隆代码（首次）
git clone <repo> && cd lawyer

# 2. 复制环境变量模板
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# 3. 启动后端依赖（PostgreSQL + Redis）
docker compose -f deploy/docker-compose.dev.yml up -d

# 4. 安装后端依赖（自动创建 .venv + uv.lock）
cd backend && uv sync

# 5. 数据库迁移
uv run alembic upgrade head

# 6. 启动后端
uv run uvicorn app.main:app --reload --port 8000

# 7. 另一个终端：启动前端
cd frontend && pnpm install && pnpm dev
```

访问：
- 前端：http://localhost:5173
- 后端 API：http://localhost:8000/docs（Swagger UI）

## 三、目录对应

- 后端代码改动 → 自动重载（uvicorn --reload）
- 前端代码改动 → HMR 自动刷新
- 数据库结构改动 → `alembic revision --autogenerate` + `alembic upgrade head`
- 知识库原始数据 → `knowledge-base/`，结构化脚本生成结果不入库

## 四、待补

- [ ] `.env.example` 实际内容
- [ ] 数据库迁移初始脚本
- [ ] 调试技巧（日志、断点）
- [ ] 常见问题排查