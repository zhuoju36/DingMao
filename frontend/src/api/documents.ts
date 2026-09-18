// 项目档案 API（P0-7-A 上传 / P0-7-B 解析 / P0-7-C 下载 + 轻量列表）
import apiClient from "./index"

// 与后端 app/schemas/document.py 对齐
export type DocumentType =
  | "contract"
  | "bidding"
  | "variation"
  | "correspondence"
  | "inspection"
  | "evidence"

export type ParseStatus =
  | "pending"
  | "parsing"
  | "parsed"
  | "failed_upload"
  | "failed_parse"
  | "archived"

export type StorageProvider = "local" | "cos"

/** 文档类型的中文标签（UI 复用，与后端 DocumentType 一一对应）。 */
export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  contract: "合同",
  bidding: "招标文件",
  variation: "签证单",
  correspondence: "往来文件",
  inspection: "监理通知单",
  evidence: "其他证据",
}

/**
 * 列表项（轻量）—— 与后端 DocumentListItem 对齐。
 * 不含 markdown；解析摘要为标量（page_count / markdown_chars / parse_elapsed_sec）。
 */
export interface DocumentListItem {
  id: number
  project_id: number
  uploader_id: number
  document_type: DocumentType
  title: string
  file_name: string
  file_size: number
  mime_type: string
  parse_status: ParseStatus
  parse_error: string | null
  page_count: number
  markdown_chars: number
  parse_elapsed_sec: number | null
  created_at: string
  updated_at: string
}

/** 详情（含解析产物，markdown 内联）。 */
export interface DocumentResponse {
  id: number
  project_id: number
  uploader_id: number
  document_type: DocumentType
  title: string
  file_name: string
  file_size: number
  mime_type: string
  storage_path: string
  storage_provider: StorageProvider
  parse_status: ParseStatus
  parse_error: string | null
  // 解析产物：只内联 markdown；middle.json / images/ 见 parsed_dir
  parsed_content: {
    markdown: string | null
    page_count: number
    markdown_chars: number
    middle_json_bytes: number
    images: number
    elapsed_sec: number
    tier: string
    parsed_dir: string
  } | null
  created_at: string
  updated_at: string
}

export interface DocumentUploadResponse {
  id: number
  project_id: number
  document_type: DocumentType
  title: string
  file_name: string
  file_size: number
  mime_type: string
  storage_path: string
  storage_provider: StorageProvider
  parse_status: ParseStatus
  created_at: string
}

export interface DocumentListResponse {
  items: DocumentListItem[]
  total: number
}

// ===== API 函数 =====

/** 上传文件到项目档案（multipart/form-data），成功后后端自动入队解析。 */
export async function uploadDocument(
  projectId: number,
  file: File,
  documentType: DocumentType,
  title: string
): Promise<DocumentUploadResponse> {
  const formData = new FormData()
  formData.append("file", file)
  formData.append("document_type", documentType)
  formData.append("title", title)
  // axios 会自动设置 multipart/form-data 边界
  return apiClient.post<DocumentUploadResponse>(
    `/projects/${projectId}/documents`,
    formData
  )
}

/** 列出项目下所有档案（轻量项）。 */
export async function listDocuments(
  projectId: number
): Promise<DocumentListItem[]> {
  const r = await apiClient.get<DocumentListResponse>(
    `/projects/${projectId}/documents`
  )
  return r.items
}

/** 档案详情（含解析产物 markdown）。 */
export async function getDocument(
  projectId: number,
  documentId: number
): Promise<DocumentResponse> {
  return apiClient.get<DocumentResponse>(
    `/projects/${projectId}/documents/${documentId}`
  )
}

/**
 * 下载原始文件并触发浏览器保存。
 *
 * 为什么不用 <a href>：接口需要 Authorization 头，普通链接带不上。
 * 这里用 axios 取 blob → createObjectURL → 触发下载 → 释放 URL。
 */
export async function downloadDocument(
  projectId: number,
  documentId: number,
  fileName: string
): Promise<void> {
  const blob = await apiClient.get<Blob>(
    `/projects/${projectId}/documents/${documentId}/download`,
    { responseType: "blob" }
  )
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement("a")
    a.href = url
    a.download = fileName
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    // 必须释放，否则 blob 常驻内存直到页面卸载
    URL.revokeObjectURL(url)
  }
}

export interface ReparseResponse {
  document_id: number
  parse_status: ParseStatus
  /** false = 已在队列中，或任务队列不可用 */
  queued: boolean
  message: string
}

/** 重新解析（清空旧产物 → 重新入队）。 */
export async function reparseDocument(
  projectId: number,
  documentId: number
): Promise<ReparseResponse> {
  return apiClient.post<ReparseResponse>(
    `/projects/${projectId}/documents/${documentId}/reparse`
  )
}

/** 删除档案（DB 行 + 源文件 + 解析产物）。 */
export async function deleteDocument(
  projectId: number,
  documentId: number
): Promise<void> {
  await apiClient.delete<void>(`/projects/${projectId}/documents/${documentId}`)
}
