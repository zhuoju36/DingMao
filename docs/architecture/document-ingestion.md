# 文档摄入（Document Ingestion）

> 把 PDF（合同/规范/签证单等）转为结构化文本 + 定位信息，供后续 LLM 检索 / 引用 / 渲染。

---

## 一、目标

| 能力 | 用途 |
|---|---|
| PDF → Markdown | 喂 LLM；前端预览 |
| PDF → MiddleJson（含 bbox） | 条款级定位回查、跳转原文 |
| 图片/表格单独提取 | 文书归档、视觉证据 |

## 二、引擎选型

**MinerU 4.0**（[opendatalab/MinerU](https://github.com/opendatalab/MinerU)），四档解析：

| 档位 | VLM | 速度（20 页 PDF） | 适用场景 |
|---|---|---|---|
| `flash` | ❌ | ~2 min（CPU ONNX）| MVP 默认；规范/合同正文 |
| `basic` | ❌ | ~3 min | OCR + 表格 + 公式，但无语义 |
| `standard` | ✅ | ~15 min（CPU）| 复杂版式、扫描件 |
| `advanced` | ✅ | 更慢 | 最高质量 |

详细档位与依赖见 [MinerU tiers 文档](https://opendatalab.github.io/MinerU/zh/usage/tiers/)。

## 三、MVP 范围

- **MVP** 只用 `flash` 档（已验证在 Pascal/CPU 跑通，详见 `experiments/mineru-test/decisions-and-results.md`）
- 标准档留到 V2（升级 GPU 后启用）

## 四、架构位置（✅ 已实现，P0-7-A/B）

```
  ┌──────────────────────────┐
  │ 用户上传 PDF              │
  └────────────┬─────────────┘
               ▼
  ┌──────────────────────────┐
  │ POST /projects/{id}/documents │  app/api/v1/documents.py
  │ - 校验大小（≤50MB）        │
  │ - 落盘 storage/projects/   │  app/services/storage.py
  │ - 写 DB（pending）         │
  │ - 入队（best-effort）      │  app/services/task_queue.py
  └────────────┬─────────────┘
               │ 201 立即返回（不等解析）
               ▼
  ┌──────────────────────────┐
  │ Redis 队列（ARQ）          │
  └────────────┬─────────────┘
               ▼
  ┌──────────────────────────┐
  │ ARQ worker（独立进程）      │  app/worker.py
  │ - 置 parsing               │
  │ - 调 ingest.parse_document │  app/services/ingest.py
  └────────────┬─────────────┘
               │ subprocess（跨 venv！）
               ▼
  ┌──────────────────────────┐
  │ mineru venv 解释器         │  MINERU_PYTHON 配置
  │ -> scripts/mineru_parse.py │  backend/scripts/mineru_parse.py
  │ -> MinerU 4.0 Flash        │
  └────────────┬─────────────┘
               │ 写 document.md / middle.json / images/ / manifest.json
               ▼
  ┌──────────────────────────┐
  │ storage/parsed/{pid}/{did}/│  完整产物落盘（可重建）
  └────────────┬─────────────┘
               │ 读 manifest.json + document.md
               ▼
  ┌──────────────────────────┐
  │ project_documents 表       │
  │ - parse_status=parsed      │
  │ - parsed_content JSONB     │  ← 只内联 markdown + 元信息
  └──────────────────────────┘
```

**为什么 subprocess 跨 venv**：MinerU 依赖 7.3 GB，backend venv 只有 737 MB，
且部署目标是腾讯云轻量 2核4G。详见 [`docs/product/upload-flow.md`](../product/upload-flow.md) §6.4。

## 五、数据契约

### 5.1 落盘布局（✅ 已实现）

```
backend/storage/
├── projects/{project_id}/{document_id}{ext}      源文件（用户上传原件）
└── parsed/{project_id}/{document_id}/            解析产物
    ├── document.md              Markdown 正文（喂 LLM）
    ├── middle.json              MiddleJson（bbox 定位）
    ├── images/                  图片素材（如有）
    ├── manifest.json            解析元信息（status/elapsed/page_count/error）
    ├── structured_content.json  MinerU 附赠
    ├── model_output.json        MinerU 附赠
    └── markdown.md / middle_json.json  MinerU save() 的副本
```

`manifest.json` 是脚本与后端之间的**唯一可信契约**（后端不解析 stdout）：

```json
{
  "input": "/path/to.pdf", "tier": "flash", "input_size": 2806,
  "status": "success", "elapsed_sec": 3.2,
  "markdown_chars": 253, "middle_json_bytes": 3958,
  "page_count": 3, "images": 0
}
```

失败时 `status="failed"` + `error`（后端据此写 `parse_error`）。

### 5.2 DB 与磁盘的分工

| 数据 | 位置 | 理由 |
|---|---|---|
| `markdown` | DB `parsed_content`（内联）| 喂 LLM / 检索需要，体积可控 |
| `page_count` 等元信息 | DB `parsed_content` | 列表页展示用 |
| `middle.json` | **仅磁盘** | 单份可达数百 KB，内联会膨胀 DB |
| `images/` | **仅磁盘** | 二进制，不入 DB |

需要「跳转到原文第 N 页 / 高亮 bbox」时，按 `parsed_content.parsed_dir` 读盘。
详见 [`docs/product/upload-flow.md`](../product/upload-flow.md) §6.3。

## 六、知识库批量入库（一次性）

MVP 决定把 38 本国标通用规范全部入库（决策日志 §6）。

### 流程

```
knowledge-base/standards/mohurd-source/*.pdf  (31 本源文件)
                │
                │ experiments/mineru-test/scripts/batch_run.py
                │ （tier=flash，单进程顺序，~2-3 min/本）
                ▼
knowledge-base/standards/parsed/<标准编号-名称>/
                ├── document.md
                └── middle.json
                │
                │ experiments/mineru-test/scripts/extract_clauses.py
                │ （X.Y.Z 模式正则 + MiddleJson bbox 关联）
                ▼
knowledge-base/standards/clauses/
                ├── clauses_overview.csv   # 统计
                └── clauses_full.json      # 每条强条 + bbox
```

### 已落库数据

详见 `experiments/mineru-test/output/clauses_overview.csv`（每次 batch 跑完后刷新）。

## 七、运行时依赖（2026-09-18 实测修正）

| 项 | 位置 | 实测大小 | 说明 |
|---|---|---|---|
| MinerU venv（含 torch/onnxruntime 全套）| `experiments/mineru-test/.venv/` | **7.3 GB** | 由 `MINERU_PYTHON` 指向 |
| ONNX 小模型（PP-DocLayoutV2 + PaddleOCR v6）| `~/.mineru/models/MinerU-4_models_onnx/` | ~500 MB | MinerU 首次运行自动下载 |
| VLM GGUF（仅 standard 档）| `~/.mineru/models/MinerU2.5-Pro-2605-1.2B-GGUF/` | 1.18 GB | 手动下载，Flash 档**未使用** |
| backend venv | `backend/.venv/` | 737 MB | 不含 MinerU |

> ⚠️ **修正记录**：本文档早前把 MinerU 依赖记为 "~500MB"，实测 venv 为 **7.3 GB**
> （torch + onnxruntime + CUDA 运行时库）。这个数量级差异直接决定了架构选型
> （subprocess 跨 venv，而非装进 backend venv）。

### 7.1 生产部署未解问题（诚实记录）

当前实现让**本地开发**可跑通，但部署到目标环境（腾讯云轻量 2核4G）还有未解问题：

| 问题 | 现状 | 影响 |
|---|---|---|
| 7.3 GB venv + 1.4 GB 模型 | 未纳入 Docker 镜像 | 镜像体积/构建时间不可接受 |
| 解析 CPU 开销 | Flash 档实测 ~5s/3页、~135s/20页（开发机）| 2核4G 上更慢，且会抢占 API 进程 CPU |
| worker 与 API 同机 | 未做资源隔离 | 大文件解析期间 API 可能受影响 |

**V2 需决策**：① 单独一台解析机；② 云 GPU 跑 standard 档；③ MinerU 拆成独立服务。
在此之前，MVP 内测阶段建议在开发机/内网机器上运行 worker。

> ⚠️ MinerU 默认把模型缓存到 `~/.mineru/`（工作区外）。
> 这是 MinerU 的标准行为，不视为"碰工作区外文件"。
> 若 workspace 重建，重新跑 `batch_run.py` 时 MinerU 会自动从 ModelScope/HuggingFace 重新拉取模型。

## 八、未来升级路径（V2）

当硬件升级到 Turing+ GPU 后：

1. 装 `torch==2.7+cu128` wheel + NVIDIA Vulkan ICD
2. 下载 VLM GGUF 模型到 `~/.mineru/`
3. `parse(pdf, tier="standard")` 启用
4. 预计标准档单页 3-8 秒（V100/A100 上），质量显著优于 flash 档

## 九、决策记录（待补入 decision-log.md）

| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-09 | MVP 用 MinerU Flash 档 | GTX 1080 (Pascal) + PyTorch 2.7 已放弃 sm_61，Standard 档不可行；Flash 档已验证质量满足 MVP |
| 2026-09 | 知识库批量入库（38 本国标）| 对应决策日志 §6 MVP 范围；用 batch_run.py + extract_clauses.py 解耦代码与知识库 |
