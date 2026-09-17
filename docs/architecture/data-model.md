# 数据模型

> 项目所有 DBL（业务实体）的设计说明。AGENTS.md 第三节只列概要，**所有字段细节在这里**。

---

## 一、设计原则

1. **通用 vs 项目隔离**：通用知识库（laws / standards）全局只读，项目特有知识（project_notes / project_clauses）按 `project_id` 隔离
2. **LLM 上下文检索**：每次问诊 = 通用知识检索 + 项目特有知识检索，合并送 LLM
3. **结论可追溯**：所有结论（🔴🟡🟢）必须挂 🟦事实 + 🟨法条 + 🟥强条 + 项目上下文
4. **MVP 优先**：先通用层做透（W1-W4），项目特有知识 V2 引入

---

## 二、模型清单

```
app/models/
├── base.py             # Base + TimestampMixin + 异步会话
├── user.py             # User（全系统唯一）
├── project.py          # Project + ProjectMember（V2）
├── document.py         # ProjectDocument（项目归档文件）
├── consultation.py     # Consultation + Message + Fact + Conclusion + Artifact
├── knowledge.py        # 通用层：Law / LawArticle / Standard / StandardClause / BehaviorStandardMapping
└── project_note.py     # 项目层（V2）：ProjectNote / ProjectClause
```

---

## 三、User（用户）

### 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| email | str(255) | 唯一、登录标识 |
| hashed_password | str(255) | bcrypt 哈希 |
| full_name | str(100)? | 真实姓名 |
| role | str(32) | UserRole 枚举（owner / designer / supervisor / contractor / subcontractor） |
| is_active | bool | 启用标志 |
| is_verified | bool | 邮箱已验证（MVP 跳过验证） |

### 关系

- 一对多 → Project（创建的项目）
- 一对多 → Consultation（发起的问诊）

### 设计要点

- 角色 MVP 单一角色，全局唯一，**不做角色切换**（已在 decision-log 中决策）
- 不存敏感字段明文
- 邮箱唯一约束在 DB 层

---

## 四、Project（项目档案）

### 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| owner_id | int FK(User) | 创建人 |
| name | str(200) | 项目名称 |
| code | str(64)? | 工程编号（如 PRJ-2026-001） |
| description | text? | 项目描述 |
| location | str(200)? | 工程地点 |
| contract_amount | Numeric(18,2)? | 合同金额 |
| contract_start_date | date? | 开工日期 |
| contract_end_date | date? | 竣工日期 |
| contract_duration_days | int? | 工期天数 |
| owner_org | str(200)? | 建设单位 |
| design_org | str(200)? | 设计单位 |
| supervisor_org | str(200)? | 监理单位 |
| contractor_org | str(200)? | 施工单位 |
| contract_clauses | JSONB? | W1 临时存放 contract_text，V2 改为独立 ProjectClause 表 |

### 关系

- 多对一 → User（owner）
- 一对多 → ProjectDocument
- 一对多 → Consultation

### 设计要点

- 单用户单项目约束（按 user_id 隔离）
- 删除时级联删除 documents / consultations

---

## 五、ProjectDocument（项目归档文件）

> V1 仅占位（数据模型已建，**W1 暂不实现文件上传**）。所有信息通过用户输入文本 + 知识库检索获得。

### 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| project_id | int FK(Project) | |
| uploader_id | int FK(User) | |
| document_type | str(32) | DocumentType 枚举：contract / bidding / variation / correspondence / inspection / evidence |
| title | str(300) | 文档标题 |
| file_name | str(255) | 原始文件名 |
| file_size | bigint | 文件大小 |
| mime_type | str(100) | MIME |
| storage_path | str(500) | COS 路径 / 本地路径 |
| storage_provider | str(20) | cos / local |
| parsed_content | JSONB? | 解析结果 |
| parse_status | str(20) | pending / success / failed |
| parse_error | str(1000)? | 解析错误信息 |
| document_date | datetime? | 文档日期 |
| parties | JSONB? | 涉及的相关方 |

### 关系

- 多对一 → Project

---

## 六、Consultation（问诊会话）

### 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| project_id | int FK(Project) | |
| user_id | int FK(User) | |
| scenario | str(32) | ConsultationScenario：contract_review / variation |
| status | str(20) | ConsultationStatus：in_progress / completed / abandoned |
| dispute_summary_user | text? | 用户原话描述 |
| dispute_summary_ai | text? | AI 提炼的争议摘要 |
| current_step | str(50) | 状态机节点（init / awaiting_text / generating / done） |
| state_data | JSONB | 状态机过渡数据 |

### 关系

- 一对多 → ConsultationMessage
- 一对多 → ConsultationFact
- 一对多 → ConsultationConclusion
- 一对多 → ConsultationArtifact

---

## 七、ConsultationMessage / Fact / Conclusion / Artifact

### ConsultationMessage（问诊对话消息）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| consultation_id | int FK | |
| role | str(20) | user / assistant / system |
| content | text | 消息内容 |
| metadata_json | JSONB? | 附加信息（事实卡片、强条提示等） |
| step_at_time | str(50)? | 当时状态机节点 |

### ConsultationFact（事实卡片）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| consultation_id | int FK | |
| fact_key | str(100) | 事实键名（如 contract_text） |
| fact_label | str(200) | 人类可读标签 |
| fact_value | text | 事实值 |
| fact_value_type | str(20) | text / number / date / enum / json |
| source_message_id | int? FK(Message) | 来源消息 |
| source_type | str(20) | user_input / ai_extracted |
| confidence | float | 1.0 = 用户直接输入；<1.0 = AI 推断 |

### ConsultationConclusion（问诊结论）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| consultation_id | int FK | |
| level | str(10) | red / yellow / green |
| title | str(300) | 结论标题 |
| content | text | 结论正文 |
| fact_refs | int[] (JSONB) | 关联 fact id 列表 🟦 |
| law_refs | JSONB | 🟨 `{code, article, version, effective_date}` |
| standard_refs | JSONB | 🟥 `{code, clause, version, is_mandatory}` |
| reasoning_chain | text? | 推理过程 |
| counter_arguments | text? | 反例/例外 |

### ConsultationArtifact（问诊产出物）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| consultation_id | int FK | |
| artifact_type | str(32) | variation_order / claim_report / supervisor_notice / correspondence / review_memo |
| title | str(300) | 文书标题 |
| content | text | 渲染后内容 |
| template_name | str(100) | Jinja2 模板名 |
| template_data | JSONB | 填充字段 |
| file_path | str(500)? | 生成的文件路径 |

---

## 八、通用知识库层

### Law（法律）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| code | str(64) | 唯一，如"民法典" |
| name | str(300) | 完整名称 |
| category | str(32) | civil / construction / bidding / safety / administrative |
| issuing_org | str(200)? | 颁布机关 |
| effective_date | str(10)? | YYYY-MM-DD |
| status | str(20) | active / replaced / abolished |
| replaced_by | str(64)? | 替代法编号 |

### LawArticle（法条）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| law_id | int FK(Law) | |
| article_no | str(20) | "第五百七十七条" |
| content | text | 条文全文 |
| paragraph | int | 第几款（默认 1） |
| item | str(20)? | 第几项（如"（一）"） |
| keywords | str[] | 关键词数组 |
| tsv | TSVECTOR? | PG 全文索引 |

### Standard（国家强制性标准）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| code | str(64) | 唯一，如"GB 55008-2021" |
| name | str(300) | |
| category | str(32) | concrete / steel / foundation / fire ... |
| version | str(20) | 出版年份 |
| effective_date | str(10)? | |
| status | str(20) | active / replaced |

### StandardClause（强条 / 标准条款）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| standard_id | int FK | |
| clause_no | str(20) | "4.1.1" |
| content | text | |
| is_mandatory | bool | true = 强条 |
| behavior_tags | str[] | 行为标签（"隐蔽工程"等） |
| keywords | str[] | |
| tsv | TSVECTOR? | |

### BehaviorStandardMapping（行为-强条映射）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| behavior_key | str(100) | 行为键 |
| behavior_description | text | 行为描述 |
| behavior_keywords | str[] | |
| clause_id | int FK(StandardClause) | 触发的强条 |
| related_article_id | int? FK(LawArticle) | 关联法条 |
| risk_level | str(10) | yellow / red |
| legal_consequence | text? | 法律后果 |
| annotated_by | str(50) | human / ai |
| verified | bool | 是否已校验 |

---

## 九、项目特有知识层（V2 — 仅设计，不实现）

> 用户决定"先只设计数据模型"，这部分是设计稿，**代码等 V2 再写**。

### 设计动机

通用法律 AI 给出的是**通识答案**。要让我们的产品差异化，必须叠加**本项目上下文**：
- 本项目合同的具体条款
- 本项目历次签证/索赔记录
- 用户主动补充的项目背景、业主偏好、关键人物

### ProjectNote（项目笔记 / 补充说明）

> 用户主动输入的项目特有上下文，由用户写，不是 LLM 自动生成。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| project_id | int FK(Project) | |
| title | str(200) | 笔记标题（如"业主付款节奏偏慢"） |
| content | text | 笔记正文 |
| note_type | str(32) | context / preference / risk_alert / key_person / special_term |
| priority | str(10) | high / medium / low（影响 LLM 检索权重） |
| source | str(20) | user_input（V2）/ ai_extracted（未来） |
| is_active | bool | 启用标志（可"折叠"已过期笔记） |

**note_type 详细**：
- `context`：项目背景（如"业主关系紧张"）
- `preference`：用户偏好（如"监理视角看问题"）
- `risk_alert`：风险提醒（如"业主最近频繁拖欠"）
- `key_person`：关键人物（如"项目经理张三只认现场签证"）
- `special_term`：专业术语/约定（如"该项目按月进度付款")

### ProjectClause（项目合同条款）

> 本项目合同的**结构化条款**（每条一行），方便 LLM 按条号精确引用。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | PK |
| project_id | int FK(Project) | |
| contract_type | str(32) | main_contract / subcontract / supplement / addendum |
| contract_ref | str(64)? | 合同编号（如 HT-2026-001） |
| clause_ref | str(20) | 条号（如"第 8.2 条"） |
| title | str(300)? | 条款标题 |
| content | text | 条款内容 |
| risk_level | str(10) | red / yellow / green（用户/AI 标注） |
| risk_reason | text? | 风险原因（如"逾期违约金超 30%"） |
| source | str(20) | user_input（手动录入）/ consultation_extracted（从问诊自动抽取） |
| source_consultation_id | int? FK(Consultation) | 来源问诊（自动抽取时记录） |

### ProjectEvent（项目事件记录 — 未来扩展）

> 本项目关键事件的时间线（设计阶段，未进这里）：
> - 历次签证单、索赔报告
> - 重大设计变更
> - 质量事故、安全事故
> - 关键节点（开工、封顶、竣工）

V2 之后单独设计。

---

## 十、问诊时的检索逻辑（V2）

```
LLM 上下文 = 通用知识 + 项目特有知识

┌─ 通用知识（全局表）
│   ├─ laws：法条全文检索
│   ├─ standards：强条全文检索
│   └─ behaviors：行为-强条映射
│
└─ 项目特有知识（按 project_id 过滤）
    ├─ project_notes：项目笔记（按 note_type + priority）
    └─ project_clauses：本项目合同条款（按 clause_ref / keywords）

合并后送 LLM（含完整 prompt + 角色视角）
```

**关键约束**：
- 所有检索都要按 `user_id` / `project_id` 隔离（多租户安全）
- 三源证据链强制：任何结论必须挂 🟦 + 🟨 + 🟥 + 项目上下文

---

## 十一、已实现 vs 待实现

| 模块 | W1 已实现 | W2 计划 | V2 计划 |
|---|---|---|---|
| User / Project / Consultation / Fact / Conclusion / Artifact | ✅ | | |
| Law / LawArticle / Standard / StandardClause / BehaviorStandardMapping | ✅ 表结构<br>已下载 31 本 PDF | 待入库数据 | |
| ProjectDocument | ✅ 表结构 | | |
| ProjectNote | 仅设计 | | V2 实现 |
| ProjectClause | 仅设计 | | V2 实现 |
| 检索逻辑（混合通用 + 项目） | | | V2 实现 |

---

## 十二、未来扩展

- **多项目对比**：跨项目分析（如"A 项目的合同条款 vs B 项目同条款"）
- **项目模板**：常用项目类型（住宅、市政、装饰）预置条款知识
- **多用户协作**：项目组成律师 + 监理 + 设计，多视角评论
- **项目间引用**：监理报告引用项目 A 的历史经验
- **时序分析**：项目事件时间线 + LLM 推理

以上均 V2+，当前文档仅记录 MVP + V2 设计。

---

## 十三、变更记录

| 日期 | 变更 |
|---|---|
| 2026-05 | 初版（W1 阶段） |
| 2026-05 | 新增"项目特有知识层"V2 设计（ProjectNote / ProjectClause） |