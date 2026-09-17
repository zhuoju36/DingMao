# 技术栈与选型依据

> 完整选型依据。AGENTS.md 第三节只列概要。

---

## 一、后端

| 模块 | 选型 | 备注 |
|---|---|---|
| 语言 | Python 3.11+ | 项目所有者熟悉 |
| Web 框架 | FastAPI | 异步高性能，Pydantic v2 集成 |
| ORM | SQLAlchemy 2.0 (async) + Alembic | 类型安全 |
| 数据库驱动 | asyncpg | FastAPI 推荐 |
| 数据校验 | Pydantic v2 | 与 FastAPI 一体化 |
| 数据库 | PostgreSQL 16（Docker 自建）| jsonb + tsvector |
| 缓存/队列 | Redis 7 | Upstash 或本地 Docker |
| 任务队列 | ARQ（轻量异步）| MVP 不用 Celery，避免过重 |
| 模板引擎 | Jinja2 | 文书生成 |
| LLM SDK | OpenAI 兼容 SDK | MiniMax-M3 / DeepSeek-V4-Flash 都兼容 |
| 文档解析 | pdfplumber + PyMuPDF + PaddleOCR | 三件套覆盖文本/扫描件 |
| 部署 | Docker + Docker Compose | 一键启动 |

## 二、前端

| 模块 | 选型 | 备注 |
|---|---|---|
| 框架 | Vue 3 + Vite | 现代化、快 |
| 语言 | TypeScript | 类型安全 |
| UI 库 | Element Plus | 项目所有者偏好 |
| 状态管理 | Pinia | Vue 3 官方推荐 |
| 路由 | Vue Router 4 | 标配 |
| HTTP | Axios | 标配 |
| 表单 | Element Plus Form + 自定义校验 | 与事实采集卡场景契合 |
| Markdown | markdown-it | 渲染推理链 / 法条引用 |
| PDF 预览 | pdfjs-dist | 归档文件预览 |

## 三、LLM 服务

| 用途 | 模型 | 说明 |
|---|---|---|
| 主力 | **MiniMax-M3** | 1M 上下文，agentic & tool use 强 |
| 备用 1 | **DeepSeek-V4-Flash** | 13B 激活，低延迟低成本 |
| 兜底 | GPT-4o / Qwen-Max | 跨厂商冗余 |

详细路由设计见 `docs/architecture/llm-router.md`（待写）。

## 四、基础设施（腾讯云）

| 资源 | 选型 |
|---|---|
| 应用服务器 | 腾讯云轻量应用服务器（2核4G） |
| 数据库 | Docker 自建 PostgreSQL（同服务器） |
| 对象存储 | 腾讯云 COS（归档文件） |
| 域名 | 腾讯云 DNSPod |
| CDN | 腾讯云 CDN（可选） |
| 监控 | 腾讯云 Cloud Monitor（免费） |
| 备份 | pg_dump 本地 + COS 异地 |

## 五、不选的方案（明确排除）

- ❌ Kubernetes / 微服务（1 人开发过度工程）
- ❌ Serverless / 云函数（长任务支持弱）
- ❌ React + Ant Design（项目所有者不熟）
- ❌ MySQL（jsonb + 全文检索弱于 PG）
- ❌ MongoDB（事务弱，不适合核心业务数据）
- ❌ 自训模型（无数据、无算力、无必要）

## 六、待补

- [ ] LLM 路由详细设计
- [ ] 数据库索引设计
- [ ] API 鉴权方案
- [ ] 文件上传/下载链路
- [ ] 实时通信方案（如需）