<script setup lang="ts">
// 登录页 - 接真实后端（/api/v1/auth/register + /login）
import { ref } from "vue"
import { useRouter } from "vue-router"
import { ElMessage } from "element-plus"
import { useUserStore } from "@/stores/user"
import apiClient from "@/api"

const router = useRouter()
const userStore = useUserStore()

const mode = ref<"login" | "register">("login")
// 仅在开发环境预填演示账号，生产环境留空
const email = ref(import.meta.env.DEV ? "demo@lawyer.com" : "")
const password = ref(import.meta.env.DEV ? "Demo123456" : "")
const fullName = ref("")
const role = ref<"owner" | "designer" | "supervisor" | "contractor" | "subcontractor">(
  "supervisor"
)
const loading = ref(false)

async function handleSubmit() {
  if (!email.value.trim() || !password.value.trim()) {
    ElMessage.warning("请填写邮箱和密码")
    return
  }
  loading.value = true
  try {
    const url = mode.value === "login" ? "/auth/login" : "/auth/register"
    const body: Record<string, unknown> = {
      email: email.value,
      password: password.value,
    }
    if (mode.value === "register") {
      body.full_name = fullName.value || null
      body.role = role.value
    }

    const res = await apiClient.post<{ access_token: string }>(url, body)

    // 必须先落 localStorage：下面的 /auth/me 会经过 Axios 拦截器读它。
    // setAuth 内部会再写一次（幂等），保证 store 与 localStorage 一致。
    localStorage.setItem("token", res.access_token)
    const me = await apiClient.get<{
      id: number
      email: string
      full_name: string | null
      role: typeof role.value
      is_active: boolean
    }>("/auth/me")

    userStore.setAuth(res.access_token, {
      id: me.id,
      email: me.email,
      fullName: me.full_name,
      role: me.role,
    })

    ElMessage.success(mode.value === "login" ? "登录成功" : "注册成功")
    router.push("/dashboard")
  } catch (e) {
    const msg = e instanceof Error ? e.message : "请求失败"
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}

function toggleMode() {
  mode.value = mode.value === "login" ? "register" : "login"
}
</script>

<template>
  <div class="login-page flex-center">
    <el-card class="login-card" shadow="always">
      <h2 class="text-center">钉铆</h2>
      <p class="text-center subtitle">钉是钉，铆是铆 —— 讲法律，讲合规</p>

      <div class="mode-tabs">
        <el-radio-group v-model="mode" size="default">
          <el-radio-button value="login">登录</el-radio-button>
          <el-radio-button value="register">注册</el-radio-button>
        </el-radio-group>
      </div>

      <el-form @submit.prevent="handleSubmit">
        <el-form-item label="邮箱">
          <el-input v-model="email" placeholder="you@example.com" />
        </el-form-item>
        <el-form-item v-if="mode === 'register'" label="姓名">
          <el-input v-model="fullName" placeholder="可选" />
        </el-form-item>
        <el-form-item v-if="mode === 'register'" label="角色">
          <el-select v-model="role" style="width: 100%">
            <el-option label="业主/建设单位" value="owner" />
            <el-option label="设计单位" value="designer" />
            <el-option label="监理单位" value="supervisor" />
            <el-option label="施工单位" value="contractor" />
            <el-option label="其他分包商" value="subcontractor" />
          </el-select>
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="password"
            type="password"
            placeholder="至少 8 位"
            show-password
          />
        </el-form-item>
        <el-button
          type="primary"
          native-type="submit"
          :loading="loading"
          class="submit-btn"
        >
          {{ mode === "login" ? "登录" : "注册并登录" }}
        </el-button>
      </el-form>

      <div class="footer mt-16">
        <p class="text-center">
          <small>本系统仅供工程人员参考，重大决策请咨询执业律师</small>
        </p>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-card {
  width: 420px;
  padding: 24px;
}

.subtitle {
  color: #909399;
  margin-bottom: 16px;
}

.mode-tabs {
  display: flex;
  justify-content: center;
  margin-bottom: 16px;
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
}

.footer {
  color: #909399;
  margin-top: 16px;
}

.mt-16 {
  margin-top: 16px;
}
</style>
