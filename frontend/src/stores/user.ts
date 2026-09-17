// 用户状态管理
import { defineStore } from "pinia"
import { ref, computed } from "vue"

export type UserRole = "owner" | "designer" | "supervisor" | "contractor" | "subcontractor"

export interface UserInfo {
  id: number
  email: string
  fullName: string | null
  role: UserRole
}

export const useUserStore = defineStore(
  "user",
  () => {
    const token = ref<string>("")
    const userInfo = ref<UserInfo | null>(null)

    const isLoggedIn = computed(() => !!token.value)
    const role = computed(() => userInfo.value?.role || null)

    function setAuth(t: string, info: UserInfo) {
      token.value = t
      userInfo.value = info
      // 统一在此写入原始 token key：
      // Axios 拦截器与路由守卫直接读 localStorage（避免循环依赖），
      // 所以两处必须同步，写入口收敛到这里。
      localStorage.setItem("token", t)
    }

    function logout() {
      token.value = ""
      userInfo.value = null
      localStorage.removeItem("token")
    }

    return { token, userInfo, isLoggedIn, role, setAuth, logout }
  },
  {
    persist: {
      key: "lawyer-user",
      storage: localStorage,
    },
  },
)