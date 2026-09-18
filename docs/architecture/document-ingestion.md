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

## 四、架构位置

```
                       ┌────────────────────────┐
   用户上传 PDF ──────▶│  POST /documents        │
                       │  (FastAPI /api/v1/...)  │
                       └──────────┬─────────────┘
                                  │ 异步任务
                                  ▼
                       ┌────────────────────────┐
                       │  app/services/ingest.py │
                       │  (薄封装 MinerU)         │
                       └──────────┬─────────────┘
                                  │ subprocess / direct call
                                  ▼
                       ┌────────────────────────┐
                       │  MinerU 4.0 Flash       │
                       │  (本地 ONNX CPU 推理)    │
                       └──────────┬─────────────┘
                                  │ Markdown + MiddleJson + images/
                                  ▼
                       ┌────────────────────────┐
                       │  app/services/store.py  │
                       │  (持久化到 PostgreSQL)  │
                       └──────────┬─────────────┘
                                  │
                                  ▼
                       ┌────────────────────────┐
                       │  project_documents 表   │
                       │  (parsed_content JSONB) │
                       └────────────────────────┘
```

## 五、数据契约

每本 PDF 摄入后落 3 类产物：

```python
# Markdown（喂 LLM）
document.md  # UTF-8 文本，含 # 章节标题、表格、列表

# MiddleJson（结构化定位）
middle.json  # schema="docvortex.middle", version="2.0"
             # pages[i].blocks[j] = {type, level, bbox, content}
             # bbox = [x0, y0, x1, y1] （PDF 比例坐标）

# 素材（图片/原图块）
images/  # PNG，每块一张；文件名含 page_idx + block_idx
```

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

## 七、运行时依赖

| 项 | 位置 | 大小 | 说明 |
|---|---|---|---|
| MinerU 4.0 wheel | `experiments/mineru-test/.venv/` | ~500MB | Python 包 |
| ONNX 小模型（PP-DocLayoutV2 + PaddleOCR v6）| `~/.mineru/models/MinerU-4_models_onnx/` | ~500MB | MinerU 自动下载 |
| VLM GGUF（仅 standard 档）| `~/.mineru/models/MinerU2.5-Pro-2605-1.2B-GGUF/` | 1.18GB | 手动下载，目前**未使用** |

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
