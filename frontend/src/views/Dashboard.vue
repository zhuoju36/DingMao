<script setup lang="ts">
// 工作台 - 快速回到上次的工作
import { computed, onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { ElMessage } from "element-plus"
import apiClient from "@/api"
import { listMyConsultations, type ConsultationListItem } from "@/api/consultation"
import { useUserStore } from "@/stores/user"

interface Project {
  id: number
  name: string
  code: string | null
  location: string | null
  contract_amount: string | null
  contractor_org: string | null
  updated_at?: string
}

const router = useRouter()
const userStore = useUserStore()

const loading = ref(false)
const projects = ref<Project[]>([])
const consultations = ref<ConsultationListItem[]>([])

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return "夜色已深"
  if (h < 12) return "早上好"
  if (h < 14) return "中午好"
  if (h < 18) return "下午好"
  return "晚上好"
})

const displayName = computed(
  () => userStore.userInfo?.fullName || userStore.userInfo?.email?.split("@")[0] || "工程师"
)

const scenarioLabels: Record<string, string> = {
  contract_review: "合同审查",
  variation: "变更扯皮",
}

const statusMeta: Record<string, { label: string; type: "success" | "warning" | "info" }> = {
  in_progress: { label: "进行中", type: "warning" },
  completed: { label: "已完成", type: "success" },
  abandoned: { label: "已废弃", type: "info" },
}

const inProgressConsultations = computed(() =>
  consultations.value.filter((c) => c.status === "in_progress")
)

async function fetchData() {
  loading.value = true
  try {
    const [projRes, cons] = await Promise.all([
      apiClient.get<{ items: Project[]; total: number }>("/projects?limit=6"),
      listMyConsultations({ limit: 8 }),
    ])
    projects.value = projRes.items
    consultations.value = cons
  } catch (e) {
    ElMessage.warning("加载工作台数据失败，请确认后端已启动")
    console.error(e)
  } finally {
    loading.value = false
  }
}

function openConsultation(id: number) {
  router.push(`/consultation/${id}`)
}

function openProject(id: number) {
  router.push(`/projects/${id}`)
}

function fmtTime(v: string) {
  return v ? v.slice(5, 16).replace("T", " ") : "—"
}

function fmtMoney(v: string | null) {
  return v ? `¥ ${Number(v).toLocaleString()}` : "—"
}

onMounted(fetchData)
</script>

<template>
  <div class="dashboard" v-loading="loading">
    <!-- 欢迎语 -->
    <div class="hero">
      <h2>{{ greeting }}，{{ displayName }} 👋</h2>
      <p class="hero-sub">
        <template v-if="inProgressConsultations.length">
          你有 <strong>{{ inProgressConsultations.length }}</strong> 个进行中的问诊
        </template>
        <template v-else-if="consultations.length">
          最近有 {{ consultations.length }} 条问诊记录
        </template>
        <template v-else> 还没有问诊记录，从新建项目开始 </template>
      </p>
    </div>

    <!-- 待继续的问诊 -->
    <el-card v-if="inProgressConsultations.length" class="section" shadow="never">
      <template #header>
        <span class="section-title">⏳ 待继续</span>
      </template>
      <div
        v-for="c in inProgressConsultations"
        :key="c.id"
        class="row-item"
        @click="openConsultation(c.id)"
      >
        <el-tag size="small" type="warning">进行中</el-tag>
        <span class="row-main">{{ c.project_name || `项目 #${c.project_id}` }}</span>
        <span class="row-scene">{{ scenarioLabels[c.scenario] ?? c.scenario }}</span>
        <span class="row-meta">已采集事实 {{ c.fact_count }}</span>
        <div class="spacer" />
        <el-button text type="primary" size="small">继续对话</el-button>
      </div>
    </el-card>

    <!-- 我的项目 -->
    <el-card class="section" shadow="never">
      <template #header>
        <div class="card-head">
          <span class="section-title">📁 我的项目</span>
          <div class="spacer" />
          <el-button text type="primary" size="small" @click="router.push('/projects')">
            查看全部
          </el-button>
        </div>
      </template>

      <el-empty v-if="projects.length === 0" description="还没有项目" :image-size="80">
        <el-button type="primary" @click="router.push('/projects')">新建项目</el-button>
      </el-empty>

      <div v-else class="project-grid">
        <div
          v-for="p in projects"
          :key="p.id"
          class="project-card"
          @click="openProject(p.id)"
        >
          <div class="pc-name">{{ p.name }}</div>
          <div class="pc-code">{{ p.code || "—" }}</div>
          <div class="pc-meta">
            <span>{{ p.location || "—" }}</span>
            <span class="pc-money">{{ fmtMoney(p.contract_amount) }}</span>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 最近问诊 -->
    <el-card class="section" shadow="never">
      <template #header>
        <span class="section-title">🕘 最近问诊</span>
      </template>

      <el-empty v-if="consultations.length === 0" description="还没有问诊记录" :image-size="80" />

      <div v-else>
        <div
          v-for="c in consultations"
          :key="c.id"
          class="row-item"
          @click="openConsultation(c.id)"
        >
          <span class="row-id">#{{ c.id }}</span>
          <el-tag size="small" :type="statusMeta[c.status]?.type ?? 'info'">
            {{ statusMeta[c.status]?.label ?? c.status }}
          </el-tag>
          <span class="row-scene">{{ scenarioLabels[c.scenario] ?? c.scenario }}</span>
          <span class="row-main">{{ c.project_name || `项目 #${c.project_id}` }}</span>
          <div class="spacer" />
          <template v-if="c.conclusion_count">
            <el-tag v-if="c.red_count" type="danger" size="small">🔴 {{ c.red_count }}</el-tag>
            <el-tag v-if="c.yellow_count" type="warning" size="small" class="ml-4">
              🟡 {{ c.yellow_count }}
            </el-tag>
            <el-tag v-if="c.green_count" type="success" size="small" class="ml-4">
              🟢 {{ c.green_count }}
            </el-tag>
          </template>
          <span class="row-time">{{ fmtTime(c.updated_at) }}</span>
        </div>
      </div>
    </el-card>

    <!-- 系统状态 -->
    <el-card class="section" shadow="never">
      <template #header>
        <span class="section-title">⚙️ 关于</span>
      </template>
      <p class="about-text">
        <strong>钉铆</strong> · MVP 阶段，覆盖<strong>合同审查</strong>与<strong>变更扯皮</strong>两个场景。
      </p>
      <p class="about-text muted">钉是钉，铆是铆 —— 讲法律，讲合规，不打马虎眼。</p>
      <p class="about-text muted">
        ⚠️ 所有 AI 输出仅供参考，不构成法律意见。重大决策请咨询执业律师。
      </p>
    </el-card>
  </div>
</template>

<style scoped>
.dashboard {
  padding: 24px;
  max-width: 1100px;
  margin: 0 auto;
}

.hero {
  margin-bottom: 20px;
}

.hero h2 {
  margin: 0 0 6px 0;
  font-size: 20px;
  color: #303133;
}

.hero-sub {
  margin: 0;
  color: #909399;
  font-size: 14px;
}

.section {
  margin-bottom: 16px;
  border: 1px solid #ebeef5;
}

.section-title {
  font-weight: 600;
  color: #303133;
}

.card-head {
  display: flex;
  align-items: center;
}

.spacer {
  flex: 1;
}

.ml-4 {
  margin-left: 4px;
}

/* 项目卡片网格 */
.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.project-card {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.15s;
}

.project-card:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.12);
}

.pc-name {
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-code {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}

.pc-meta {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #606266;
}

.pc-money {
  color: #e6a23c;
  font-weight: 600;
}

/* 列表行 */
.row-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s;
}

.row-item:hover {
  background: #f5f7fa;
}

.row-id {
  color: #909399;
  font-size: 12px;
  min-width: 36px;
}

.row-main {
  color: #303133;
  font-size: 14px;
  font-weight: 500;
}

.row-scene {
  color: #409eff;
  font-size: 13px;
}

.row-meta,
.row-time {
  color: #909399;
  font-size: 12px;
}

.about-text {
  margin: 0 0 6px 0;
  font-size: 13px;
  color: #606266;
  line-height: 1.7;
}

.about-text.muted {
  color: #909399;
}
</style>
