// 项目档案 API（P0-7-A 最小切片）
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
  items: DocumentResponse[]
  total: number
}

// ===== API 函数 =====

/** 上传文件到项目档案（multipart/form-data）。 */
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

/** 列出项目下所有档案。 */
export async function listDocuments(
  projectId: number
): Promise<DocumentResponse[]> {
  const r = await apiClient.get<DocumentListResponse>(
    `/projects/${projectId}/documents`
  )
  return r.items
}

/** 档案详情。 */
export async function getDocument(
  projectId: number,
  documentId: number
): Promise<DocumentResponse> {
  return apiClient.get<DocumentResponse>(
    `/projects/${projectId}/documents/${documentId}`
  )
}
