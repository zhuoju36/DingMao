// 问诊相关 API
import apiClient from "./index"
import type {
  ChatTurnResponse,
  ConfirmReportResponse,
  Consultation,
  ConsultationListItem,
  ConsultationListResponse,
  ConsultationMessage,
  ConsultationScenario,
  ConsultationStatus,
  StreamEvent,
} from "@/types/consultation"

export type {
  ChatTurnResponse,
  ConfirmReportResponse,
  Consultation,
  ConsultationConclusion,
  ConsultationFact,
  ConsultationListItem,
  ConsultationListResponse,
  ConsultationMessage,
  ConsultationScenario,
  ConsultationStatus,
  EvidenceWarning,
  FactProgress,
  FactSpec,
  LawRef,
  PendingFact,
  RiskLevel,
  StandardRef,
  StreamEvent,
} from "@/types/consultation"

// === 普通 JSON 端点 ===

export async function createConsultation(
  projectId: number,
  scenario: ConsultationScenario = "contract_review"
): Promise<Consultation> {
  return apiClient.post<Consultation>("/consultations", {
    project_id: projectId,
    scenario,
  })
}

export async function getConsultation(id: number): Promise<Consultation> {
  return apiClient.get<Consultation>(`/consultations/${id}`)
}

/**
 * 用户确认生成报告（状态机迁移 #6：awaiting_confirm → generating_report）。
 *
 * 只做状态迁移与校验，实际的 LLM 流式生成仍走 generateReportStream。
 * 必填未齐时后端不阻断（consultation-ui.md §5.1），但在响应里返回
 * missing_required，由前端提示。
 */
export async function confirmReport(
  id: number
): Promise<ConfirmReportResponse> {
  return apiClient.post<ConfirmReportResponse>(`/consultations/${id}/confirm`)
}

// === 流式端点 ===

/**
 * 异步生成器，逐个 yield 后端的 ndjson 事件。
 * 使用原生 fetch + ReadableStream 解析（不引第三方库）。
 */
export async function* generateReportStream(
  consultationId: number,
  signal?: AbortSignal
): AsyncGenerator<StreamEvent, void, unknown> {
  const token = localStorage.getItem("token") ?? ""
  const response = await fetch(
    `/api/v1/consultations/${consultationId}/generate-report-stream`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      signal,
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

export async function postMessage(
  consultationId: number,
  content: string
): Promise<ChatTurnResponse> {
  return apiClient.post<ChatTurnResponse>(
    `/consultations/${consultationId}/messages`,
    { content }
  )
}

export async function listMessages(
  consultationId: number
): Promise<ConsultationMessage[]> {
  return apiClient.get<ConsultationMessage[]>(
    `/consultations/${consultationId}/messages`
  )
}

// === 项目下问诊列表 ===

export async function listProjectConsultations(
  projectId: number,
  scenario?: ConsultationScenario
): Promise<ConsultationListItem[]> {
  const query = scenario ? `?scenario=${scenario}` : ""
  const r = await apiClient.get<ConsultationListResponse>(
    `/projects/${projectId}/consultations${query}`
  )
  return r.items
}

// === 我的问诊（跨项目）===

export async function listMyConsultations(params?: {
  scenario?: ConsultationScenario
  status?: ConsultationStatus
  limit?: number
}): Promise<ConsultationListItem[]> {
  const q = new URLSearchParams()
  if (params?.scenario) q.set("scenario", params.scenario)
  if (params?.status) q.set("status_filter", params.status)
  if (params?.limit) q.set("limit", String(params.limit))
  const query = q.toString() ? `?${q}` : ""
  const r = await apiClient.get<ConsultationListResponse>(
    `/consultations${query}`
  )
  return r.items
}
