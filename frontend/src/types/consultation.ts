// Consultation 类型 — 与后端 schemas/consultation.py 1:1 对齐
// 见 docs/architecture/api-alignment.md 修复记录

export type ConsultationScenario = "contract_review" | "variation"
export type ConsultationStatus = "in_progress" | "completed" | "abandoned"
export type RiskLevel = "red" | "yellow" | "green"

// W3-W8 第 3 轮 EvidenceLinker 修复后（P2-2 同步）：
// LLM 输出后由 EvidenceLinker 自动填充 version / effective_date
export interface LawRef {
  code: string
  article_no: string
  version: string
  effective_date: string
}

export interface StandardRef {
  code: string
  clause_no: string
  version: string
  is_mandatory: boolean
  effective_date?: string
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

  created_at: string
  updated_at: string
}

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
  | { type: "done"; summary: string; risk_count: number; disclaimer?: string }
  | { type: "error"; message: string }
