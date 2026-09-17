// 问诊相关 API
import apiClient from "./index"

export type ConsultationScenario = "contract_review" | "variation"
export type ConsultationStatus = "in_progress" | "completed" | "abandoned"

export interface ConsultationConclusion {
  id: number
  level: "red" | "yellow" | "green"
  title: string
  content: string
  fact_refs: number[]
  law_refs: unknown[]
  standard_refs: unknown[]
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
  scenario: string
  status: string
  dispute_summary_user: string | null
  dispute_summary_ai: string | null
  current_step: string
  created_at: string
  updated_at: string
  facts: ConsultationFact[]
  conclusions: ConsultationConclusion[]
}

// === 普通 JSON 端点 ===

export async function createConsultation(
  projectId: number,
  scenario: ConsultationScenario = "contract_review"
): Promise<Consultation> {
  const r = await apiClient.post<Consultation>("/consultations", {
    project_id: projectId,
    scenario,
  })
  return r as unknown as Consultation
}

export async function submitContractText(
  consultationId: number,
  content: string
): Promise<Consultation> {
  const r = await apiClient.post<Consultation>(
    `/consultations/${consultationId}/submit-text`,
    { content }
  )
  return r as unknown as Consultation
}

export async function getConsultation(id: number): Promise<Consultation> {
  const r = await apiClient.get<Consultation>(`/consultations/${id}`)
  return r as unknown as Consultation
}

// === 流式端点 ===

export type StreamEvent =
  | { type: "chunk"; text: string }
  | { type: "done"; summary: string; risk_count: number; disclaimer?: string }
  | { type: "error"; message: string }

/**
 * 异步生成器，逐个 yield 后端的 ndjson 事件。
 * 使用原生 fetch + ReadableStream 解析（不引第三方库）。
 */
export async function* generateReportStream(
  consultationId: number
): AsyncGenerator<StreamEvent, void, unknown> {
  const token = localStorage.getItem("token") ?? ""
  const response = await fetch(
    `/api/v1/consultations/${consultationId}/generate-report-stream`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }
  )

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }
  if (!response.body) {
    throw new Error("响应为空")
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder("utf-8")
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // 按行切：最后一段可能不完整，保留到下一轮
    const lines = buffer.split("\n")
    buffer = lines.pop() ?? ""
    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed) continue
      try {
        yield JSON.parse(trimmed) as StreamEvent
      } catch {
        // 跳过格式异常的 JSON 行
      }
    }
  }
}

// === 多轮对话端点 ===

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

export async function postMessage(
  consultationId: number,
  content: string
): Promise<ChatTurnResponse> {
  const r = await apiClient.post<ChatTurnResponse>(
    `/consultations/${consultationId}/messages`,
    { content }
  )
  return r as unknown as ChatTurnResponse
}

export async function listMessages(
  consultationId: number
): Promise<ConsultationMessage[]> {
  const r = await apiClient.get<ConsultationMessage[]>(
    `/consultations/${consultationId}/messages`
  )
  return r as unknown as ConsultationMessage[]
}

// === 项目下问诊列表 ===

export interface ConsultationListItem {
  id: number
  scenario: string
  status: string
  summary: string | null
  fact_count: number
  conclusion_count: number
  red_count: number
  yellow_count: number
  green_count: number
  created_at: string
  updated_at: string
}

export async function listProjectConsultations(
  projectId: number,
  scenario?: ConsultationScenario
): Promise<ConsultationListItem[]> {
  const query = scenario ? `?scenario=${scenario}` : ""
  const r = await apiClient.get<{ items: ConsultationListItem[]; total: number }>(
    `/projects/${projectId}/consultations${query}`
  )
  return (r as unknown as { items: ConsultationListItem[] }).items
}
