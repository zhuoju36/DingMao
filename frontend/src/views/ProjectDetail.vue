<script setup lang="ts">
// 项目详情 - 项目元数据 + 各场景历史问诊
import { computed, onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { ElMessage, ElMessageBox } from "element-plus"
import apiClient from "@/api"
import {
  createConsultation,
  listProjectConsultations,
  type ConsultationListItem,
} from "@/api/consultation"
import { SCENARIOS } from "@/constants/scenarios"
import type { UserRole } from "@/stores/user"

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
  role: UserRole
}

// 角色中文标签（与 Projects/AppLayout 同步）
const roleLabels: Record<UserRole, string> = {
  owner: "业主/建设单位",
  designer: "设计单位",
  supervisor: "监理单位",
  contractor: "施工单位",
  subcontractor: "其他分包商",
}

const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.id))

const project = ref<Project | null>(null)
const loading = ref(false)
const loadError = ref("")
const activeTab = ref("overview")
const starting = ref<string | null>(null)

// 各场景的历史问诊
const contractConsultations = ref<ConsultationListItem[]>([])
const variationConsultations = ref<ConsultationListItem[]>([])

const statusMeta: Record<string, { label: string; type: "success" | "warning" | "info" }> = {
  in_progress: { label: "进行中", type: "warning" },
  completed: { label: "已完成", type: "success" },
  abandoned: { label: "已废弃", type: "info" },
}

async function fetchData() {
  loading.value = true
  loadError.value = ""
  try {
    project.value = await apiClient.get<Project>(`/projects/${projectId.value}`)
    const [c1, c2] = await Promise.all([
      listProjectConsultations(projectId.value, "contract_review"),
      listProjectConsultations(projectId.value, "variation"),
    ])
    contractConsultations.value = c1
    variationConsultations.value = c2
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : "加载项目失败"
  } finally {
    loading.value = false
  }
}

/**
 * 开始问诊（智能续聊）：
 * - 若该场景下有「进行中」的问诊 → 弹窗让用户选择继续/新建
 * - 否则直接新建
 */
async function startConsultation(scenario: "contract_review" | "variation") {
  const existing =
    scenario === "contract_review" ? contractConsultations.value : variationConsultations.value
  const inProgress = existing.find((c) => c.status === "in_progress")

  if (inProgress) {
    try {
      await ElMessageBox.confirm(
        `该场景下有一个进行中的问诊 #${inProgress.id}（已采集 ${inProgress.fact_count} 条事实）。要继续它，还是新建一个？`,
        "继续还是新建？",
        {
          distinguishCancelAndClose: true,
          confirmButtonText: "继续上次",
          cancelButtonText: "新建问诊",
          type: "info",
        }
      )
      // 确认 = 继续
      router.push(`/consultation/${inProgress.id}`)
      return
    } catch (action) {
      if (action === "cancel") {
        // 取消按钮 = 新建，继续往下走
      } else {
        return // 关闭弹窗 = 什么都不做
      }
    }
  }

  starting.value = scenario
  try {
    const created = await createConsultation(projectId.value, scenario)
    ElMessage.success(`问诊已创建 #${created.id}`)
    router.push(`/consultation/${created.id}`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "创建失败")
  } finally {
    starting.value = null
  }
}

function openConsultation(id: number) {
  router.push(`/consultation/${id}`)
}

function fmt(v: string | null | undefined) {
  return v && v.length > 0 ? v : "—"
}

function fmtMoney(v: string | null | undefined) {
  return v ? `¥ ${Number(v).toLocaleString()}` : "—"
}

function fmtTime(v: string) {
  // 后端返回 ISO，展示为 YYYY-MM-DD HH:MM
  return v ? v.slice(0, 16).replace("T", " ") : "—"
}

// 本项目下各场景的统计（供概览页场景网格使用）
const scenarioTiles = computed(() => {
  const byScenario: Record<string, ConsultationListItem[]> = {
    contract_review: contractConsultations.value,
    variation: variationConsultations.value,
  }
  return SCENARIOS.map((s) => {
    const list = byScenario[s.key] ?? []
    return {
      ...s,
      total: list.length,
      inProgress: list.filter((c) => c.status === "in_progress").length,
      reportCount: list.filter((c) => c.conclusion_count > 0).length,
    }
  })
})

/** 概览页点场景卡片：可用的切到对应 Tab，规划中的提示 */
function onTileClick(key: string, status: string) {
  if (status !== "available") {
    ElMessage.info("该场景正在规划中，敬请期待")
    return
  }
  activeTab.value = key === "contract_review" ? "contract" : "variation"
}

/** 从概览的「全部问诊」入口跳到场景中心 */
function goScenarioCenter() {
  router.push("/scenarios")
}

onMounted(fetchData)
</script>

<template>
  <div class="project-detail">
    <el-page-header @back="router.push('/projects')" class="mb-16">
      <template #content>
        <span class="page-title">{{ project?.name || `项目 #${projectId}` }}</span>
      </template>
    </el-page-header>

    <el-alert
      v-if="loadError"
      :title="`加载项目失败：${loadError}`"
      type="error"
      :closable="false"
      show-icon
      class="mb-16"
    />

    <div v-loading="loading">
      <el-tabs v-model="activeTab">
        <!-- 概览 -->
        <el-tab-pane label="概览" name="overview">
          <el-empty v-if="!project && !loading" description="项目不存在或加载失败" />
          <template v-else-if="project">
            <!-- 场景卡片网格：本项目在各场景下的事务 -->
            <div class="section-head">
              <span class="section-title">本项目下场景</span>
              <div class="spacer" />
              <el-button text type="primary" size="small" @click="goScenarioCenter">
                场景中心（跨项目）→
              </el-button>
            </div>

            <div class="tile-grid mb-16">
              <div
                v-for="t in scenarioTiles"
                :key="t.key"
                :class="['tile', { planned: t.status !== 'available' }]"
                @click="onTileClick(t.key, t.status)"
              >
                <div class="tile-head">
                  <span class="tile-icon">{{ t.icon }}</span>
                  <span class="tile-name">{{ t.name }}</span>
                  <div class="spacer" />
                  <el-tag v-if="t.status !== 'available'" size="small" type="info">
                    规划中
                  </el-tag>
                  <el-tag v-else-if="t.inProgress" size="small" type="warning">
                    {{ t.inProgress }} 待继续
                  </el-tag>
                </div>
                <div class="tile-metrics">
                  <template v-if="t.status === 'available'">
                    <span>{{ t.total }} 条问诊</span>
                    <span v-if="t.reportCount">· {{ t.reportCount }} 份报告</span>
                    <span v-else-if="!t.total" class="muted">尚未开始</span>
                  </template>
                  <span v-else class="muted">{{ t.description }}</span>
                </div>
              </div>
            </div>

            <div class="section-head">
              <span class="section-title">项目信息</span>
            </div>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="项目名称">{{ fmt(project.name) }}</el-descriptions-item>
              <el-descriptions-item label="我在本项目">
                <el-tag size="small">{{ roleLabels[project.role] ?? project.role }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="工程编号">{{ fmt(project.code) }}</el-descriptions-item>
              <el-descriptions-item label="工程地点">{{ fmt(project.location) }}</el-descriptions-item>
              <el-descriptions-item label="合同金额">{{ fmtMoney(project.contract_amount) }}</el-descriptions-item>
              <el-descriptions-item label="工期天数">{{ fmt(project.contract_duration_days?.toString()) }}</el-descriptions-item>
              <el-descriptions-item label="开工日期">{{ fmt(project.contract_start_date) }}</el-descriptions-item>
              <el-descriptions-item label="竣工日期">{{ fmt(project.contract_end_date) }}</el-descriptions-item>
              <el-descriptions-item label="建设单位">{{ fmt(project.owner_org) }}</el-descriptions-item>
              <el-descriptions-item label="施工单位">{{ fmt(project.contractor_org) }}</el-descriptions-item>
              <el-descriptions-item label="设计单位">{{ fmt(project.design_org) }}</el-descriptions-item>
              <el-descriptions-item label="监理单位">{{ fmt(project.supervisor_org) }}</el-descriptions-item>
              <el-descriptions-item v-if="project.description" label="项目描述" :span="2">
                {{ project.description }}
              </el-descriptions-item>
            </el-descriptions>
          </template>
        </el-tab-pane>

        <!-- 合同审查 -->
        <el-tab-pane name="contract">
          <template #label>
            合同审查
            <el-badge
              v-if="contractConsultations.length"
              :value="contractConsultations.length"
              class="tab-badge"
            />
          </template>

          <el-empty
            v-if="contractConsultations.length === 0"
            description="还没有合同审查记录"
          />
          <div v-else class="consult-list">
            <div
              v-for="c in contractConsultations"
              :key="c.id"
              class="consult-item"
              @click="openConsultation(c.id)"
            >
              <div class="item-head">
                <span class="item-id">#{{ c.id }}</span>
                <el-tag size="small" :type="statusMeta[c.status]?.type ?? 'info'">
                  {{ statusMeta[c.status]?.label ?? c.status }}
                </el-tag>
                <span class="item-time">{{ fmtTime(c.created_at) }}</span>
                <div class="spacer" />
                <el-button text type="primary" size="small">
                  {{ c.status === "completed" ? "查看报告" : "继续对话" }}
                </el-button>
              </div>
              <div v-if="c.summary" class="item-summary">{{ c.summary }}</div>
              <div class="item-stats">
                <span>事实 {{ c.fact_count }}</span>
                <template v-if="c.conclusion_count">
                  <el-tag v-if="c.red_count" type="danger" size="small" class="ml-8">
                    红线 {{ c.red_count }}
                  </el-tag>
                  <el-tag v-if="c.yellow_count" type="warning" size="small" class="ml-8">
                    黄区 {{ c.yellow_count }}
                  </el-tag>
                  <el-tag v-if="c.green_count" type="success" size="small" class="ml-8">
                    可控 {{ c.green_count }}
                  </el-tag>
                </template>
                <span v-else class="muted ml-8">尚未生成报告</span>
              </div>
            </div>
          </div>

          <el-button
            type="primary"
            class="mt-16"
            :loading="starting === 'contract_review'"
            @click="startConsultation('contract_review')"
          >
            <el-icon><Plus /></el-icon>
            {{ contractConsultations.length ? "开始新合同审查" : "开始合同审查" }}
          </el-button>
        </el-tab-pane>

        <!-- 变更扯皮 -->
        <el-tab-pane name="variation">
          <template #label>
            变更扯皮
            <el-badge
              v-if="variationConsultations.length"
              :value="variationConsultations.length"
              class="tab-badge"
            />
          </template>

          <el-empty
            v-if="variationConsultations.length === 0"
            description="还没有变更扯皮记录"
          />
          <div v-else class="consult-list">
            <div
              v-for="c in variationConsultations"
              :key="c.id"
              class="consult-item"
              @click="openConsultation(c.id)"
            >
              <div class="item-head">
                <span class="item-id">#{{ c.id }}</span>
                <el-tag size="small" :type="statusMeta[c.status]?.type ?? 'info'">
                  {{ statusMeta[c.status]?.label ?? c.status }}
                </el-tag>
                <span class="item-time">{{ fmtTime(c.created_at) }}</span>
                <div class="spacer" />
                <el-button text type="primary" size="small">
                  {{ c.status === "completed" ? "查看报告" : "继续对话" }}
                </el-button>
              </div>
              <div v-if="c.summary" class="item-summary">{{ c.summary }}</div>
              <div class="item-stats">
                <span>事实 {{ c.fact_count }}</span>
                <template v-if="c.conclusion_count">
                  <el-tag v-if="c.red_count" type="danger" size="small" class="ml-8">
                    红线 {{ c.red_count }}
                  </el-tag>
                  <el-tag v-if="c.yellow_count" type="warning" size="small" class="ml-8">
                    黄区 {{ c.yellow_count }}
                  </el-tag>
                  <el-tag v-if="c.green_count" type="success" size="small" class="ml-8">
                    可控 {{ c.green_count }}
                  </el-tag>
                </template>
                <span v-else class="muted ml-8">尚未生成报告</span>
              </div>
            </div>
          </div>

          <el-button
            type="primary"
            class="mt-16"
            :loading="starting === 'variation'"
            @click="startConsultation('variation')"
          >
            <el-icon><Plus /></el-icon>
            {{ variationConsultations.length ? "开始新变更问诊" : "开始变更问诊" }}
          </el-button>
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

.ml-8 {
  margin-left: 8px;
}

.spacer {
  flex: 1;
}

.tab-badge {
  margin-left: 6px;
}

/* 概览页：场景卡片网格 */
.section-head {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
}

.section-title {
  font-weight: 600;
  color: #303133;
  font-size: 14px;
}

.tile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 10px;
}

.tile {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.15s;
  background: #fff;
}

.tile:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.12);
}

.tile.planned {
  background: #fafafa;
  cursor: default;
}

.tile.planned:hover {
  border-color: #ebeef5;
  box-shadow: none;
}

.tile-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}

.tile-icon {
  font-size: 16px;
}

.tile-name {
  font-weight: 600;
  color: #303133;
  font-size: 14px;
}

.tile-metrics {
  display: flex;
  gap: 6px;
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
}

.tile-metrics .muted {
  color: #c0c4cc;
}

/* 问诊列表 */
.consult-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.consult-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px 16px;
  cursor: pointer;
  transition: all 0.15s;
}

.consult-item:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.12);
}

.item-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.item-id {
  font-weight: 600;
  color: #303133;
}

.item-time {
  color: #909399;
  font-size: 12px;
}

.item-summary {
  margin-top: 8px;
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.item-stats {
  margin-top: 8px;
  display: flex;
  align-items: center;
  font-size: 12px;
  color: #909399;
}

.muted {
  color: #c0c4cc;
}
</style>
