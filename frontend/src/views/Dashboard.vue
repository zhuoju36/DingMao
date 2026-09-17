<script setup lang="ts">
// 工作台 - MVP 占位，后续接入项目列表/最近问诊等
import { ref, onMounted } from "vue"
import { useRouter } from "vue-router"
import { useUserStore } from "@/stores/user"
import { healthApi } from "@/api/health"
import { ElMessage } from "element-plus"

const router = useRouter()
const userStore = useUserStore()

const llmStatus = ref<{ available: boolean; default: string; providers: Record<string, boolean> } | null>(null)

onMounted(async () => {
  try {
    llmStatus.value = await healthApi.checkLLM()
  } catch (e) {
    ElMessage.warning("无法连接后端 API，请确认后端已启动")
  }
})

function handleLogout() {
  userStore.logout()
  router.push("/login")
}
</script>

<template>
  <div class="dashboard">
    <el-container>
      <el-header class="header">
        <div class="header-content">
          <h3>建工法律顾问</h3>
          <div class="user-info">
            <span>{{ userStore.userInfo?.fullName || userStore.userInfo?.email }}</span>
            <el-tag size="small" class="ml-8">{{ userStore.role }}</el-tag>
            <el-button text @click="handleLogout" class="ml-8">退出</el-button>
          </div>
        </div>
      </el-header>

      <el-main class="main">
        <el-row :gutter="16">
          <el-col :span="8">
            <el-card shadow="hover">
              <template #header>
                <div class="flex-between">
                  <span>合同审查</span>
                  <el-tag size="small" type="warning">P0</el-tag>
                </div>
              </template>
              <p>上传合同/招标文件，获取红黄绿分级审查报告</p>
              <el-button type="primary" plain @click="router.push('/projects')">进入项目</el-button>
            </el-card>
          </el-col>

          <el-col :span="8">
            <el-card shadow="hover">
              <template #header>
                <div class="flex-between">
                  <span>变更扯皮</span>
                  <el-tag size="small" type="danger">P0</el-tag>
                </div>
              </template>
              <p>律师问诊式对话，生成签证单/索赔报告/证据目录</p>
              <el-button type="primary" plain @click="router.push('/projects')">开始问诊</el-button>
            </el-card>
          </el-col>

          <el-col :span="8">
            <el-card shadow="hover">
              <template #header>
                <div class="flex-between">
                  <span>系统状态</span>
                </div>
              </template>
              <div v-if="llmStatus">
                <p>
                  LLM 默认:
                  <el-tag :type="llmStatus.available ? 'success' : 'danger'" size="small">
                    {{ llmStatus.default }}
                  </el-tag>
                </p>
                <p>
                  MiniMax-M3:
                  <el-tag :type="llmStatus.providers.minimax ? 'success' : 'info'" size="small">
                    {{ llmStatus.providers.minimax ? "已配置" : "未配置" }}
                  </el-tag>
                </p>
                <p>
                  DeepSeek-V4-Flash:
                  <el-tag :type="llmStatus.providers.deepseek ? 'success' : 'info'" size="small">
                    {{ llmStatus.providers.deepseek ? "已配置" : "未配置" }}
                  </el-tag>
                </p>
              </div>
              <div v-else>
                <el-text type="warning">无法连接后端</el-text>
              </div>
            </el-card>
          </el-col>
        </el-row>

        <el-card class="mt-16" shadow="hover">
          <template #header>
            <span>MVP 进度</span>
          </template>
          <el-timeline>
            <el-timeline-item timestamp="W-2 ~ W0" type="primary">准备期：知识库结构化启动</el-timeline-item>
            <el-timeline-item timestamp="W1 ~ W4">MVP Core：合同审查场景</el-timeline-item>
            <el-timeline-item timestamp="W5 ~ W8">变更扯皮场景</el-timeline-item>
            <el-timeline-item timestamp="W9 ~ W12">打磨 + Beta 内测</el-timeline-item>
          </el-timeline>
        </el-card>
      </el-main>
    </el-container>
  </div>
</template>

<style scoped>
.dashboard {
  min-height: 100vh;
  background: #f5f7fa;
}

.header {
  background: #fff;
  border-bottom: 1px solid #ebeef5;
  padding: 0;
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
  padding: 0 24px;
}

.user-info {
  display: flex;
  align-items: center;
}

.ml-8 {
  margin-left: 8px;
}

.main {
  padding: 24px;
}
</style>