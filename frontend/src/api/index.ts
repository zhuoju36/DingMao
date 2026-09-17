// Axios 统一封装
// 由于响应拦截器已经返回 response.data，我们改造 apiClient 的方法签名，
// 让 get/post/put/delete 直接返回 T 而不是 Promise<AxiosResponse<T>>。
import axios, { type AxiosInstance, type AxiosRequestConfig, AxiosError } from "axios"
import { ElMessage } from "element-plus"

const instance: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api/v1",
  timeout: 60000,
  headers: { "Content-Type": "application/json" },
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
