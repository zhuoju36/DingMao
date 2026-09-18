# 决策日志

> 防止反悔。所有"为什么这样选"在这里记录。AGENTS.md 第五节只列概要。

---

## 格式

```
### YYYY-MM-DD | 决策标题
- **决策**:
- **背景**:
- **备选**:
- **理由**:
- **影响/代价**:
- **回退条件**（如适用）:
```

---

## 决策列表

### 2026-05 | 部署方案：腾讯云轻量 + Docker Compose
- **决策**: 腾讯云轻量应用服务器（2核4G 起步）+ Docker Compose 一键部署
- **背景**: 1 人开发，需要零运维
- **备选**: Vercel + Serverless（不支持长任务）、Railway（海外访问慢）、K8s（过度工程）
- **理由**: 1 人开发零运维；PostgreSQL 自建无额外成本；后期可平滑迁移到独立 TencentDB
- **影响/代价**: 单点故障风险（MVP 阶段可接受）；2核4G 资源紧张需精打细算
- **回退条件**: 用户量 > 500 或日活 > 100 时，迁移到独立 CVM + TencentDB

### 2026-05 | LLM 主力：MiniMax-M3，备用：DeepSeek-V4-Flash
- **决策**: MiniMax-M3 为主力（律师问诊 + 文书起草），DeepSeek-V4-Flash 为备用（高频低延迟任务）
- **背景**: 需要 1M 长上下文 + agentic 能力强 + 中文法律场景；需降本
- **备选**: GPT-4o（成本高）、Qwen-Max（备选兜底）
- **理由**: MiniMax-M3 在长合同理解、tool use 上能力描述匹配；DeepSeek-V4-Flash 激活参数仅 13B，成本极低
- **影响/代价**: **未实测场景表现**，需 W2-W3 实测；如不达预期临时切换
- **回退条件**: 实测 JSON 解析成功率 < 95% 或推理链人工评分 < 80% 时切换

### 2026-05 | 数据库：MVP 阶段自建 PostgreSQL
- **决策**: MVP 用 Docker 自建 PostgreSQL 16，不上独立 TencentDB
- **背景**: 节省成本（TencentDB 约 ¥150-300/月）
- **备选**: TencentDB PG（贵但高可用）、MySQL（用户偏好但 PG 更适合 JSONB 与全文检索）
- **理由**: PG 的 jsonb + tsvector + pg_trgm 对本产品场景更合适；MVP 阶段数据可重建
- **影响/代价**: 单点故障；需自管备份（pg_dump + COS）
- **回退条件**: 用户量增长或对可用性要求提升时迁移 TencentDB PG

### 2026-05 | 前端：Vue 3 + Vite + TS + Element Plus
- **决策**: Vue 3 Composition API + Vite + TypeScript + Element Plus + Pinia + Vue Router
- **背景**: 项目所有者熟悉 Vue 生态
- **备选**: Nuxt 3（有 SSR 但 1 人 MVP 无必要）、React + Ant Design
- **理由**: 项目所有者技术栈偏好；Element Plus 中后台成熟；TS 类型安全
- **影响/代价**: 无
- **回退条件**: 无

### 2026-05 | 不做第三方软件对接
- **决策**: 不与广联达、品茗、新点等工程软件对接
- **背景**: 用户已明确
- **理由**: 保持独立产品边界，降低复杂度；MVP 周期 12 周红线
- **影响/代价**: 用户需手动导入合同/签证单 PDF（已支持）
- **回退条件**: V2 阶段根据用户反馈评估

### 2026-05 | MVP 知识库范围：50 部核心法规 + 38 本通用规范全文强条
- **决策**: MVP 知识库仅入库法规核心 50 部 + 通用规范 38 本全文强条
- **背景**: 用户已明确"几本全文强条的通用规范即可"
- **备选**: 入库所有推荐性标准（量大）、外包给第三方数据服务商
- **理由**: 覆盖 80%+ 工程常见场景；可获取性高（通用规范已全文公开）；工程人员兼职可承担校对
- **影响/代价**: 边缘场景覆盖不全（接受）
- **回退条件**: 内测用户反馈覆盖不足时，扩充专项规范

### 2026-05 | 文书生成：Jinja2 模板引擎 + LLM 润色
- **决策**: 关键字段（数字、时间、条款号、版本号）走模板引擎，LLM 仅负责润色
- **背景**: 核心原则第 2 条（LLM 不生成关键数字）
- **备选**: LLM 端到端生成（不可控）、人工填写（体验差）
- **理由**: 关键数据可追溯；LLM 幻觉风险隔离
- **影响/代价**: 模板维护成本（5 类文书可接受）
- **回退条件**: 无

### 2026-05 | MVP 周期 12 周；角色机制：单一角色 + 视角差异
- **决策**: MVP 12 周交付；用户选一个角色（业主/设计/监理/施工/其他分包），AI 输出视角差异
- **背景**: 用户已明确
- **备选**: 多角色切换（MVP 复杂度过高）、无角色（差异化弱）
- **理由**: 1 人开发节奏；视角差异已能提供差异化价值
- **影响/代价**: 不支持"模拟对方立场"（用户已认可接受此限制）
- **回退条件**: V2 评估

### 2026-05 | 角色机制反转：用户级 → 项目级（**反转上一条决策**）
- **决策**: 角色从用户级单一角色迁移到项目级。`users.role` 重命名为 `users.default_role`（仅作新建项目表单预填），`projects` 新增 `role` 列（必填，LLM 视角依据）。同一用户在不同项目可有不同角色
- **背景**: 实际工作中同一用户在不同项目里身份不同（监理一个项目、施工另一个项目），单一用户角色无法表达
- **备选**: (a) 维持用户单一角色（不解决实际场景）；(b) 引入 `ProjectMember` 多对多表（V3 多人协作再做，本期不做）
- **理由**: 反映实际工作流；保持单用户单项目约束（V3 才上 ProjectMember）；零额外查询开销（JOIN 已有的 projects 行）
- **影响/代价**: 注册流程保留角色采集（现在叫"默认角色"）；新建项目表单必选角色；前端 AppLayout 头部角色徽章改为显示默认角色
- **回退条件**: 若发现 80%+ 用户单一项目单一角色，可考虑重新合并字段（不建议，损失数据）

### 2026-09 | 文档摄入分层：MVP 只做 L1+L2，L3 摘要 V2 启用 + 预留字段
- **决策**: 项目档案只做 L1（原始文件）+ L2（解析后文本）；L3 摘要以 `summary TEXT?` / `extracted_facts JSONB?` 字段在 ProjectDocument 表预留，**MVP 不写入**；V2 启用时再补抽取 pipeline
- **背景**: 决策日志 §6 MVP 边界（12 周红线）+ §应用原则 2（LLM 不参与关键数字）；当前合同审查/变更扯皮已可用 MinerU Flash 档解析（详见 [`docs/architecture/document-ingestion.md`](../architecture/document-ingestion.md)）
- **备选**: (a) MVP 同时做 L3 全文摘要（LLM 调用）；(b) MVP 做 L3 但用 LLM 生成事实卡；(c) MVP 完全不做 L3 也不预留字段
- **理由**: LLM 摘要增加 MVP 复杂度与成本（违反 §6 红线）；规则抽取的 `extracted_facts` 零成本且符合应用原则 2（关键数字不交给 LLM）；预留字段满足原则 7（架构长远眼光），不"先这样以后再换"
- **影响/代价**: V2 启用时需写 alembic migration 加列、抽取 pipeline、Pydantic schema/前端类型；`extracted_facts` 必须可重建（删除后可由 `parsed_content` 重新生成，不依赖容器运行时状态）
- **回退条件**: 无（字段预留是单向可扩展）

### 2026-09 | 用户上传入口：仅项目档案，不进通用知识库
- **决策**: 用户上传文件 → 仅进项目档案（ProjectDocument），通用知识库仍由项目所有者按 [`docs/domain/knowledge-base.md`](../domain/knowledge-base.md) 规范手动维护
- **背景**: 决策日志 §6 MVP 知识库范围锁定（50 部核心法规 + 38 本通用规范全文强条，**其他不入库**）
- **备选**: (a) 用户上传可贡献强条进通用库；(b) 用户上传进 ProjectNote / ProjectClause（V2 设计稿）；(c) MVP 暂不做上传功能
- **理由**: §6 MVP 红线优先；保持通用库权威性（项目所有者逐条校对入库，质量可控）；MVP 期间上传功能延后至 W3-W8 变更扯皮完成后再做（UX 优先级见 [`docs/product/upload-flow.md`](../product/upload-flow.md) §十）
- **影响/代价**: 用户上传无法贡献通用库；通用库扩展依赖项目所有者手动入库
- **回退条件**: V2 评估"用户贡献强条"功能（需先扩展 §6 边界）

### 2026-09 | System Prompt 解耦：代码默认 + 文件覆盖（jinja2）
- **决策**: PromptStore 三层架构（DB V2+ > 文件 MVP > 代码默认 MVP），用 jinja2 渲染占位符；详见 [`docs/product/w3-w8-llm-prompts.md`](../product/w3-w8-llm-prompts.md) §十
- **背景**: 运维需要 A/B test、调措辞、加公司免责声明；AGENTS.md 原则 7（架构长远）+ `conventions.md` 第 14 行（常量集中管理）
- **备选**: (a) 全 `.env`（KV 不适合多行）；(b) 只文件覆盖（部署需拷全套默认）；(c) 数据库（V2 过重）
- **理由**: 业内共识（LangChain Hub、Anthropic Prompt Library）；代码默认保证开箱可用；文件覆盖给运维自由度；jinja2 项目已有依赖（`pyproject.toml` 第 32 行 `jinja2>=3.1.4`）；`undefined=StrictUndefined` 防静默错误
- **影响/代价**: `app/core/prompts.py` 新增；`chat.py` 改造调 `prompt_store.render()`；新增 4 个 YAML 文件；与现有 `app/core/constants.py` 并列
- **回退条件**: 无（向后兼容，未设 `PROMPT_DIR` 时与原 prompt 等价）

### 2026-09 | 三源证据填充：EvidenceLinker 自动挂载 version + effective_date
- **决策**: LLM 只填 (code, article_no/clause_no)；version / effective_date / is_mandatory 由 EvidenceLinker 从 DB 匹配填充；详见 [`docs/product/w3-w8-triple-evidence.md`](../product/w3-w8-triple-evidence.md)
- **背景**: 应用原则 1（数据确凿：三源证据必填）+ 应用原则 2（LLM 不生成关键数字）+ 应用原则 3（引用必须有版本号 + 生效日期）；现状 `stream_report` 写 `law_refs=[]` `standard_refs=[]` 永远空数组
- **备选**: (a) LLM 直接填 version（违反应用原则 2）；(b) 手动让用户填（体验差）；(c) 不填 version（违反应用原则 3）
- **理由**: EvidenceLinker 纯函数可重建（决策日志 §7 知识库与代码解耦）；防 LLM 幻觉（编造 code/条款号）；匹配快（<50ms）；`Law` 表补 `version` 字段（参考 `Standard.version` 已有先例）
- **影响/代价**: `Law.version` 加列 + 回填已知法律版本；`search_laws` / `search_standards` 补返回字段；`app/services/evidence_linker.py` 新建；Alembic migration 一条
- **回退条件**: 无（向后兼容，老数据 `law_refs=[]` 仍可写）

#### 2026-09 修订注记（P0 修复后）

subagent 独立审阅发现初始设计有 3 个红线违反 / silent failure，已在 [`w3-w8-triple-evidence.md`](../product/w3-w8-triple-evidence.md) 修复：

| # | 修复 | 修复前 | 修复后 |
|---|---|---|---|
| P0-1 | `Law` 加 `aliases JSONB`；匹配改 aliases + name + code 三级遍历 + article_no 汉字↔阿拉伯归一化 | `hit["law_code"] == raw.get("code")` 字符串相等（LLM 输出"中华人民共和国民法典"与 DB 存"民法典"失配）→ silent failure | 三级匹配 + 归一化层，挂载率恢复 ≥95% |
| P0-2 | `_validate_risk` 改 raise `EvidenceValidationError` | `missing_law_version` 仅返回 warning（软警告，违反应用原则 3 红线） | 直接 raise 硬错误，由上层决定重试/降级 |
| P0-3 | `Law.version` 在知识库导入脚本入库（`knowledge-base/scripts/import_laws.py`），alembic migration 只加 nullable 列 | migration 硬编码 `op.execute("UPDATE laws SET version = '2020' WHERE code = '民法典'")` 等 50 行 SQL | migration 只 `op.add_column`；version + aliases 跟法条一同导入（参考 `Standard.version` 已有做法）|

### 2026-09 | 5 类文书：Jinja2 模板 + 哨兵 token 校验 + 并行
- **决策**: 变更扯皮场景 5 类文书（签证单 / 索赔报告 / 监理通知单 / 工作联系单 / 审查意见备忘录）统一采用以下方案：
  1. **Jinja2 模板渲染**结构化字段（项目名称 / 当事人 / 金额 / 时间 / 条款号等）
  2. **LLM 仅做措辞润色**（应用原则 2：关键数字不交给 LLM）
  3. **哨兵 token 校验**保证结构化字段 100% 保留：渲染时用不可见 token 替换结构化值 → LLM 润色 → 反向恢复（结构性保证，LLM 看不到原值）
  4. **免责声明固定在文书顶部 + 底部双显**（应用原则 4：律师复核提示放在显眼位置）
  5. **5 类文书 `asyncio.gather` 并行生成**（25s → 5-8s）
- 详见 [`docs/product/w3-w8-artifacts.md`](../product/w3-w8-artifacts.md)
- **背景**: 决策日志 §7（"Jinja2 模板引擎 + LLM 润色，关键数字不交给 LLM"）+ 应用原则 2（LLM 不生成关键数字）+ 应用原则 4（文书前免责声明）；W3-W8 收官决策
- **备选**:
  - (a) LLM 端到端生成（违反应用原则 2，幻觉风险）
  - (b) 模板渲染不润色（文书表达僵硬）
  - (c) 润色后正则校验结构化字段（正则无法区分"合同金额 100 万"语义数字 vs "第 8 条"叙事数字）
- **理由**:
  - 决策日志 §7 已锁定方向
  - 哨兵 token 是结构性保证（subagent 审阅建议），比正则可靠
  - 顶部 + 底部双显是应用原则 4 硬要求（原设计违反，subagent 审阅发现）
  - 并行：LLM 润色是 I/O 密集型，串行浪费
- **影响/代价**:
  - `backend/app/services/artifact_renderer.py` 新建（哨兵 token 机制）
  - `backend/app/templates/artifacts/*.j2` 5 个模板
  - `backend/app/services/consultation_engine.py` `generate_artifacts` 并行编排
  - `frontend/package.json` 加 `markdown-it` 依赖
  - `backend/app/core/constants.py` 加 `EvidenceType` 枚举
- **回退条件**: 哨兵 token 实测破坏率 > 5%（按应用原则 2 红线绝不妥协）

### 2026-09 | PromptStore 拆 V1/V2（subagent 审阅建议简化）
- **决策**: PromptStore 拆两阶段落地，详见 [`docs/product/w3-w8-llm-prompts.md`](../product/w3-w8-llm-prompts.md) §十
  - **V1（MVP）**: 只交付 `DEFAULT_PROMPTS dict + render()` 接口（无文件层、无 DB 层）
  - **V2（未来）**: 加 YAML 文件覆盖层（`PROMPT_DIR` 环境变量）+ DB 覆盖层（V2+ A/B test）
- **背景**: 上一条"System Prompt 解耦"决策原设计是三层架构（DB V2+ > 文件 MVP > 代码默认 MVP），但 subagent 独立审阅指出 MVP 阶段三层是过度设计，违反 AGENTS.md 原则 2「最简单实现」
- **备选**:
  - (a) 一次性建完整三层（被否，MVP 过重）
  - (b) 完全不用 PromptStore，V1 直接 `dict.get`（V2 再说）
- **理由**: 决策日志 §2026-09 "Prompt 解耦"已预留 V2 升级路径，V1 简化不影响未来扩展——`PromptStore` 类内部升级时调用方 `prompt_store.render(key, **vars)` 接口不变
- **影响/代价**: `app/core/prompts.py` V1 只 30 行（单层）；V2 升级时改 `__init__` 参数即可
- **回退条件**: V1 落地后实际运营发现需要 A/B 测试，再升级 V2

### 2026-09 | 问诊 UI：两栏 + 分段控件（不是聊天工具）
- **决策**: 问诊页改为左栏 380px「采集进度」+ 右栏分段控件 `[对话][结论][文书]`，详见 [`docs/product/consultation-ui.md`](../product/consultation-ui.md)
- **背景**: 现状是单栏上下堆叠的聊天界面（聊天 `flex:1` + 报告 `45vh`），但产品定义是「结构化多轮事实采集，**禁止自由提问**」——界面主角应是「待查事项清单」的完成度，对话只是手段。现状把关系倒置了：90% 屏幕给聊天气泡，事实只剩一个数字徽章；三依据（🟦🟨🟥）字段 API 全返回但模板一个都没渲染
- **备选**:
  - (a) 单栏纵向 + 粘性锚点导航（否决：报告 4 条结论很长，滚动距离大）
  - (b) 三栏 事实|对话|结论（否决：1440px 笔记本上每栏只剩 ~400px，正文没法读）
  - (c) 保持聊天气泡 + 侧边抽屉放事实（否决：清单不常驻，回答追问时看不见还差什么）
- **理由**: 与 `ProjectDocumentsTab` 同一套栅格（已验证可用）；左栏恒定保证"我提供了什么/还差什么"永远可见；分段控件比锚点可预测
- **影响/代价**: `frontend/src/views/Consultation.vue` 重写；新建 `ConsultationFactsPanel.vue`；后端需先补 6 个缺口（见下条）
- **回退条件**: 实测用户主要在右栏工作、从不看左栏 → 退回单栏 + 抽屉

### 2026-09 | 证据引用改「检索优先」，不让 LLM 写条款号
- **决策**: 后端先检索 `laws`/`law_articles`/`standard_clauses`，把候选编号为 `[L1]`/`[S1]` 注入 prompt，LLM **只输出标签**，后端按标签回映射真实 DB 行取 `version`/`effective_date`。偏离 `w3-w8-triple-evidence.md` §3.2 原设计
- **背景**: 原设计是 LLM 输出 `{code, article_no}` → `EvidenceLinker` 模糊匹配 DB 补版本号。落地时发现 `stream_report` 里 `law_refs=[]`/`standard_refs=[]` 是硬编码空数组，且 `search_standards` 从不被问诊调用——🟥 依据链从生成那一刻就断了
- **备选**:
  - (a) 维持原设计，实现 `EvidenceLinker` 模糊匹配（否决：需汉字/阿拉伯数字归一 + 未验证的 `_cn_to_int`，是"先生成再纠错"）
  - (b) 只修硬编码 bug，不引入检索（否决：LLM 仍会编条款号）
- **理由**: 应用原则 2「LLM 不参与关键数字生成」——条款号就是关键数字。检索优先让 LLM **没有机会**写出条款号；应用原则 3 自动满足（版本号直接来自 DB）。消掉一整块模糊匹配的不确定性
- **影响/代价**: 新建 `evidence_linker.py`；候选召回不足时降级为 `no_candidate_basis` warning + `reasoning_chain` 说明"无明确依据"
- **回退条件**: 实测候选召回率 < 60%（LLM 无从选择）→ 补混合检索（关键词 + 向量）

### 2026-09 | 三源证据缺失的降级：引用级硬、结论级软
- **决策**: 单条引用缺 `version`/`effective_date` → **丢弃该引用**；结论缺 `fact_refs` → **保留结论** + warning；warnings 写 `consultations.state_data` JSONB；`failed` 进 `ConsultationStep`/`ConsultationStatus` 枚举
- **背景**: `w3-w8-triple-evidence.md` 内部三处互斥表述——§4.3 标"绝不写入 DB"硬抛错，§4.1/§4.2/§9.1 说软 warning 不阻塞，§4.3 尾部还残留与 `-> None` 签名矛盾的死代码；另 `system_warning` 字段归属未定（第 1 轮明确说 `Consultation` 表不加字段），迁移表 #8/#10 引用了枚举里不存在的 `failed`
- **备选**:
  - (a) 整条 `raise EvidenceValidationError`（否决：一次 LLM 漏填毁掉 20 秒生成过程，违反"先跑通最小端到端"）
  - (b) 全部软 warning 静默通过（否决：应用原则 3 是红线）
  - (c) 新增 `system_warning` 列（否决：第 1 轮已明确不加字段，且 `state_data` 空着就是为这类状态预留）
- **理由**: 应用原则 1 原文是"**无依据不升格结论**"，不是"无依据不出结论"——惩罚应落在引用上，不落在结论上；应用原则 3 是真红线，缺版本号的引用必须丢掉
- **影响/代价**: `consultations.state_data` 启用（原完全未使用）；`ConsultationStep`/`ConsultationStatus` 各加 `FAILED`
- **回退条件**: 实测降级结论占比 > 30% → 说明知识库覆盖不足，优先补知识库而非收紧校验

### 2026-09 | 通用规范知识库：MinerU Flash 档 + OCR 校对 + 抽取器重写 + 入库
- **决策**: 31 本国标通用规范 GB 55000 系列采用以下链路：
  1. **MinerU Flash 档 PDF 解析**（GTX 1080 Pascal 唯一可行档位，Standard 档需 Turing+ GPU；详见 `experiments/mineru-test/decisions-and-results.md`）
  2. **OCR 校对脚本** `experiments/mineru-test/scripts/fix_ocr.py`：剥离行末页码/页眉噪声、补缺空格、合并跨行断条款、补漏冒号、剥离 base64 内嵌图片
  3. **抽取器重写** `extract_clauses.py`：严格 X.Y.Z 模式、跳过 Markdown 围栏代码块、跳过表/图/注/附录标题、列表项合并到父条 content
  4. **PG 入库脚本** `backend/scripts/import_standards.py`：幂等 upsert 31 本标准 + 3750 条强条（实施日期硬编码映射，关键词朴素 TF 提取）
- **背景**: 决策日志 §6（"MVP 知识库：50 部核心法规 + 38 本通用规范全文强条"）+ 应用原则 7（"知识库与代码解耦，可重建"）+ W3-W8 完成的应用原则 1-3（三源证据必须 version + effective_date）
- **抽取前后对比**：
  | 指标 | 旧抽取器 | 新抽取器 |
  |---|---:|---:|
  | 条款总数 | 7599 | **3752** |
  | 真 X.Y.Z | 3631 (47.8%) | **3752 (100%)** |
  | 单数字误抓 | 3944 (51.9%) | **0** |
  | 表内数据被当条款 | 大量 | **0** |
- **备选**:
  - (a) 跳过 OCR 校对直接入库（否决：3750 条中混入 50% 噪声污染数据库）
  - (b) LLM 抽取强条（否决：违反应用原则 2「LLM 不生成关键数字」+ 幻觉风险）
  - (c) 不入库（保留 `clauses_full.json` 文件）：否决：违反决策日志 §7「应用层加载，启动时导入数据库」
- **理由**:
  - 抽取器正则化是结构性修复（不是润色），0 副作用
  - 应用原则 7 要求知识库可重建，PG 入库是知识库与代码解耦的最后一公里
  - base64 剥离让 GB55011 markdown 从 712KB → 41KB（-94%），节省存储且不影响条款文字
- **影响/代价**:
  - 新增 `fix_ocr.py` (8KB)、`import_standards.py` (7KB)
  - 新增 alembic migration `c3d4e5f6a7b8`：UNIQUE(standard_id, clause_no)
  - `StandardClause` model 加 `__table_args__`
  - `seed_knowledge.py` 删 demo GB 55008-2022 / 4.1.1 捏造条文（决策日志要求"数据确凿优先"，demo 条文违反应用原则 1）
- **回退条件**: 抽取器修改导致召回率下降 → 保留旧 `extract_clauses.py` 到 `extract_clauses_v1.py` 可对照

### 2026-09 | behavior_standard_mappings 0 条：人工开工
- **决策**: `behavior_standard_mappings` 表保留空表，MVP 期间由项目所有者按行为-强条清单人工标注 5-10 个高频行为（`concealed_work_no_acceptance` 等），每条行为关联 1+ 强条 + 法条 + 风险等级
- **背景**: 决策日志 §6 标注这是"最有价值的资产"，必须人工主导 + AI 辅助校验；MVP 自动化 AI 配对的准确率不足以承担法律责任
- **备选**:
  - (a) 用 keywords + 全文检索自动配对（否决：违背"人工主导"原则，MVP 阶段准确率 < 60%）
  - (b) 不入库，等 V2（否决：决策日志 §6 明确 MVP 必须有）
- **理由**: 应用原则 1（"数据确凿优先，无依据不升格结论"）要求行为-强条映射必须有可追溯来源；LLM 自动配对无法保证这一点
- **影响/代价**: 项目所有者前 2 周投入 ≥10 小时人工标注；这是 MVP 阶段最耗时但 ROI 最高的工作
- **回退条件**: 内测用户实测行为抽取准确率 < 70% → 收紧映射规则而非扩展自动化

### 2026-09 | GB 55009 / 55025-55029 暂缺：6 个编号未覆盖
- **决策**: 31 本入库，6 个编号（GB55009、GB55025、GB55026、GB55027、GB55028、GB55029）暂缺；不阻塞 MVP，下次住建部新发文时补齐
- **背景**: 决策日志 §6「其他不入库」原则 + 6 个编号中部分可能住建部官网尚未公开（如 GB55009 状态待核查）
- **备选**:
  - (a) 阻塞 MVP 等全部 38 本齐全（否决：违反 §6 MVP 12 周红线）
  - (b) 用推荐性国标/行业标准补齐（否决：违反 §6「推荐性国标不入库」）
- **理由**: 31 本覆盖建工法律核心场景（结构/抗震/地基/混凝土/钢结构/木结构/防水/防火/电气/暖通/市政/交通/节能等），MVP 阶段足够；其余 6 个是边缘场景
- **影响/代价**: 部分罕见场景（如安全防范工程 GB55029）覆盖不全
- **回退条件**: 内测用户反馈覆盖不足时，扩展专项规范

### 2026-09 | 行为-强条映射：LLM 半自动生成 + 人工审查
- **决策**: `behavior_standard_mappings` 不走纯人工标注，采用**「LLM 半自动 + 人工审查」** 流水线：
  1. **锁定 25 个高频行为清单**（`backend/scripts/behavior_taxonomy.py`）—— 防止 LLM 自由发明导致 key 碎片化
  2. **LLM 批量生成候选**（`scripts/generate_behavior_mappings.py`）—— 对每条强条调 LLM，让它从 25 个候选里挑（confidence high/medium），输出 reason + 风险等级 + 法律后果
  3. **人工 CLI 审查**（`scripts/review_mappings.py`）—— `list / review / verify / delete / stats`，每周 10-20 条
  4. **Verified 区分权威等级**——`verified=true` 作为应用层权威依据；`verified=false` 作为 V2 向量召回池
- **背景**: 用户问"全人工标注太累，能否 LLM 先过一轮？"→ 本决策
- **质量实测**（200 条样本，4 个 prompt 版本迭代）:
  | Prompt | 插入数 | 质量评估 |
  |---|---:|---|
  | v1（宽松）| 48 | ~42% 准确（false positive 较多）|
  | v2（极严）| 3 | ~100% 准确但召回极低 |
  | v3（严格 medium）| 10 | ~80% 准确 |
  | **v4（召回优先）** | **77** | ~20-30% 准确，召回较高 |
- **MVP 决策**: 采用 v4。LLM 负责"扫描 3750 条找出明显该挂的强条"，人类审查负责"剔除误挂"。**这是策略本质 —— 不是 LLM 准，是 LLM 召回 + 人工过滤**
- **备选**:
  - (a) 纯人工标注 5-10 个高频行为 × 30 分钟 = 5 小时起（否决：长尾覆盖不到）
  - (b) 纯 LLM 标注 + 直接用（否决：责任不清，律师不敢信）
  - (c) 等 V2 加向量检索再开工（否决：决策日志 §6 标 MVP 必须有）
- **理由**: 审查比标注便宜 3-6 倍；LLM 把"理解强条含义 + 匹配行为"做了，人工只做"是/否/改"
- **影响/代价**:
  - 新增 3 个脚本（`behavior_taxonomy.py` 25 行为定义 + `generate_behavior_mappings.py` LLM 生成 + `review_mappings.py` CLI 审查）
  - 200 条样本演示验证：1 个高质量 mapping（GB 55002-2021 5.2.5 钢筋替代换算）经人工 verify 2 条 + delete 1 条
  - 跑全量 3750 条预计 1.5-2 小时，成本 ¥30-50
- **回退条件**: LLM 误挂率 > 80% 持续 1 周 → 收紧 prompt + 重新审视 25 行为清单本身是否合理
### 2026-09 | 法律元数据从国家法律法规数据库补齐（不用条文正文推导）
- **决策**: `laws.version` ← `gbrq`、`effective_date` ← `sxrq`、`issuing_org` ← `zdjgName`，取自国家法律法规数据库 <https://flk.npc.gov.cn>；脚本 `backend/scripts/sync_law_metadata.py`，产出报告 `knowledge-base/LAW_METADATA_REPORT.md`。实测补齐 **176/177**
- **背景**: `laws.version` 177 部全为 NULL，`evidence_linker` 按应用原则 3 丢弃所有缺版本号的引用 → 🟨 依据恒为空。源数据集 `dengcao/Chinese-Laws` 是纯条文 .txt，不含任何元数据字段
- **备选**:
  - (a) **从条文末条推导**「本法自YYYY年M月D日起施行」（166/177 可解析）——**否决**：那是**原始**施行日期，而数据集正文已是修订后版本。实测建筑法第四十八条是 2011 修正后文本，末条却写 1998-03-01；直接采用会生成「《建筑法》第X条（1998-03-01 施行）」而用户读的是 2019 修正版，正是原则 3 要防的误导
  - (b) 保持 NULL，🟨 继续为空——否决：产品的核心卖点就是三依据
  - (c) 用 LLM 推断版本号——否决：违反应用原则 2
- **理由**: 官方权威一手来源；取的是法条自身的公布/施行日期，不是推测；脚本幂等可重建（应用原则 7）
- **影响/代价**: 新增 1 个脚本 + 1 份报告；无新增依赖（httpx 已有）；`laws` 三字段从 0/1/1 变为 176/176/176
- **坑（已写入脚本注释）**: ①公开的第三方接口文档称「sxx=3 为有效」是错的，实测按它过滤会漏掉 11 部现行有效的环境类法律（环境保护法、大气污染防治法现行版均为 sxx=1）；改用「排除 sxrq 晚于今天 + 取 gbrq 最新」。②必须排除尚未生效版本，否则商标法（gbrq 2026-06-26 / sxrq 2027-01-01）会给 2019 版文本盖上 2026 版本号
- **回退条件**: 权威库接口变更或大面积取不到值时，退回「仅对有把握的法律填值，其余留 NULL」

### 2026-09 | 检索排序改 IDF 加权 + 受控词表查询扩展
- **决策**: `evidence_linker` 的排序由「重叠度计数」改为 **IDF 加权打分**；新增 `expand_search_terms()`——LLM 从**受控词表内选词**做查询扩展（不许自造词）
- **背景**: 补齐法条元数据后 🟨 仍为空。排查发现三层问题：①中文 ILIKE 无词边界，`工期` 命中「动**工期**限」、`索赔` 命中《民用航空法》《旅游法》；②案情口语（"索赔""工期顺延"）与法条法言法语（"赔偿损失""顺延工程日期"）对不上，主场景召回 **0 条**；③纯计数分辨率太低，《民法典》807（催告付款，该争议核心条款）与 788/798/803/800 同为 overlap=4，靠长度破平被挤到第 7 位
- **备选**:
  - (a) 扩大锚点词硬门控——**否决**：会把《民法典》合同编总则里「合同变更须协商一致」「书面形式」的条文全挡掉，而"口头指令变更"这类程序争议恰恰靠总则，导致该场景 🟨 恒为空（实测）
  - (b) 上向量检索/tsvector——否决：MVP 阶段过重，且 `tsv` 列全空、无中文分词扩展
  - (c) 让 LLM 自由生成检索词——否决：会产出「工程变更」这类法条原文里查不到的词（原文写「工程范围」「变更」），检索必然落空。故改为**只能从词表里选**
- **理由**: IDF 是经典 IR 做法，零新依赖；受控词表保证扩展词一定能查到；应用原则 2 不受影响（LLM 只选检索词，条款号仍由 DB 提供）
- **影响/代价**: 每个报告生成多一次 LLM 调用（约 4s）；`evidence_linker` 新增 `extra_terms` 参数
- **坑**: IDF 子查询最初让检索 2s → **39s**（PostgreSQL 12+ 默认内联 CTE，全表计数被每个候选行重算），加 `AS MATERIALIZED` 后回到 ~1s
- **回退条件**: 查询扩展的 LLM 调用失败率 > 10% 或延迟不可接受 → 退回纯案情用词（召回降但可用，已实现降级返回空列表）
