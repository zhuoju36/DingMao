<script setup lang="ts">
// 场景中心：按「任务类型」而非「项目」组织工作
//
// 律师/造价/监理的典型用法：
//   早上打开 → 场景中心 → 一次性看完所有项目待处理的合同审查
import { computed, onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { ElMessage } from "element-plus"
import { listMyConsultations, type ConsultationListItem } from "@/api/consultation"
import { SCENARIOS } from "@/constants/scenarios"

const router = useRouter()
const loading = ref(false)
const allConsultations = ref<ConsultationListItem[]>([])

interface ScenarioStat {
  key: string
  name: string
  icon: string
  description: string
  whenToUse: string
  status: "available" | "planned"
  total: number
  inProgress: number
  completed: number
  projectCount: number
  latestAt: string | null
}

const stats = computed<ScenarioStat[]>(() => {
  return SCENARIOS.map((s) => {
    const list = allConsultations.value.filter((c) => c.scenario === s.key)
    const projects = new Set(list.map((c) => c.project_id))
    const latest = list.length
      ? list.reduce((a, b) => (a.updated_at > b.updated_at ? a : b))
      : null
    return {
      ...s,
      total: list.length,
      inProgress: list.filter((c) => c.status === "in_progress").length,
      completed: list.filter((c) => c.status === "completed").length,
      projectCount: projects.size,
      latestAt: latest?.updated_at ?? null,
    }
  })
})

const totalInProgress = computed(() =>
  allConsultations.value.filter((c) => c.status === "in_progress").length
)

async function fetchData() {
  loading.value = true
  try {
    allConsultations.value = await listMyConsultations({ limit: 100 })
  } catch (e) {
    ElMessage.warning("加载场景数据失败，请确认后端已启动")
    console.error(e)
  } finally {
    loading.value = false
  }
}

function openScenario(s: ScenarioStat) {
  if (s.status !== "available") {
    ElMessage.info(`「${s.name}」正在规划中，敬请期待`)
    return
  }
  router.push(`/scenarios/${s.key}`)
}

function fmtTime(v: string | null) {
  if (!v) return "—"
  return v.slice(5, 16).replace("T", " ")
}

onMounted(fetchData)
</script>

<template>
  <div class="scenarios" v-loading="loading">
    <div class="hero">
      <h2>场景中心</h2>
      <p class="hero-sub">
        <template v-if="totalInProgress">
          有 <strong>{{ totalInProgress }}</strong> 个问诊待继续 · 按任务类型跨项目处理
        </template>
        <template v-else> 按任务类型组织工作，跨项目查看同类事务 </template>
      </p>
    </div>

    <div class="grid">
      <div
        v-for="s in stats"
        :key="s.key"
        :class="['scenario-card', { planned: s.status !== 'available' }]"
        @click="openScenario(s)"
      >
        <div class="card-head">
          <span class="icon">{{ s.icon }}</span>
          <span class="name">{{ s.name }}</span>
          <div class="spacer" />
          <el-tag v-if="s.status !== 'available'" size="small" type="info">规划中</el-tag>
          <el-tag v-else-if="s.inProgress" size="small" type="warning">
            {{ s.inProgress }} 待继续
          </el-tag>
        </div>

        <p class="desc">{{ s.description }}</p>

        <div v-if="s.status === 'available'" class="metrics">
          <span class="metric">
            <strong>{{ s.projectCount }}</strong> 个项目
          </span>
          <span class="metric">
            <strong>{{ s.total }}</strong> 条问诊
          </span>
          <span v-if="s.completed" class="metric">
            <strong>{{ s.completed }}</strong> 份报告
          </span>
        </div>
        <div v-else class="metrics">
          <span class="metric muted">适用：{{ s.whenToUse }}</span>
        </div>

        <div class="card-foot">
          <span class="time">
            <template v-if="s.latestAt">最近 {{ fmtTime(s.latestAt) }}</template>
            <template v-else>尚无记录</template>
          </span>
          <div class="spacer" />
          <el-button
            v-if="s.status === 'available'"
            text
            type="primary"
            size="small"
          >
            进入 →
          </el-button>
          <span v-else class="muted small">敬请期待</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scenarios {
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

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.scenario-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 18px 20px;
  cursor: pointer;
  transition: all 0.15s;
  background: #fff;
  display: flex;
  flex-direction: column;
}

.scenario-card:hover {
  border-color: #409eff;
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.12);
  transform: translateY(-1px);
}

.scenario-card.planned {
  background: #fafafa;
  cursor: default;
}

.scenario-card.planned:hover {
  border-color: #ebeef5;
  box-shadow: none;
  transform: none;
}

.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.icon {
  font-size: 20px;
}

.name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.spacer {
  flex: 1;
}

.desc {
  margin: 0 0 12px 0;
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
  min-height: 42px;
}

.metrics {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
  font-size: 12px;
  color: #909399;
}

.metric strong {
  color: #409eff;
  font-size: 15px;
  margin-right: 2px;
}

.metric.muted {
  color: #c0c4cc;
}

.card-foot {
  display: flex;
  align-items: center;
  border-top: 1px solid #f2f6fc;
  padding-top: 10px;
  margin-top: auto;
}

.time {
  font-size: 12px;
  color: #c0c4cc;
}

.muted {
  color: #c0c4cc;
}

.small {
  font-size: 12px;
}
</style>
