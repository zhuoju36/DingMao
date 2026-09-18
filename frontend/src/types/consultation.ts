// Consultation 类型 — 与后端 schemas/consultation.py 1:1 对齐
// 见 docs/architecture/api-alignment.md 修复记录

export type ConsultationScenario = "contract_review" | "variation"
export type ConsultationStatus = "in_progress" | "completed" | "abandoned"
export type RiskLevel = "red" | "yellow" | "green"

// 三依据引用（由后端 evidence_linker 从库中取 version/effective_date，
// 缺失的引用在链接阶段已被丢弃，前端拿到的一定是可引用的）
export interface LawRef {
  code: string
  /** 法律全称（如「中华人民共和国民法典」），展示用 */
  name?: string | null
  article_no: string
  version: string
  effective_date: string
}

export interface StandardRef {
  code: string
  name?: string | null
  clause_no: string
  version: string
  is_mandatory: boolean
  effective_date?: string | null
}

export interface ConsultationConclusion {
  id: number
  level: RiskLevel
  title: string
  content: string

  fact_refs: number[]
  law_refs: LawRef[]
  standard_refs: StandardRef[]

  reasoning_chain: string | null
  counter_arguments: string | null

  created_at: string
}

export interface ConsultationFact {
  id: number
  fact_key: string
  fact_label: string
  fact_value: string
  fact_value_type: string
  confidence: number

  created_at: string
}

export interface Consultation {
  id: number
  project_id: number
  scenario: ConsultationScenario
  status: ConsultationStatus
  current_step: string

  dispute_summary_user: string | null
  dispute_summary_ai: string | null

  facts: ConsultationFact[]
  conclusions: ConsultationConclusion[]

  /** 采集进度快照（左栏「采集进度」面板数据源，见 consultation-ui.md §4） */
  fact_progress: FactProgress | null
  /** 三依据降级告警（缺版本号的引用被丢弃时记录，必须可见） */
  evidence_warnings: EvidenceWarning[]

  created_at: string
  updated_at: string
}

// ===== 事实采集进度（与后端 schemas.FactProgressOut 对齐）=====

/** 单个事实键的规格。由后端下发，前端**不硬编码**必填清单（避免两端漂移） */
export interface FactSpec {
  fact_key: string
  fact_label: string
  value_type: string
  required: boolean
  question: string
}

/** 未过置信度闸门、未写库的事实（等用户手动补） */
export interface PendingFact {
  fact_key: string
  fact_label: string
  reason: string
}

export interface FactProgress {
  required_total: number
  required_have: number
  missing_required: string[]
  registry: FactSpec[]
  pending: PendingFact[]
}

/** 三依据降级告警 */
export interface EvidenceWarning {
  scope: "conclusion" | "ref"
  index: number
  type: string
  detail: string
}

/** 状态机节点（与后端 core/consultation_state.ConsultationStep 对齐） */
export type ConsultationStep =
  | "init"
  | "collecting_facts"
  | "awaiting_confirm"
  | "generating_report"
  | "generating_artifacts"
  | "done"
  | "failed"
  | "abandoned"
  | "await_text"

export interface ConsultationMessage {
  id: number
  consultation_id: number
  role: "user" | "assistant" | "system"
  content: string

  created_at: string
}

export interface ChatTurnResponse {
  consultation_id: number
  user_message_id: number
  assistant_message_id: number
  assistant_content: string
  ready_to_report: boolean
  fact_count: number

  /** 当前状态机节点 */
  current_step: string
  /** 本轮新写入的事实（人类标签），用于「已记下：争议日期」提示 */
  new_fact_labels: string[]
  /** 未过置信度闸门、未写库的项（需用户手动补） */
  pending_facts: PendingFact[]
  fact_progress: FactProgress
  /** 事实抽取失败时的错误（非空表示本轮事实可能缺失，必须可见） */
  extraction_error: string | null
}

/** 确认生成报告的响应（状态机迁移 #6） */
export interface ConfirmReportResponse {
  consultation_id: number
  current_step: string
  ready_to_report: boolean
  /** 提前生成时仍缺的必填 fact_key */
  missing_required: string[]
}

export interface ConsultationListItem {
  id: number
  project_id: number
  project_name: string | null
  scenario: ConsultationScenario
  status: ConsultationStatus
  summary: string | null  // dispute_summary_ai

  fact_count: number
  conclusion_count: number
  red_count: number
  yellow_count: number
  green_count: number

  created_at: string
  updated_at: string
}

export interface ConsultationListResponse {
  project_id?: number | null
  items: ConsultationListItem[]
  total: number
}

// 流式报告事件（与后端 ndjson 一致）
export type StreamEvent =
  | { type: "chunk"; text: string }
  /** 重试前要求前端清空已收到的半截内容 */
  | { type: "reset" }
  | {
      type: "done"
      summary: string
      risk_count: number
      disclaimer?: string
      /** 三依据降级告警 */
      warnings?: EvidenceWarning[]
    }
  | { type: "error"; message: string }
