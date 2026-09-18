<script setup lang="ts">
// 单场景跨项目视图：把同一类事务集中处理
//
// 例：合同审查场景 → 一次看完所有项目里待审查的合同
import { computed, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { ElMessage } from "element-plus"
import apiClient from "@/api"
import {
  createConsultation,
  listMyConsultations,
  type ConsultationListItem,
} from "@/api/consultation"
import { SCENARIO_MAP } from "@/constants/scenarios"
import type { Project } from "@/types/project"

const route = useRoute()
const router = useRouter()

const scenarioKey = computed(() => String(route.params.scenario))
const scenario = computed(() => SCENARIO_MAP[scenarioKey.value])

const loading = ref(false)
const consultations = ref<ConsultationListItem[]>([])
const projects = ref<Project[]>([])

const filterProject = ref<number | "all">("all")
const filterStatus = ref<string>("all")

const creating = ref(false)
const showNewDialog = ref(false)
const newProjectId = ref<number | null>(null)

const statusMeta: Record<string, { label: string; type: "success" | "warning" | "info" }> = {
  in_progress: { label: "进行中", type: "warning" },
  completed: { label: "已完成", type: "success" },
  abandoned: { label: "已废弃", type: "info" },
}

const filtered = computed(() => {
  return consultations.value.filter((c) => {
    if (filterProject.value !== "all" && c.project_id !== filterProject.value) return false
    if (filterStatus.value !== "all" && c.status !== filterStatus.value) return false
    return true
  })
})

/** 按项目分组，保持「最近更新优先」的顺序 */
const grouped = computed(() => {
  const map = new Map<number, { projectId: number; projectName: string; items: ConsultationListItem[] }>()
  for (const c of filtered.value) {
    let g = map.get(c.project_id)
    if (!g) {
      g = {
        projectId: c.project_id,
        projectName: c.project_name || `项目 #${c.project_id}`,
        items: [],
      }
      map.set(c.project_id, g)
    }
    g.items.push(c)
  }
  return [...map.values()]
})

const totalInProgress = computed(
  () => filtered.value.filter((c) => c.status === "in_progress").length
)

async function fetchData() {
  loading.value = true
  try {
    const [cons, projRes] = await Promise.all([
      listMyConsultations({
        scenario: scenarioKey.value as "contract_review" | "variation",
        limit: 100,
      }),
      apiClient.get<{ items: Project[] }>("/projects?limit=100"),
    ])
    consultations.value = cons
    projects.value = projRes.items
  } catch (e) {
    ElMessage.warning("加载失败，请确认后端已启动")
    console.error(e)
  } finally {
    loading.value = false
  }
}

function openConsultation(id: number) {
  router.push(`/consultation/${id}`)
}

function openNewDialog() {
  newProjectId.value = projects.value[0]?.id ?? null
  showNewDialog.value = true
}

async function confirmNew() {
  if (!newProjectId.value) {
    ElMessage.warning("请选择项目")
    return
  }
  creating.value = true
  try {
    const created = await createConsultation(
      newProjectId.value,
      scenarioKey.value as "contract_review" | "variation"
    )
    showNewDialog.value = false
    router.push(`/consultation/${created.id}`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "创建失败")
  } finally {
    creating.value = false
  }
}

function fmtTime(v: string) {
  return v ? v.slice(0, 16).replace("T", " ") : "—"
}

// 切换场景时重新拉取
watch(scenarioKey, fetchData)
onMounted(fetchData)
</script>

<template>
  <div class="scenario-detail" v-loading="loading">
    <el-page-header @back="router.push('/scenarios')" class="mb-16">
      <template #content>
        <span class="page-title">
          {{ scenario?.icon }} {{ scenario?.name || scenarioKey }}
        </span>
        <span class="page-sub">跨项目</span>
      </template>
    </el-page-header>

    <el-alert
      v-if="!scenario"
      :title="`未知场景：${scenarioKey}`"
      type="warning"
      :closable="false"
      show-icon
      class="mb-16"
    />

    <template v-else>
      <p class="scene-desc">{{ scenario.description }}</p>

      <!-- 过滤条 -->
      <div class="toolbar mb-16">
        <el-select v-model="filterProject" class="filter-select" placeholder="项目">
          <el-option label="全部项目" value="all" />
          <el-option
            v-for="p in projects"
            :key="p.id"
            :label="p.name"
            :value="p.id"
          />
        </el-select>
        <el-select v-model="filterStatus" class="filter-select ml-8" placeholder="状态">
          <el-option label="全部状态" value="all" />
          <el-option label="进行中" value="in_progress" />
          <el-option label="已完成" value="completed" />
        </el-select>
        <el-tag v-if="totalInProgress" type="warning" size="small" class="ml-8">
          {{ totalInProgress }} 个待继续
        </el-tag>
        <div class="spacer" />
        <el-button type="primary" @click="openNewDialog">
          <el-icon><Plus /></el-icon>
          新建{{ scenario.name }}问诊
        </el-button>
      </div>

      <el-empty
        v-if="grouped.length === 0"
        :description="
          consultations.length === 0
            ? `还没有${scenario.name}记录，点击右上角新建`
            : '当前筛选条件下没有记录'
        "
      />

      <!-- 按项目分组 -->
      <div v-for="g in grouped" :key="g.projectId" class="project-group">
        <div class="group-head">
          <span class="group-name">{{ g.projectName }}</span>
          <el-tag size="small" type="info" class="ml-8">{{ g.items.length }} 条</el-tag>
        </div>

        <div
          v-for="c in g.items"
          :key="c.id"
          class="consult-row"
          @click="openConsultation(c.id)"
        >
          <span class="row-id">#{{ c.id }}</span>
          <el-tag size="small" :type="statusMeta[c.status]?.type ?? 'info'">
            {{ statusMeta[c.status]?.label ?? c.status }}
          </el-tag>

          <span class="row-summary">
            {{ c.summary || (c.fact_count ? `已采集 ${c.fact_count} 条事实` : "尚未开始对话") }}
          </span>

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
          <el-button text type="primary" size="small">
            {{ c.status === "completed" ? "查看报告" : "继续对话" }}
          </el-button>
        </div>
      </div>
    </template>

    <!-- 新建问诊：选项目 -->
    <el-dialog v-model="showNewDialog" title="新建问诊" width="480px">
      <el-form label-width="80px">
        <el-form-item label="场景">
          <el-tag>{{ scenario?.name }}</el-tag>
        </el-form-item>
        <el-form-item label="所属项目" required>
          <el-select v-model="newProjectId" placeholder="选择项目" style="width: 100%">
            <el-option
              v-for="p in projects"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showNewDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="confirmNew">
          创建并进入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.scenario-detail {
  padding: 24px;
  max-width: 1100px;
  margin: 0 auto;
}

.page-title {
  font-size: 16px;
  font-weight: 600;
}

.page-sub {
  margin-left: 8px;
  color: #909399;
  font-size: 13px;
}

.scene-desc {
  margin: 0 0 16px 0;
  color: #606266;
  font-size: 13px;
}

.mb-16 {
  margin-bottom: 16px;
}

.ml-4 {
  margin-left: 4px;
}

.ml-8 {
  margin-left: 8px;
}

.spacer {
  flex: 1;
}

.toolbar {
  display: flex;
  align-items: center;
}

.filter-select {
  width: 180px;
}

/* 项目分组 */
.project-group {
  margin-bottom: 20px;
}

.group-head {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 6px;
  margin-bottom: 8px;
}

.group-name {
  font-weight: 600;
  color: #303133;
  font-size: 14px;
}

.consult-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  margin-bottom: 6px;
  cursor: pointer;
  transition: all 0.15s;
  background: #fff;
}

.consult-row:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.1);
}

.row-id {
  color: #909399;
  font-size: 12px;
  min-width: 36px;
}

.row-summary {
  color: #606266;
  font-size: 13px;
  max-width: 380px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-time {
  color: #c0c4cc;
  font-size: 12px;
}
</style>
