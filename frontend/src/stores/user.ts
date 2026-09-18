// 用户状态管理
import { defineStore } from "pinia"
import { ref, computed } from "vue"

import type { UserRole } from "@/types/project"

// Re-export UserRole（保持旧 import 路径兼容）
export type { UserRole }

export interface UserInfo {
  id: number
  email: string
  fullName: string | null
  /** 新建项目时的默认角色（项目级 role 由 Project 持有，本字段不再代表当前角色） */
  defaultRole: UserRole
}

export const useUserStore = defineStore(
  "user",
  () => {
    const token = ref<string>("")
    const userInfo = ref<UserInfo | null>(null)

    const isLoggedIn = computed(() => !!token.value)
    /** 默认角色（用于新建项目表单预填） */
    const defaultRole = computed(() => userInfo.value?.defaultRole || null)

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

    return { token, userInfo, isLoggedIn, defaultRole, setAuth, logout }
  },
  {
    persist: {
      key: "dingmao-user",
      storage: localStorage,
    },
  },
)