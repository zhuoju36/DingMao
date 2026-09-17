// 健康检查 API
// 响应拦截器已经 unwrap，方法直接返回 T。
import apiClient from "./index"

interface LlmStatus {
  default: string
  providers: Record<string, boolean>
  available: boolean
}

export const healthApi = {
  async check(): Promise<{ status: string }> {
    return apiClient.get<{ status: string }>("/health")
  },
  async checkLLM(): Promise<LlmStatus> {
    return apiClient.get<LlmStatus>("/health/llm")
  },
}
