<script setup lang="ts">
// 项目详情 - 接真实后端
import { computed, onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { ElMessage } from "element-plus"
import apiClient from "@/api"

interface Project {
  id: number
  name: string
  code: string | null
  description: string | null
  location: string | null
  contract_amount: string | null
  contract_start_date: string | null
  contract_end_date: string | null
  contract_text: string | null
  owner_org: string | null
  design_org: string | null
  supervisor_org: string | null
  contractor_org: string | null
}

interface Consultation {
  id: number
  project_id: number
  scenario: string
  status: string
  dispute_summary_ai: string | null
  created_at: string
  conclusions: { level: string; title: string }[]
}

const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.id))

const project = ref<Project | null>(null)
const consultations = ref<Consultation[]>([])
const loading = ref(false)
const activeTab = ref("overview")
const starting = ref<string | null>(null)

async function fetchData() {
  loading.value = true
  try {
    project.value = await apiClient.get<Project>(`/projects/${projectId.value}`)
    // 拉项目下的问诊（用 list 项目端点拿到 consultations 关联）
    // 后端 ProjectResponse 没带 consultations 列表，所以从 detail 单独拉
    // 这里简化：前端存一份 token 后让用户进 /consultations/{id} 看详情
  } catch {
    ElMessage.error("加载项目失败")
  } finally {
    loading.value = false
  }
}

async function startConsultation(scenario: "contract_review" | "variation") {
  starting.value = scenario
  try {
    const created = await apiClient.post<{ id: number }>("/consultations", {
      project_id: projectId.value,
      scenario,
    })
    ElMessage.success(`问诊已创建 #${created.id}`)
    router.push(`/consultation/${created.id}`)
  } catch (e) {
    const msg = e instanceof Error ? e.message : "创建失败"
    ElMessage.error(msg)
  } finally {
    starting.value = null
  }
}

function fmt(v: string | null | undefined) {
  return v && v.length > 0 ? v : "—"
}

function fmtMoney(v: string | null | undefined) {
  return v ? `¥ ${Number(v).toLocaleString()}` : "—"
}

onMounted(fetchData)
</script>

<template>
  <div class="project-detail">
    <el-page-header @back="router.push('/projects')" class="mb-16">
      <template #content>
        <span class="page-title">
          {{ project?.name || `项目 #${projectId}` }}
        </span>
      </template>
    </el-page-header>

    <div v-loading="loading">
      <el-tabs v-model="activeTab">
        <!-- 概览 -->
        <el-tab-pane label="概览" name="overview">
          <el-empty
            v-if="!project"
            description="项目不存在或加载失败"
          />
          <el-descriptions v-else :column="2" border>
            <el-descriptions-item label="项目名称">{{ fmt(project.name) }}</el-descriptions-item>
            <el-descriptions-item label="工程编号">{{ fmt(project.code) }}</el-descriptions-item>
            <el-descriptions-item label="工程地点">{{ fmt(project.location) }}</el-descriptions-item>
            <el-descriptions-item label="合同金额">{{ fmtMoney(project.contract_amount) }}</el-descriptions-item>
            <el-descriptions-item label="开工日期">{{ fmt(project.contract_start_date) }}</el-descriptions-item>
            <el-descriptions-item label="竣工日期">{{ fmt(project.contract_end_date) }}</el-descriptions-item>
            <el-descriptions-item label="建设单位">{{ fmt(project.owner_org) }}</el-descriptions-item>
            <el-descriptions-item label="施工单位">{{ fmt(project.contractor_org) }}</el-descriptions-item>
            <el-descriptions-item label="设计单位">{{ fmt(project.design_org) }}</el-descriptions-item>
            <el-descriptions-item label="监理单位">{{ fmt(project.supervisor_org) }}</el-descriptions-item>
            <el-descriptions-item
              v-if="project.description"
              label="项目描述"
              :span="2"
            >
              {{ project.description }}
            </el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>

        <!-- 合同审查 -->
        <el-tab-pane label="合同审查" name="contract">
          <el-button
            type="primary"
            :loading="starting === 'contract_review'"
            @click="startConsultation('contract_review')"
          >
            <el-icon><Plus /></el-icon>
            开始合同审查
          </el-button>
          <p class="mt-16">
            <small>合同审查将基于本项目的合同条款，由 AI 助手识别风险条款。</small>
          </p>
        </el-tab-pane>

        <!-- 变更扯皮 -->
        <el-tab-pane label="变更扯皮" name="variation">
          <el-button
            type="primary"
            :loading="starting === 'variation'"
            @click="startConsultation('variation')"
          >
            <el-icon><Plus /></el-icon>
            开始变更问诊
          </el-button>
          <p class="mt-16">
            <small>变更扯皮场景帮助您梳理变更事实，评估签证/索赔风险。</small>
          </p>
        </el-tab-pane>

        <!-- 归档文件 -->
        <el-tab-pane label="归档文件" name="documents">
          <el-empty description="归档文件功能在 W2 阶段实现" />
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<style scoped>
.project-detail {
  padding: 24px;
  background: #fff;
  min-height: calc(100vh - 60px);
}

.page-title {
  font-size: 16px;
  font-weight: bold;
}

.mb-16 {
  margin-bottom: 16px;
}

.mt-16 {
  margin-top: 16px;
}
</style>
