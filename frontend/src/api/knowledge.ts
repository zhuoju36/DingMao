// 知识库搜索 API（对齐后端 /knowledge/search）
import apiClient from "./index"

// 后端 LawHit 当前字段（注意：缺 version，待知识库层 P1-1 修复后补）
export interface LawHit {
  law_id: number
  law_code: string
  law_name: string
  article_id: number
  article_no: string
  content: string
  keywords: string[]
  effective_date: string | null
}

// 后端 StandardHit 当前字段
export interface StandardHit {
  standard_id: number
  standard_code: string
  standard_name: string
  clause_id: number
  clause_no: string
  content: string
  is_mandatory: boolean
  behavior_tags: string[]
  effective_date: string | null
}

export interface KnowledgeSearchResponse {
  query: string
  laws: LawHit[]
  standards: StandardHit[]
  total: number
}

export async function searchKnowledge(
  q: string,
  limit = 5
): Promise<KnowledgeSearchResponse> {
  // axios 默认 query string 编码
  return apiClient.get<KnowledgeSearchResponse>(
    `/knowledge/search?q=${encodeURIComponent(q)}&limit=${limit}`
  )
}
