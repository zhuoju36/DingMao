# MinerU Standard 档 GTX 1080 可行性实验报告

> 日期：2026-09-18
> 实验人：AI 编码助手（执行）+ 项目所有者（决策）
> 状态：**结论：Standard 档在 Pascal 架构 GPU 上不可行**，改用 Flash 档跑全部 38 本国标

---

## 一、实验目标

验证 MinerU 4.0 Standard 档（带 VLM 语义理解）能否在项目所有者的 GTX 1080 (Pascal sm_61) 上跑通，转换一本国标 PDF 作为知识库结构化样本。

## 二、决策点（决策日志应记录）

| 项 | 选项 | 最终选择 |
|---|---|---|
| 路径 | standard+llamacpp(GPU 4-bit) / standard+llamacpp(CPU) / basic / Flash | **Flash 档** |
| 目录 | experiments/ / backend/scripts/ / tmp/ | **experiments/mineru-test/** |

---

## 三、环境实测

| 项 | 值 |
|---|---|
| GPU | 2 × NVIDIA GeForce GTX 1080 (Pascal sm_61, 8GB × 2) |
| 驱动 | CUDA 12.3（向下兼容 11.x/12.x runtime）|
| 系统 CUDA | cuda-12-1 + cuda-12-8 已通过 apt 装好（含 nvcc）|
| Python | 3.10.12（系统）/3.11（backend venv）|
| 系统 glibc | 2.35（满足 torch 2.7 cu128 manylinux_2_28 tag）|
| sudo | ❌ 需要密码（apt 装系统包受阻）|

---

## 四、关键发现

### 4.1 ✅ Flash 档端到端跑通（GB55005-2021 木结构通用规范，2.7MB / 20 页）

- **耗时**：135.5 秒（CPU + ONNX，约 6.7 秒/页）
- **产物**：Markdown 9121 字 / 439 行 + MiddleJson 84KB
- **质量**：章节结构、目次、条文编号（7.0.5 等）全部正确保留
- **自动下载**：PP-DocLayoutV2 + PaddleOCR v6 等 ONNX 小模型（214MB）

### 4.2 ✅ VLM 模型（1.2B Q8_0）加载与推理成功

- **模型**：`jinzhenj/MinerU2.5-Pro-2605-1.2B-GGUF`（HF/ModelScope）
- **大小**：主模型 506MB + mmproj 677MB = **1.18GB**（Q8_0 量化）
- **推理引擎**：`mineru-llama-cpp`（自带预编译 .so + Vulkan 后端）
- **CPU 模式实测**：43.3 秒/页（prompt 19 t/s / predicted 48 t/s）
- **输出质量**：完美 OCR 出 GB55005 前言正文，准确率高

### 4.3 🚨 阻断点 1（致命）：PyTorch 2.7 放弃 Pascal

```
Found GPU0 NVIDIA GeForce GTX 1080 which is of cuda capability 6.1.
PyTorch no longer supports this GPU because it is too old.
The minimum cuda capability supported by this library is 7.5.
```

- MinerU 4.0 要求 `torch>=2.7.0`，**最低支持 sm_75（Turing 架构）**
- GTX 1080 = Pascal sm_61 → PyTorch 算子全部拒绝运行
- Standard 档的 small model backend（PP-DocLayoutV2 + PaddleOCR torch 版）走不通
- **结论：Standard 档的整条 pipeline 在 Pascal 架构上不可行**

### 4.4 ⚠️ 阻断点 2：Vulkan ICD 缺失

- `mineru-llama-cpp` 自带 `libggml-vulkan.so`
- 但 `/usr/share/vulkan/icd.d/` 是空（NVIDIA Vulkan ICD 没装）
- llama.cpp 自动 fallback 到 **CPU 后端**（实测可工作但慢）

### 4.5 ⚠️ 阻断点 3：sudo 需要密码

- 装 NVIDIA Vulkan ICD (`apt install vulkan-nvidia-driver`) 需 sudo
- 装 torch 老版本（如 2.3+cu118）需重做 venv
- 自动化装包受阻

---

## 五、性能对比

| 路径 | 单页耗时 | 20 页 PDF | 输出质量 | 可行性 |
|---|---|---|---|---|
| **Flash 档（实测）** | 6.7s | 135s | 文本好，复杂版式一般 | ✅ 已验证 |
| Standard + llama-cpp CPU | 43s | 14 min | VLM + OCR 完美（实测） | ❌ Standard 档 small model 跑不了 |
| Standard + llama-cpp GPU | ~5s 估 | ~2 min | 最好 | ❌ 需 Vulkan ICD + sudo |
| vLLM | — | — | — | ❌ vLLM 同样不支持 Pascal |

---

## 六、产物清单（`experiments/mineru-test/`）

```
experiments/mineru-test/
├── .venv/                                    # 独立 Python 环境
├── scripts/
│   ├── 01_flash_smoke.py                    # Flash 档烟雾测试
│   └── 02_standard_smoke.py                 # Standard 档烟雾测试（备用）
├── output/
│   └── flash_smoke/
│       ├── document.md                      # 9121 字 GB55005 Markdown
│       └── middle.json                      # 84KB MiddleJson
└── decisions-and-results.md                 # 本报告
```

外部产物：
- `~/.mineru/models/MinerU2.5-Pro-2605-1.2B-GGUF/`（1.18GB GGUF 模型，可复用）
- `~/.mineru/models/MinerU-4_models_onnx/`（214MB ONNX 小模型，可复用）
- `~/.mineru/config.yaml`（已配置 modelscope 源）

---

## 七、下一步建议（已确认采纳）

按 AGENTS.md 决策日志第 62-69 行："**MVP 知识库范围：50 部核心法规 + 38 本通用规范全文强条**"。

- [x] Flash 档跑通，已验证知识库结构化技术路径
- [ ] **批量转换全部 38 本国标**（用 `batch_parse_standards.py`）
- [ ] 从 MiddleJson 抽取强条（"强制性"标记的条款）
- [ ] 写入 PostgreSQL `standards` / `standard_clauses` 表
- [ ] 关联 `behavior_standard_mapping`（决策日志强调的"最有价值资产"）

## 八、未来 V2 评估

如果未来升级到 Turing+ GPU（如 RTX 3090 / RTX 4090 / Tesla T4），MinerU Standard 档可立即启用，路径已验证：
1. 装 CUDA 12.8 兼容 torch wheel
2. 装 NVIDIA Vulkan ICD
3. 配置 `config.yaml` 的 `model.vlm.engine: llama-cpp` + `n_gpu_layers: 99`
4. 预期：单页 3-8 秒，质量比 Flash 档显著提升
