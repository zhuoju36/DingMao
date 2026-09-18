// Project 类型 — 与后端 ProjectResponse 1:1 对齐（16 字段）
// 见 docs/architecture/api-alignment.md 修复记录
export type UserRole =
  | "owner"
  | "designer"
  | "supervisor"
  | "contractor"
  | "subcontractor"

export interface Project {
  id: number
  name: string
  code: string | null
  description: string | null
  location: string | null

  // Decimal / date / int 在 JSON 中都是字符串
  contract_amount: string | null
  contract_start_date: string | null  // YYYY-MM-DD
  contract_end_date: string | null    // YYYY-MM-DD
  contract_duration_days: number | null

  owner_org: string | null
  design_org: string | null
  supervisor_org: string | null
  contractor_org: string | null

  role: UserRole

  contract_text: string | null
  contract_clauses: Record<string, unknown> | null

  // 后端新增（修复 P3-2）
  created_at?: string
  updated_at?: string
}

export interface ProjectListResponse {
  items: Project[]
  total: number
}
