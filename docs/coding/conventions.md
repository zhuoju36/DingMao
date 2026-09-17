# 代码规范与目录约定

> 索引页。**不在本文件堆示例代码**。具体示例按需创建子文件。

---

## 一、总体原则

1. **可读性优先** — 代码是写给人看的，机器执行只是顺带
2. **类型安全** — 后端 Pydantic v2 + 前端 TypeScript，禁止 `any` 滥用
3. **小函数、长模块** — 单函数不超过 50 行，模块按职责切分
4. **约定优于配置** — 框架默认行为不轻易覆盖
5. **不写死魔法值** — 配置进 `.env`，常量集中管理

## 二、目录约定

### 2.1 后端（backend/）

```
backend/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── core/                # 配置、安全、依赖注入
│   ├── api/v1/              # 路由（按业务模块拆分）
│   ├── models/              # SQLAlchemy 模型（表结构）
│   ├── schemas/             # Pydantic schemas（API DTO）
│   ├── services/            # 业务逻辑层（LLM、文档解析、文书生成等）
│   ├── db/                  # 数据库连接、迁移
│   └── knowledge/           # 法条/强条/映射（领域逻辑）
├── alembic/                 # 数据库迁移
├── tests/                   # 测试
├── Dockerfile
├── pyproject.toml           # 项目 manifest（uv 用）
├── uv.lock                  # 依赖锁文件（uv 生成，必须入库）
└── .python-version          # Python 版本锁定（uv 标准）
```

**核心约定**：
- `api/` 只做参数解析与路由转发，业务逻辑放 `services/`
- `models/` 表结构、`schemas/` 接口契约，不混用
- `services/` 跨业务调用必须显式 import，不做隐式注入

### 2.2 前端（frontend/）

```
frontend/
├── src/
│   ├── main.ts
│   ├── App.vue
│   ├── views/               # 页面级组件
│   ├── components/          # 通用组件
│   ├── stores/              # Pinia stores
│   ├── router/              # 路由
│   ├── api/                 # Axios 封装 + API 定义
│   ├── types/               # TS 类型定义
│   ├── utils/               # 工具函数
│   └── styles/              # 全局样式
├── public/
├── Dockerfile
├── nginx.conf
├── package.json
├── vite.config.ts
└── tsconfig.json
```

**核心约定**：
- 视图组件 `PascalCase.vue`，工具组件 `kebab-case.vue`
- Pinia stores 按业务模块拆（user、project、consultation...）
- API 调用统一走 `src/api/`，禁止在组件内直接 axios

## 三、命名规范

| 类别 | 后端（Python） | 前端（TS/Vue） |
|---|---|---|
| 变量/参数 | snake_case | camelCase |
| 函数/方法 | snake_case | camelCase |
| 类 | PascalCase | PascalCase |
| 常量 | UPPER_SNAKE | UPPER_SNAKE |
| 文件名 | snake_case.py | PascalCase.vue / kebab-case.ts |
| 数据库表 | snake_case（复数） | — |
| API 路径 | /kebab-case | — |

## 四、代码风格

- **后端**：Ruff（lint + format）+ mypy（type check）
- **前端**：ESLint + Prettier（Vue 3 推荐配置）
- **提交前必须通过**，CI 卡点

详细配置见 `backend/pyproject.toml`（已包含 ruff / mypy / pytest 配置）。

后端使用 [uv](https://docs.astral.sh/uv/) 管理依赖，命令：
- `uv sync` — 同步依赖到 `.venv`
- `uv add <pkg>` — 添加新依赖
- `uv run <cmd>` — 在虚拟环境中运行命令
- `uv lock` — 更新 lockfile

## 五、错误处理约定

详见 `docs/coding/error-handling.md`（待补）。

核心要点：
- 后端：自定义异常类 + 全局异常处理器，**禁止裸 except**
- 前端：Axios interceptor 统一处理 + 用户友好提示

## 六、待补

- [ ] 后端代码示例
- [ ] 前端组件示例
- [ ] Pydantic schema 写法示例
- [ ] Pinia store 写法示例
- [ ] Git 提交规范（Conventional Commits？）