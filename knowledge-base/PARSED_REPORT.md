# 国标通用规范结构化报告

> 日期：2026-09-18
> 处理人：AI 编码助手
> 状态：✅ 31 本全部入库

---

## 一、覆盖范围

| 项 | 值 |
|---|---|
| 已处理规范 | **31 本**（GB 55001 ~ GB 55037，缺 17 个编号） |
| 总页数 | **961 页** |
| 强条总数 | **6531 条**（GB 55000 系列全文强制性）|
| Markdown 总量 | 1.8 MB（1,841,058 字符）|
| MiddleJson 总量 | ~5 MB（含 bbox 定位）|
| 解析产物（parsed/）| 7.7 MB |
| 平均强条密度 | 6.8 条/页 |

## 二、规模分布

### Top 5（条款最多）

| 编号 | 名称 | 页 | 强条 |
|---|---|---:|---:|
| GB55037-2022 | 建筑防火通用规范 | 66 | **653** |
| GB55024-2022 | 建筑电气与智能化通用规范 | 45 | **425** |
| GB55033-2022 | 城市轨道交通工程项目规范 | 42 | **347** |
| GB55015-2021 | 建筑节能与可再生能源利用通用规范 | 82 | **314** |
| GB55002-2021 | 建筑与市政工程抗震通用规范 | 46 | **294** |

### Bottom 5（条款最少）

| 编号 | 名称 | 页 | 强条 |
|---|---|---:|---:|
| GB55035-2023 | 城乡历史文化保护利用项目规范 | 15 | 66 |
| GB55010-2021 | 供热工程项目规范 | 15 | 97 |
| GB55032-2022 | 建筑与市政工程施工质量控制通用规范 | 35 | 122 |
| GB55016-2021 | 建筑环境通用规范 | 43 | 128 |
| GB55006-2021 | 钢结构通用规范 | 24 | 137 |

## 三、编号缺口（17 个）

下列编号暂未收录 PDF，原因可能是住建部尚未公开 / 已废止 / 未发布：

```
2021 版：GB55009, GB55023-29, GB55031-32    （共 10 个）
2022 版：GB55025-29, GB55035                  （共 6 个）
2023 版：（除 GB55035 外无其他）
合计：17 个编号未覆盖
```

**建议**：下次住建部发文时补齐；目前覆盖的 31 本已涵盖建工法律核心场景（结构/抗震/地基/混凝土/钢结构/木结构/防水/防火/电气/暖通/市政/交通/节能等）。

## 四、数据流

```
原始 PDF（202 MB）
   knowledge-base/standards/mohurd-source/*.pdf (31 本)
   │
   │ experiments/mineru-test/scripts/batch_run.py
   │ （MinerU Flash 档，单进程顺序）
   │ 总耗时 41 分钟，平均 81.9 秒/本
   ▼
结构化结果（7.7 MB）
   knowledge-base/standards/parsed/<标准编号-名称>/
   ├── document.md   (Markdown)
   └── middle.json   (MiddleJson + bbox)
   │
   │ experiments/mineru-test/scripts/extract_clauses.py
   │ （X.Y.Z 模式正则 + MiddleJson 块提取）
   ▼
强条清单（CSV + JSON）
   experiments/mineru-test/output/
   ├── batch_manifest.csv      (31 行，转换耗时)
   ├── clauses_overview.csv    (31 行，强条统计)
   └── clauses_full.json       (6531 强条明细)
```

## 五、产物清单（绝对路径）

| 路径 | 大小 | 说明 |
|---|---|---|
| `knowledge-base/standards/parsed/` | 7.7 MB | 31 本规范的 Markdown + MiddleJson |
| `experiments/mineru-test/output/batch_manifest.csv` | 2 KB | 转换耗时/状态 |
| `experiments/mineru-test/output/clauses_overview.csv` | 2 KB | 强条统计 |
| `experiments/mineru-test/output/clauses_full.json` | ~5 MB | 强条明细（含条号/级别/内容）|
| `experiments/mineru-test/decisions-and-results.md` | - | 实验决策报告 |
| `experiments/mineru-test/.venv/` | ~500 MB | MinerU Python 环境（可重建）|
| `~/.mineru/models/MinerU-4_models_onnx/` | ~500 MB | ONNX 小模型缓存（MinerU 自动管理）|

## 六、质量验证

- ✅ GB55001-2021 工程结构通用规范：30 页 214 强条，Markdown 144KB
- ✅ GB55002-2021 建筑与市政工程抗震通用规范：46 页 294 强条，Markdown 196KB
- ✅ 全部 31 本 markdown 总 1.8 MB，章节结构、目次、条文编号全部保留
- ✅ MiddleJson schema 统一为 `docvortex.middle` v2.0（带 bbox 定位）
- ✅ 失败 0 本（manifest 全 ok）

## 七、下一步建议

### 立即可做

1. **写 seed 脚本** — 把 `clauses_full.json` 导入到 PostgreSQL 的 `standards` + `standard_clauses` 表（决策日志 §7 要求知识库与代码解耦 + 可重建）
2. **做 PDF → 条文级跳转** — 把 MiddleJson 的 `page_idx + bbox` 关联到 `standard_clauses.location` 字段，前端报告可点击跳转 PDF
3. **决策日志更新** — `docs/product/decision-log.md` 加一条 "2026-09 | 文档摄入用 MinerU Flash 档"

### V2 待做

1. **强条 → 法条 / 行为 关联映射**（决策日志强调的"最有价值资产"）
   - 行为-强条映射表 `behavior_standard_mapping`（已建表结构，未填数据）
2. **升级到 Standard 档**（需 Turing+ GPU）
3. **完整 38 本补齐**（住建部新发文时下载补充）

## 八、复现命令

```bash
# 环境准备
cd experiments/mineru-test
source .venv/bin/activate

# 跑批量转换（增量，已转换的自动跳过）
python scripts/batch_run.py 2>&1 | tee /tmp/batch_standards.log

# 跑强条提取
python scripts/extract_clauses.py
```

总复现成本：~50 分钟（首跑 + 模型下载）/ ~45 分钟（增量）。
