<script setup lang="ts">
// 律师问诊 —— consultation-ui.md 定稿布局
//
// 核心判断（§二）：**问诊不是聊天**。产品定义是「结构化多轮事实采集，
// 禁止自由提问」，界面主角应是「待查事项清单」的完成度，对话只是手段。
//
// 布局：左栏 380px「采集进度」恒定可见 + 右栏分段控件 [对话][结论][文书]。
// 左栏恒定是关键——回答追问时也能看见"还差什么"。
import { computed, nextTick, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { ElMessage, ElMessageBox } from "element-plus"
import ConsultationFactsPanel from "@/components/ConsultationFactsPanel.vue"
import ConsultationConclusionCard from "@/components/ConsultationConclusionCard.vue"
import {
  confirmReport,
  createConsultation,
  generateReportStream,
  getConsultation,
  listMessages,
  postMessage,
  type Consultation,
  type ConsultationMessage,
  type EvidenceWarning,
} from "@/api/consultation"

const route = useRoute()
const router = useRouter()
const consultationId = computed(() => Number(route.params.id))

// ===== 状态 =====
const consultation = ref<Consultation | null>(null)
const messages = ref<ConsultationMessage[]>([])
const chatInput = ref("")
const sending = ref(false)
const loadError = ref("")

// 报告生成
const reportText = ref("")
const errorMsg = ref("")
const streaming = ref(false)
const disclaimer = ref("")
const warnings = ref<EvidenceWarning[]>([])
const aborted = ref(false)
let streamController: AbortController | null = null

const messagesScrollRef = ref<HTMLElement | null>(null)

/** 右栏分段（§3.1 方案 A） */
type Pane = "chat" | "conclusions" | "artifacts"
const pane = ref<Pane>("chat")

/** 生成中显示流式预览 */
const generating = computed(
  () =>
    streaming.value ||
    ["generating_report", "generating_artifacts"].includes(step.value)
)

// ===== 派生 =====
const scenarioLabel = computed(() => {
  const s = consultation.value?.scenario
  if (s === "variation") return "变更扯皮"
  if (s === "contract_review") return "合同审查"
  return "问诊"
})
const scenarioKind = computed(() => consultation.value?.scenario ?? "")
const step = computed(() => consultation.value?.current_step ?? "init")
const status = computed(() => consultation.value?.status ?? "unknown")
const facts = computed(() => consultation.value?.facts ?? [])
const progress = computed(() => consultation.value?.fact_progress ?? null)
const conclusions = computed(() => consultation.value?.conclusions ?? [])
const artifacts = computed(
  () => (consultation.value as { artifacts?: unknown[] } | null)?.artifacts ?? []
)
const hasReport = computed(() => conclusions.value.length > 0)

const statusLabel = computed(() => {
  const map: Record<string, string> = {
    in_progress: "进行中",
    completed: "已完成",
    abandoned: "已废弃",
    failed: "生成失败",
  }
  return map[status.value] ?? status.value
})
const statusTagType = computed(() => {
  if (status.value === "completed") return "success"
  if (status.value === "failed") return "danger"
  return "warning"
})

/** 5 步步骤条（§5.3，只展示不可点击） */
const STEPS = [
  { key: "collecting_facts", label: "采集事实" },
  { key: "awaiting_confirm", label: "确认" },
  { key: "generating_report", label: "生成报告" },
  { key: "generating_artifacts", label: "生成文书" },
  { key: "done", label: "完成" },
] as const
const activeStep = computed(() => {
  const s = step.value
  if (s === "init" || s === "await_text") return 0
  if (s === "failed") return 2 // 停在"生成报告"并标红
  const i = STEPS.findIndex((x) => x.key === s)
  return i >= 0 ? i : 0
})
const stepFailed = computed(() => step.value === "failed")

const riskStats = computed(() => {
  const s = { red: 0, yellow: 0, green: 0 }
  for (const c of conclusions.value) {
    if (c.level === "red") s.red += 1
    else if (c.level === "yellow") s.yellow += 1
    else if (c.level === "green") s.green += 1
  }
  return s
})

/** 主按钮文案（§5.1 随状态 morph） */
const primaryAction = computed(() => {
  if (stepFailed.value) return { label: "重试生成", kind: "retry" as const }
  if (generating.value) return { label: "停止生成", kind: "stop" as const }
  if (step.value === "done") return { label: "", kind: "none" as const }
  if (step.value === "awaiting_confirm")
    return { label: "确认生成报告", kind: "confirm" as const }
  return { label: "生成报告", kind: "generate" as const }
})

const inputPlaceholder = computed(() => {
  if (status.value === "completed")
    return "本问诊已生成报告。如需继续追问，请点右上角「新建问诊」"
  if (scenarioKind.value === "variation")
    return "补充变更事实，或回答 AI 的追问（Ctrl+Enter 发送）"
  return "粘贴合同条款，或回答 AI 的追问（Ctrl+Enter 发送）"
})
const inputDisabled = computed(
  () => sending.value || status.value === "completed" || generating.value
)

const evidenceWarnings = computed(
  () => consultation.value?.evidence_warnings ?? warnings.value
)
/** 全局依据缺失提示（不是单条结论的问题，而是知识库整体没料） */
const globalBasisGap = computed(() => {
  const w = evidenceWarnings.value
  if (!w.length) return ""
  const noBasis = w.filter((x) => x.type === "no_candidate_basis").length
  const missingVer = w.filter((x) => x.type.startsWith("missing_")).length
  if (missingVer)
    return `知识库中 ${missingVer} 条引用因缺少版本号/生效日期被隐去（应用原则 3：引用过期条文等同误导）`
  if (noBasis) return `${noBasis} 条结论在知识库中无对应条款，已标注「无明确依据」`
  return ""
})

// ===== 数据加载 =====
async function scrollToBottom() {
  await nextTick()
  if (messagesScrollRef.value) {
    messagesScrollRef.value.scrollTop = messagesScrollRef.value.scrollHeight
  }
}

async function loadAll() {
  try {
    const [c, m] = await Promise.all([
      getConsultation(consultationId.value),
      listMessages(consultationId.value),
    ])
    consultation.value = c
    messages.value = m
    // 默认分段跟着状态走（§3.1）
    pane.value = c.conclusions.length ? "conclusions" : "chat"
    await scrollToBottom()
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : "加载问诊失败"
  }
}

onMounted(loadAll)
watch(consultationId, loadAll)

// ===== 对话 =====
async function sendMessage() {
  if (!chatInput.value.trim() || sending.value) return
  const userContent = chatInput.value
  const tempId = -Date.now()
  messages.value.push({
    id: tempId,
    consultation_id: consultationId.value,
    role: "user",
    content: userContent,
    created_at: new Date().toISOString(),
  })
  chatInput.value = ""
  await scrollToBottom()

  sending.value = true
  try {
    const resp = await postMessage(consultationId.value, userContent)
    messages.value = messages.value.filter((m) => m.id !== tempId)
    const now = new Date().toISOString()
    messages.value.push(
      {
        id: resp.user_message_id,
        consultation_id: consultationId.value,
        role: "user",
        content: userContent,
        created_at: now,
      },
      {
        id: resp.assistant_message_id,
        consultation_id: consultationId.value,
        role: "assistant",
        content: resp.assistant_content,
        created_at: now,
      }
    )
    await scrollToBottom()

    if (resp.extraction_error) {
      ElMessage.warning(`事实抽取失败，本轮内容未结构化：${resp.extraction_error}`)
    } else if (resp.new_fact_labels.length) {
      ElMessage.success(`已记下：${resp.new_fact_labels.join("、")}`)
    }
    if (resp.ready_to_report) {
      ElMessage.success("必填事实已齐，可以生成报告了")
    }
    consultation.value = await getConsultation(consultationId.value)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "发送失败")
    messages.value = messages.value.filter((m) => m.id !== tempId)
  } finally {
    sending.value = false
  }
}

// ===== 生成报告 =====
async function handlePrimary() {
  const a = primaryAction.value
  if (a.kind === "stop") return stopStreaming()
  if (a.kind === "none") return
  if (a.kind === "generate") {
    const missing = progress.value?.missing_required ?? []
    if (missing.length) {
      const labels = missing.map(
        (k) => progress.value?.registry.find((s) => s.fact_key === k)?.fact_label ?? k
      )
      try {
        await ElMessageBox.confirm(
          `还差 ${missing.length} 项必填事实（${labels.join("、")}），先补齐质量更高。仍要生成？`,
          "确认生成",
          { confirmButtonText: "仍要生成", cancelButtonText: "先去补充" }
        )
      } catch {
        return
      }
    } else {
      try {
        await ElMessageBox.confirm(
          "AI 将基于当前所有事实和对话生成完整报告，是否继续？",
          "生成报告",
          { confirmButtonText: "生成", cancelButtonText: "再聊一会" }
        )
      } catch {
        return
      }
    }
  }
  await startStreaming()
}

async function startStreaming() {
  if (streaming.value) return
  reportText.value = ""
  errorMsg.value = ""
  warnings.value = []
  aborted.value = false
  streaming.value = true
  streamController = new AbortController()

  try {
    // 状态机迁移 #6：先留痕「用户已确认」
    const cf = await confirmReport(consultationId.value)
    consultation.value = await getConsultation(consultationId.value)
    if (cf.missing_required.length) {
      ElMessage.warning(`提前生成：仍缺 ${cf.missing_required.length} 项必填事实`)
    }
  } catch (e) {
    streaming.value = false
    streamController = null
    ElMessage.error(e instanceof Error ? e.message : "确认生成失败")
    return
  }

  try {
    for await (const ev of generateReportStream(
      consultationId.value,
      streamController.signal
    )) {
      if (ev.type === "chunk") {
        reportText.value += ev.text
      } else if (ev.type === "reset") {
        // 后端重试：清掉半截内容
        reportText.value = ""
      } else if (ev.type === "done") {
        if (ev.disclaimer) disclaimer.value = ev.disclaimer
        if (ev.warnings) warnings.value = ev.warnings
        reportText.value = ""
        consultation.value = await getConsultation(consultationId.value)
        pane.value = "conclusions"
      } else if (ev.type === "error") {
        errorMsg.value = ev.message
        consultation.value = await getConsultation(consultationId.value)
      }
    }
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      aborted.value = true
      reportText.value = ""
      ElMessage.info("已取消生成")
    } else {
      errorMsg.value = `流中断: ${e instanceof Error ? e.message : "未知错误"}`
    }
  } finally {
    streaming.value = false
    streamController = null
  }
}

function stopStreaming() {
  streamController?.abort()
}

async function newChat() {
  try {
    await ElMessageBox.confirm(
      "新建问诊会开启一个全新的对话上下文，原问诊记录会保留，是否继续？",
      "新建问诊",
      { confirmButtonText: "新建", cancelButtonText: "取消" }
    )
  } catch {
    return
  }
  if (!consultation.value) return
  try {
    const c = await createConsultation(
      consultation.value.project_id,
      consultation.value.scenario
    )
    router.push(`/consultation/${c.id}`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "新建失败")
  }
}

function backToProject() {
  const pid = consultation.value?.project_id
  if (pid) router.push(`/projects/${pid}`)
  else router.push("/projects")
}
</script>

<template>
  <div class="consultation">
    <!-- 顶部：返回 + 标题 + 状态 -->
    <header class="topbar">
      <el-page-header
        :title="`问诊 #${consultationId}`"
        :content="scenarioLabel"
        @back="backToProject"
      />
      <div class="spacer" />
      <el-tag size="small" :type="statusTagType">{{ statusLabel }}</el-tag>
      <el-button size="small" class="ml-8" @click="newChat">新建问诊</el-button>
    </header>

    <el-alert
      v-if="loadError"
      :title="`加载问诊失败：${loadError}`"
      type="error"
      :closable="false"
      show-icon
      class="mb-12"
    >
      <template #default>
        <el-button size="small" class="mt-8" @click="backToProject">
          返回项目
        </el-button>
      </template>
    </el-alert>

    <template v-else>
      <!-- 步骤条（§5.3 只展示，不可点击回退） -->
      <ol class="stepper" :class="{ failed: stepFailed }">
        <li
          v-for="(s, i) in STEPS"
          :key="s.key"
          class="stepper-item"
          :class="{ active: i === activeStep, done: i < activeStep }"
        >
          <span class="dot">{{ i < activeStep ? "✓" : i + 1 }}</span>
          <span class="step-label">{{ s.label }}</span>
        </li>
      </ol>

      <!-- 两栏主体 -->
      <div class="panes">
        <ConsultationFactsPanel
          :progress="progress"
          :facts="facts"
          :step="step"
          :busy="generating"
          @confirm="handlePrimary"
        />

        <section class="pane-right">
          <!-- 分段控件（§3.1 方案 A） -->
          <div class="segments">
            <button
              class="seg"
              :class="{ on: pane === 'chat' }"
              @click="pane = 'chat'"
            >
              对话
              <span v-if="messages.length" class="seg-n">{{ messages.length }}</span>
            </button>
            <button
              class="seg"
              :class="{ on: pane === 'conclusions' }"
              :disabled="!hasReport && !generating"
              @click="pane = 'conclusions'"
            >
              结论
              <span v-if="conclusions.length" class="seg-n">{{
                conclusions.length
              }}</span>
            </button>
            <button
              class="seg"
              :class="{ on: pane === 'artifacts' }"
              :disabled="!artifacts.length"
              @click="pane = 'artifacts'"
            >
              文书
              <span v-if="artifacts.length" class="seg-n">{{ artifacts.length }}</span>
            </button>
            <div class="spacer" />
            <span v-if="generating" class="seg-status">
              <span class="spin" />{{ step === "generating_artifacts" ? "生成文书中" : "生成报告中" }}
            </span>
          </div>

          <div class="pane-body">
            <!-- ===== 对话 ===== -->
            <template v-if="pane === 'chat'">
              <div ref="messagesScrollRef" class="chat-scroll">
                <el-alert
                  title="⚠️ 本对话由 AI 引导，结论仅供参考，重大决策请由执业律师复核。"
                  type="warning"
                  :closable="false"
                  class="mb-12"
                />
                <div v-if="!messages.length" class="empty-hint">
                  <el-empty
                    :description="`描述你的${scenarioKind === 'variation' ? '变更争议' : '合同条款'}，AI 会逐项追问补齐事实`"
                    :image-size="72"
                  />
                </div>
                <div
                  v-for="m in messages"
                  :key="m.id"
                  class="msg"
                  :class="[`msg-${m.role}`]"
                >
                  <div class="avatar">
                    {{ m.role === "user" ? "我" : m.role === "system" ? "!" : "AI" }}
                  </div>
                  <div class="bubble">
                    <div class="content">{{ m.content }}</div>
                    <div class="time">{{ m.created_at.slice(11, 16) }}</div>
                  </div>
                </div>
                <div v-if="sending" class="msg msg-assistant">
                  <div class="avatar">AI</div>
                  <div class="bubble bubble-typing">
                    <span class="dot-typing" /><span class="dot-typing" /><span
                      class="dot-typing"
                    />
                  </div>
                </div>
              </div>
            </template>

            <!-- ===== 结论 ===== -->
            <template v-else-if="pane === 'conclusions'">
              <el-alert
                :title="
                  disclaimer ||
                  '⚠️ 以下报告仅供参考，重大决策请咨询执业律师复核。'
                "
                type="warning"
                :closable="false"
                show-icon
                class="mb-12"
              />
              <el-alert
                v-if="globalBasisGap"
                :title="globalBasisGap"
                type="info"
                :closable="false"
                show-icon
                class="mb-12"
              />

              <!-- 生成中：流式预览 -->
              <div v-if="generating" class="stream-preview">
                <pre class="stream-text">{{ reportText
                  }}<span class="cursor">▊</span></pre>
              </div>

              <template v-else-if="hasReport">
                <div class="overview">
                  <el-tag v-if="riskStats.red" type="danger" size="large">
                    🔴 红线 {{ riskStats.red }}
                  </el-tag>
                  <el-tag
                    v-if="riskStats.yellow"
                    type="warning"
                    size="large"
                    class="ml-8"
                  >
                    🟡 黄区 {{ riskStats.yellow }}
                  </el-tag>
                  <el-tag
                    v-if="riskStats.green"
                    type="success"
                    size="large"
                    class="ml-8"
                  >
                    🟢 可控 {{ riskStats.green }}
                  </el-tag>
                </div>

                <ConsultationConclusionCard
                  v-for="(c, i) in conclusions"
                  :key="c.id"
                  :conclusion="c"
                  :facts="facts"
                  :warnings="evidenceWarnings"
                  :index="i"
                />

                <el-alert
                  v-if="consultation?.dispute_summary_ai"
                  :title="consultation.dispute_summary_ai"
                  type="success"
                  :closable="false"
                  show-icon
                  class="mt-8"
                />
              </template>

              <el-empty v-else description="还没有生成结论" :image-size="72" />
            </template>

            <!-- ===== 文书（第二轮落地，§4.5）===== -->
            <template v-else>
              <el-empty
                description="文书功能将在下一轮落地（5 类：签证单 / 索赔报告 / 监理通知单 / 工作联系单 / 审查意见备忘录）"
                :image-size="72"
              />
            </template>

            <el-alert
              v-if="errorMsg"
              :title="errorMsg"
              type="error"
              :closable="false"
              show-icon
              class="mt-12"
            />
            <el-alert
              v-if="aborted"
              title="已取消生成，可再次点击「生成报告」重试"
              type="info"
              :closable="false"
              show-icon
              class="mt-12"
            />
          </div>
        </section>
      </div>

      <!-- 输入区 -->
      <footer v-if="pane === 'chat'" class="input-bar">
        <el-input
          v-model="chatInput"
          type="textarea"
          :rows="2"
          :placeholder="inputPlaceholder"
          :disabled="inputDisabled"
          @keydown.ctrl.enter.prevent="sendMessage"
          @keydown.meta.enter.prevent="sendMessage"
        />
        <div class="input-actions">
          <small class="hint">
            <template v-if="progress && progress.missing_required.length">
              还差 {{ progress.missing_required.length }} 项必填：{{
                progress.missing_required
                  .map(
                    (k) =>
                      progress.registry.find((s) => s.fact_key === k)?.fact_label ?? k
                  )
                  .join("、")
              }}
            </template>
            <template v-else-if="progress">必填事实已齐</template>
          </small>
          <div class="spacer" />
          <el-button
            type="primary"
            :loading="sending"
            :disabled="!chatInput.trim() || inputDisabled"
            @click="sendMessage"
          >
            发送
          </el-button>
          <el-button
            v-if="primaryAction.kind !== 'none'"
            :type="primaryAction.kind === 'stop' ? 'danger' : 'success'"
            :plain="primaryAction.kind === 'stop'"
            :loading="streaming"
            :disabled="sending || generating"
            class="ml-8"
            @click="handlePrimary"
          >
            {{ primaryAction.label }}
          </el-button>
        </div>
      </footer>
    </template>
  </div>
</template>

<style scoped>
.consultation {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 20px 24px;
  background: #f5f7fa;
  --pane-h: max(420px, calc(100vh - 300px));
}

.topbar {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.spacer {
  flex: 1;
}
.mb-12 {
  margin-bottom: 12px;
}
.mt-8 {
  margin-top: 8px;
}
.mt-12 {
  margin-top: 12px;
}
.ml-8 {
  margin-left: 8px;
}

/* ===== 步骤条 ===== */
.stepper {
  display: flex;
  align-items: center;
  gap: 4px;
  list-style: none;
  margin: 0 0 12px;
  padding: 8px 14px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  flex-shrink: 0;
  overflow-x: auto;
}
.stepper-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: #c0c4cc;
  white-space: nowrap;
}
.stepper-item:not(:last-child)::after {
  content: "─";
  margin: 0 6px;
  color: #e4e7ed;
}
.stepper-item .dot {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #f0f2f5;
  color: #909399;
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stepper-item.done {
  color: #67c23a;
}
.stepper-item.done .dot {
  background: #f0f9eb;
  color: #67c23a;
}
.stepper-item.active {
  color: #409eff;
  font-weight: 600;
}
.stepper-item.active .dot {
  background: #409eff;
  color: #fff;
}
.stepper.failed .stepper-item.active {
  color: #f56c6c;
}
.stepper.failed .stepper-item.active .dot {
  background: #f56c6c;
}

/* ===== 两栏 ===== */
.panes {
  display: flex;
  gap: 12px;
  flex: 1;
  min-height: 0;
  align-items: flex-start;
}
.pane-right {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: var(--pane-h);
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.segments {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 12px;
  border-bottom: 1px solid #ebeef5;
  flex-shrink: 0;
  background: #fafcff;
}
.seg {
  border: none;
  background: transparent;
  font-size: 13px;
  color: #606266;
  padding: 5px 12px;
  border-radius: 5px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 5px;
}
.seg:hover:not(:disabled) {
  background: #ecf5ff;
  color: #409eff;
}
.seg.on {
  background: #409eff;
  color: #fff;
  font-weight: 600;
}
.seg:disabled {
  color: #c0c4cc;
  cursor: not-allowed;
}
.seg-n {
  font-size: 11px;
  background: rgba(0, 0, 0, 0.08);
  border-radius: 8px;
  padding: 0 5px;
  font-variant-numeric: tabular-nums;
}
.seg.on .seg-n {
  background: rgba(255, 255, 255, 0.28);
}
.seg-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #e6a23c;
}
.spin {
  width: 10px;
  height: 10px;
  border: 2px solid #f3d19e;
  border-top-color: #e6a23c;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.pane-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px 16px;
}

/* ===== 对话 ===== */
.chat-scroll {
  min-height: 100%;
}
.empty-hint {
  padding-top: 40px;
}
.msg {
  display: flex;
  margin-bottom: 16px;
  align-items: flex-start;
  gap: 10px;
}
.msg-user {
  flex-direction: row-reverse;
}
.avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  background: #67c23a;
}
.msg-user .avatar {
  background: #409eff;
}
.msg-system .avatar {
  background: #e6a23c;
}
.bubble {
  max-width: 76%;
  padding: 10px 14px;
  border-radius: 8px;
  background: #f4f4f5;
  color: #303133;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-user .bubble {
  background: #409eff;
  color: #fff;
}
.msg-system .bubble {
  background: #fdf6ec;
  color: #b88230;
}
.bubble .time {
  margin-top: 4px;
  font-size: 11px;
  color: #909399;
  text-align: right;
}
.msg-user .bubble .time {
  color: rgba(255, 255, 255, 0.75);
}
.bubble-typing {
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 14px;
}
.dot-typing {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #909399;
  animation: typing 1.4s infinite ease-in-out;
}
.dot-typing:nth-child(2) {
  animation-delay: 0.2s;
}
.dot-typing:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes typing {
  0%,
  60%,
  100% {
    transform: scale(0.8);
    opacity: 0.5;
  }
  30% {
    transform: scale(1.2);
    opacity: 1;
  }
}

/* ===== 结论 ===== */
.overview {
  display: flex;
  align-items: center;
  margin-bottom: 14px;
}
.stream-preview {
  background: #fafafa;
  border-radius: 4px;
  padding: 12px;
}
.stream-text {
  margin: 0;
  font-family: "Menlo", "Monaco", monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #606266;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 60vh;
  overflow-y: auto;
}
.cursor {
  animation: blink 1s step-end infinite;
  color: #409eff;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}

/* ===== 输入区 ===== */
.input-bar {
  margin-top: 12px;
  background: #fff;
  border-radius: 8px;
  padding: 10px 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  flex-shrink: 0;
}
.input-actions {
  display: flex;
  align-items: center;
  margin-top: 8px;
}
.hint {
  color: #909399;
  font-size: 12px;
}

/* ===== 窄屏（<1280px）：左栏折叠到顶部 ===== */
@media (max-width: 1280px) {
  .consultation {
    --pane-h: max(360px, calc(100vh - 420px));
  }
  .panes {
    flex-direction: column;
  }
}
</style>
