// Axios 统一封装
// 由于响应拦截器已经返回 response.data，我们改造 apiClient 的方法签名，
// 让 get/post/put/delete 直接返回 T 而不是 Promise<AxiosResponse<T>>。
import axios, { type AxiosInstance, type AxiosRequestConfig, AxiosError } from "axios"
import { ElMessage } from "element-plus"

const instance: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api/v1",
  timeout: 60000,
  // ⚠️ 切勿在此处设置默认 Content-Type: application/json
  //
  // axios 1.x 的 transformRequest 里有这段逻辑（lib/defaults/index.js:47,57）：
  //   const hasJSONContentType = contentType.indexOf('application/json') > -1
  //   if (isFormData(data)) {
  //     return hasJSONContentType ? JSON.stringify(formDataToJSON(data)) : data
  //   }
  // 即：一旦 Content-Type 是 json，**FormData 会被悄悄转成 JSON 字符串**，
  // 浏览器不再设置 multipart 边界 → 后端 FastAPI 解析不到 file/document_type
  // 等表单字段 → 返回 422（且错误信息不指向真正原因，极难排查）。
  //
  // 不设默认头不会影响 JSON 请求：axios 对普通对象会**自动**设置
  // application/json（同文件 101-102 行）。故这里显式留空是正确的。
})

// 请求拦截器
instance.interceptors.request.use((config) => {
  const token = localStorage.getItem("token")
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：剥掉外层 AxiosResponse，直接返回 data
instance.interceptors.response.use(
  (response) => response.data,
  (error: AxiosError<{ message?: string; code?: string }>) => {
    const status = error.response?.status
    const message = error.response?.data?.message || error.message || "请求失败"
    if (status === 401) {
      ElMessage.error("登录已过期，请重新登录")
      localStorage.removeItem("token")
      window.location.href = "/login"
    } else if (status === 403) {
      ElMessage.error("无权访问")
    } else if (status && status >= 500) {
      ElMessage.error(`服务器错误: ${message}`)
    } else if (message) {
      ElMessage.error(message)
    }
    return Promise.reject(error)
  },
)

// 改造版 client：方法返回 Promise<T>，而不是 Promise<AxiosResponse<T>>
const apiClient = {
  get: <T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> =>
    instance.get<T>(url, config).then((r) => r as unknown as T),
  post: <T = unknown>(
    url: string,
    data?: unknown,
    config?: AxiosRequestConfig,
  ): Promise<T> =>
    instance.post<T>(url, data, config).then((r) => r as unknown as T),
  put: <T = unknown>(
    url: string,
    data?: unknown,
    config?: AxiosRequestConfig,
  ): Promise<T> =>
    instance.put<T>(url, data, config).then((r) => r as unknown as T),
  delete: <T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> =>
    instance.delete<T>(url, config).then((r) => r as unknown as T),
}

export default apiClient
