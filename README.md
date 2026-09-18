# 钉铆 (DingMao)

> 面向设计院、监理、咨询机构的 AI 争议顾问 MVP
>
> **钉是钉，铆是铆** —— 讲法律，讲合规，不打马虎眼

[![Status](https://img.shields.io/badge/status-MVP-yellow)]()
[![Stack](https://img.shields.io/badge/stack-FastAPI%20%7C%20Vue3-blue)]()

---

## 项目特点

- 🎯 **聚焦工程行业**：合同审查 + 变更扯皮两个高频场景
- 📚 **数据确凿**：法条 + 强条知识库，结论可复核
- 🤝 **律师问诊式**：结构化多轮对话，采集事实后给结论
- 📄 **可产出文书**：签证单、索赔报告、监理通知单等

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11 + FastAPI + SQLAlchemy 2.0 |
| 前端 | Vue 3 + Vite + TypeScript + Element Plus |
| 数据库 | PostgreSQL 16（Docker 自建） |
| LLM 主力 | MiniMax-M3 |
| LLM 备用 | DeepSeek-V4-Flash |
| 部署 | 腾讯云轻量 + Docker Compose |

## 目录结构

```
DingMao/
├── backend/          # FastAPI 后端
├── frontend/         # Vue 3 前端
├── knowledge-base/   # 知识库原始数据
├── deploy/           # Docker Compose 部署
├── docs/             # 文档
├── AGENTS.md         # 项目导航与协作约定 ⬅️ 必读
└── README.md
```

## 快速开始

### 前置要求
- Python 3.11+
- Node.js 20+
- pnpm 9+
- uv 0.5+（[安装](https://docs.astral.sh/uv/getting-started/installation/)）
- Docker + Docker Compose

### 1. 启动基础设施（PostgreSQL + Redis）
```bash
docker compose -f deploy/docker-compose.dev.yml up -d
```

### 2. 启动后端
```bash
cd backend
cp .env.example .env
# 编辑 .env，填入 LLM API Key
uv sync                                    # 创建 .venv + 安装依赖
uv run alembic upgrade head                # 数据库迁移
uv run uvicorn app.main:app --reload --port 8000  # 启动后端
```

后端启动后访问：
- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs

### 3. 启动前端
```bash
cd frontend
cp .env.example .env
pnpm install
pnpm dev
```

前端启动后访问：http://localhost:5173

### 4. 一键启动（生产模式）
```bash
docker compose -f deploy/docker-compose.yml up -d
```

## 当前状态

✅ **已完成**（脚手架阶段）：
- 完整目录结构
- 后端核心：FastAPI + SQLAlchemy + Alembic + LLM 路由
- 前端核心：Vue 3 + Element Plus + 路由 + Pinia
- Docker Compose 一键部署
- 数据模型：用户/项目/文档/问诊/法条/强条

🚧 **下一步**（按路线图）：
- W1-W2：合同审查场景端到端
- W3-W4：律师问诊状态机
- W5-W8：变更扯皮场景
- W9-W12：打磨 + Beta

详细路线图见 `docs/product/decision-log.md`。

## 重要约定

⚠️ 修改任何代码前请先读 `AGENTS.md`。

核心原则：
1. 数据确凿优先（🟦 事实 + 🟨 法条 + 🟥 强条）
2. LLM 不生成关键数字（金额、时间、条款号、版本号）
3. 法条/强条引用必须有版本号 + 生效日期
4. 文书前必须显示免责
5. MVP 12 周红线

## 许可

仅供内部 MVP 阶段使用。