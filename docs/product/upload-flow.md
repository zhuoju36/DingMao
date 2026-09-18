# 项目档案上传流程（Upload → Parse → Store）

> 日期：2026-09-18
> 状态：待用户拍板（已对齐方向，文档初版）

---

## 一、功能边界

| 项 | 决策依据 |
|---|---|
| ❌ 用户上传不进**通用知识库** | 决策日志 §6：MVP 知识库范围锁定为 50 部法规 + 38 本强条，**其他不入库** |
| ✅ 用户上传进**项目档案**（ProjectDocument）| `data-model.md` 第 117-138 行：表结构已建，W1 未实现上传 |
| ❌ 推荐性国标 | 决策日志 §6 红线：仅强条入库 |
| ❌ 第三方软件对接 | 决策日志 §6 红线 |

**核心结论**：本流程只覆盖"项目档案"，通用知识库由项目所有者按 `docs/domain/knowledge-base.md` 规范手动维护（该文档待补）。

## 二、用户决策（2026-09-18 对齐）

| 决策点 | 选择 | 理由 |
|---|---|---|
| 上传范围 | 仅项目档案 | 严格遵守决策日志 §6 |
| 文件类型指定 | 用户手动选 | 可控、不增加 LLM 调用 |
| 异步模式 | 后台异步 + 状态徽章 | 解析 2-5 分钟不能让用户干等 |
| 解析后编辑 | 不允许 | MVP 最简；纠错靠 PDF 原文回查 |

## 三、入口与信息架构

### 3.1 入口位置

**项目详情页新增"档案"Tab**（`/projects/:id` 下）：

```
项目详情 Tab 顺序（更新）：
  [概览] [合同审查] [变更扯皮] [档案] [强条速查]

MVP 仅 2 个 P0 场景可用，但档案 Tab 始终可见（V2 通用知识库场景可共用）
```

### 3.2 与已有 IA 的兼容

- ✅ 不破坏 `ia.md` 第 7 节 MVP 优先级
- ✅ 项目页 Tab 兜底原则（≤3 个 Tab）— 当前是 4 个，触发 "MVP 升级为网格" 决策（`ia.md` 第 27 行）
- ✅ 顶级"档案"顶级菜单**暂不做**（V2+ 考虑）

## 四、文件分类

按 `data-model.md` 第 127 行定义 6 种 `document_type`，上传时强制单选：

| 类型 | 用途 | 典型文件 |
|---|---|---|
| `contract` | 合同审查场景主输入 | 总包合同、分包合同、补充协议 |
| `bidding` | 招投标合规 | 招标文件、投标文件 |
| `variation` | 变更扯皮主输入 | 签证单、变更申请 |
| `correspondence` | 沟通证据 | 监理通知单、工作联系单 |
| `inspection` | 现场记录 | 隐蔽工程验收单、检验批 |
| `evidence` | 通用证据 | 聊天记录截图、照片、签收单 |

## 五、状态机

```
  ┌──────────┐  上传成功    ┌──────────┐  解析完成  ┌──────────┐
  │ pending  │ ───────────▶ │ parsing  │ ────────▶ │ parsed   │
  └──────────┘              └──────────┘           └──────────┘
       │                          │                      │
       │ 上传失败                  │ 解析失败              │ 用户重解析
       ▼                          ▼                      ▼
  ┌──────────┐              ┌──────────┐            ┌──────────┐
  │ failed   │              │ failed   │            │ parsing  │ (重置)
  │ upload   │              │ parse    │            │ (重新)    │
  └──────────┘              └──────────┘            └──────────┘
```

### 5.1 状态徽章规约（前端）

| 状态 | 颜色 | 图标 | 文案 |
|---|---|---|---|
| `pending` | 灰 | ⏳ | 待解析 |
| `parsing` | 黄 | 🔄 | 解析中 |
| `parsed` | 绿 | ✅ | 已解析 |
| `failed_upload` | 红 | ❌ | 上传失败 |
| `failed_parse` | 红 | ⚠️ | 解析失败 |
| `archived` | 灰 | 📦 | 已归档 |

## 六、API 设计（✅ 已实现，2026-09-18）

| 端点 | 方法 | 用途 | 实现状态 |
|---|---|---|---|
| `/api/v1/projects/:id/documents` | GET | 列项目档案 | ✅ P0-7-A |
| `/api/v1/projects/:id/documents` | POST | 上传文件（multipart/form-data）| ✅ P0-7-A + 自动入队解析 |
| `/api/v1/projects/:id/documents/:doc_id` | GET | 详情（含 `parsed_content`）| ✅ P0-7-A |
| `/api/v1/projects/:id/documents/:doc_id` | DELETE | 删除（DB + 源文件 + 解析产物）| ✅ P0-7-B |
| `/api/v1/projects/:id/documents/:doc_id/reparse` | POST | 重解析（清产物 → 重置 pending → 入队）| ✅ P0-7-B |

实现位置：`backend/app/api/v1/documents.py`

### 6.1 POST 字段

```
file:           binary  （必填，PDF/图片，最大 50MB）
document_type:  enum    （必填，6 选 1）
title:          string  （可选，默认取原文件名）
```

### 6.2 后端流程（✅ 已实现）

```
1. POST /documents                        [app/api/v1/documents.py]
   - 鉴权：项目 owner（MVP 单用户；成员权限待 V2 ProjectMember）
   - 校验文件大小（>50MB → 422 DocumentValidationError）
   - 落本地 storage/projects/{project_id}/{doc_id}{ext}
   - 写 project_documents（parse_status=pending）
   - task_queue.enqueue_parse_document()  ← best-effort，队列挂了也返回 201
   - 返回 201 + document_id

2. ARQ worker（独立进程）                  [app/worker.py]
   - 启动: cd backend && .venv/bin/arq app.worker.WorkerSettings
   - 置 parsing → 调 ingest.parse_document()（subprocess 跑 MinerU）
   - 成功: parsed   + parsed_content + 产物落盘 storage/parsed/{pid}/{did}/
   - 失败: failed_parse + parse_error（不抛异常，避免 ARQ 无意义重试）
   - 文档在排队期间被删 → 静默跳过

3. POST /documents/:doc_id/reparse
   - 清 parsed_content / parse_error → 重置 pending → 重新入队
   - 去重：_job_id="parse:{doc_id}" + keep_result=0
     （去重窗口 = 排队中+执行中；任务结束后可再次重解析）

4. DELETE /documents/:doc_id
   - 删源文件 + 删解析产物目录 + 删 DB 行，返回 204
```

### 6.3 parsed_content 结构（实现与设计稿的偏差，已确认）

设计稿原写 `{markdown, middle_json}` 全内联。**实际实现只内联 markdown**：

```json
{
  "markdown": "……正文……",
  "page_count": 3,
  "markdown_chars": 253,
  "middle_json_bytes": 3958,
  "images": 0,
  "elapsed_sec": 3.2,
  "tier": "flash",
  "parsed_dir": "parsed/7/2"
}
```

**理由**：`middle.json` 单文件可达数百 KB（GB55037 实测 388 KB），逐份内联进 JSONB
会明显膨胀 DB；而 MVP 喂 LLM 只需要 markdown。完整产物（middle.json / images/ /
structured_content.json / model_output.json）留在 `storage/parsed/{pid}/{did}/`，
需要按页定位时再读盘。符合"原则 7 知识库与代码解耦（可重建）"。

### 6.4 MinerU 调用方式（关键架构约束）

MinerU 依赖 **7.3 GB**（torch/onnxruntime + 模型），不装进 backend venv（737 MB）。
后端通过 **subprocess** 调用「装了 MinerU 的解释器」执行
`backend/scripts/mineru_parse.py`，解释器路径由 `MINERU_PYTHON` 配置。

- 本地开发：`MINERU_PYTHON=../experiments/mineru-test/.venv/bin/python`
- 生产部署：需单独准备 mineru venv，填绝对路径（见 `.env.example`）
- 未配置时：上传仍成功，解析以 `failed_parse` + 明确错误信息失败（不静默跳过）

## 七、页面布局

```
┌────────────────────────────────────────────────────┐
│ Projects / XX 综合楼工程                            │
├────────────────────────────────────────────────────┤
│ [概览] [合同审查] [变更扯皮] [档案 (4)] [强条速查] │
├────────────────────────────────────────────────────┤
│ 📁 项目档案                                         │
│                                                     │
│ + 上传文件  筛选: [全部类型 ▼] [全部状态 ▼] [🔍]  │
│ ─────────────────────────────────────────────────  │
│ ┌────────────────────────────────────────────────┐ │
│ │ 📄 总包合同_v3.pdf                              │ │
│ │ 合同 · 2026-03-15 · 12.5 MB · ✅ 已解析         │ │
│ │ 32 页 · 145 事实卡片 · 张工上传                  │ │
│ │ [查看] [下载原文] [重新解析] [⋯]               │ │
│ └────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────┐ │
│ │ 📷 现场签证单_2026-04.jpg                       │ │
│ │ 签证单 · 2026-04-22 · 2.1 MB · 🔄 解析中       │ │
│ │ ████████░░░ 78% · 预计还需 30s · 张工上传      │ │
│ └────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────┐ │
│ │ 📋 监理通知单_005.pdf                           │ │
│ │ 监理 · 2026-05-01 · 0.8 MB · ⚠️ 解析失败       │ │
│ │ 原因: PDF 加密 · 张工上传                       │ │
│ │ [下载原文] [重新解析] [删除]                    │ │
│ └────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────┘
```

## 八、错误处理

| 场景 | 用户提示 | 后端动作 |
|---|---|---|
| 文件 > 50MB | "文件超过 50MB 限制" | 拒绝上传 |
| 非 PDF / 图片 | "仅支持 PDF、JPG、PNG" | 拒绝上传 |
| MinerU 解析失败 | "解析失败：[原因]" | 状态置 failed_parse，保留原文件 |
| PDF 加密 | "PDF 已加密，请解密后重试" | 状态 failed_parse |
| 扫描件低识别率 | "识别率低，建议手工补事实" | 状态 parsed，quality 标记 |

## 九、后续可扩展（V2）

- OCR 纠错（上传者编辑解析产物）
- 跨项目档案搜索（Cmd+K 全局）
- 文件版本管理
- 自动归档规则（按时间 / 状态）
- 多人协作评论（违背 MVP 红线，**永远不做**）

## 十、决策点 vs 决策日志

本次设计**未修改**决策日志。沿用：
- §6 MVP 边界（用户上传不进通用库）
- §6 角色反转（项目级角色，影响上传者权限校验）
- §7 知识库与代码解耦（parsed_content JSONB 可重建）

如未来要扩展"用户上传进通用库"，需先改决策日志并升级 MVP 范围。
