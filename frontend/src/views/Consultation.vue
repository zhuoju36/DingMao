<script setup lang="ts">
// 律师问诊：多轮对话 + 报告卡片（持久化展示）
//
// 报告来源：consultation.conclusions（后端已落库）
// —— 关掉页面/刷新/重新进入都能看到，不再依赖弹窗状态
import { computed, nextTick, onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { ElMessage, ElMessageBox } from "element-plus"
import {
  createConsultation,
  generateReportStream,
  getConsultation,
  listMessages,
  postMessage,
  type ConsultationMessage,
} from "@/api/consultation"

const route = useRoute()
const router = useRouter()
const consultationId = computed(() => Number(route.params.id))

// 状态
const consultation = ref<Awaited<ReturnType<typeof getConsultation>> | null>(null)
const messages = ref<ConsultationMessage[]>([])
const chatInput = ref("")
const sending = ref(false)
const loadError = ref("")

// 报告生成
const reportText = ref("")
const errorMsg = ref("")
const streaming = ref(false)
const firstChunkAt = ref<number | null>(null)
const totalChunks = ref(0)
const disclaimer = ref("")
const aborted = ref(false)
let streamController: AbortController | null = null

// 滚动容器
const messagesScrollRef = ref<HTMLElement | null>(null)
const reportCardRef = ref<HTMLElement | null>(null)

const scenarioLabel = computed(() => {
  const s = consultation.value?.scenario
  if (s === "variation") return "变更扯皮"
  if (s === "contract_review") return "合同审查"
  return "问诊"
})

const scenarioKind = computed<"contract_review" | "variation" | "unknown">(() => {
  const s = consultation.value?.scenario
  if (s === "variation" || s === "contract_review") return s
  return "unknown"
})

const status = computed(() => consultation.value?.status ?? "unknown")
const statusLabel = computed(() => {
  const map: Record<string, string> = {
    in_progress: "进行中",
    completed: "已完成",
    abandoned: "已废弃",
  }
  return map[status.value] ?? status.value
})
const factCount = computed(() => consultation.value?.facts.length ?? 0)
const conclusions = computed(() => consultation.value?.conclusions ?? [])
const hasReport = computed(() => conclusions.value.length > 0)

// 报告统计
const riskStats = computed(() => {
  const s = { red: 0, yellow: 0, green: 0 }
  for (const c of conclusions.value) {
    if (c.level === "red") s.red += 1
    else if (c.level === "yellow") s.yellow += 1
    else if (c.level === "green") s.green += 1
  }
  return s
})

const levelMeta: Record<string, { label: string; type: "danger" | "warning" | "success"; icon: string }> = {
  red: { label: "红线", type: "danger", icon: "🔴" },
  yellow: { label: "黄区", type: "warning", icon: "🟡" },
  green: { label: "可控", type: "success", icon: "🟢" },
}

// 输入区文案按场景变
const inputConfig = computed(() => {
  if (scenarioKind.value === "variation") {
    return {
      placeholder: "补充变更事实或回答 AI 的追问（例如：业主临时要求增加的工作内容、签证情况等）",
      hint: "事实越具体，AI 引导越精准。建议主动回答 AI 提出的关键问题。",
    }
  }
  return {
    placeholder: "粘贴合同条款或回答 AI 的追问（例如：付款条件、工期、违约责任等）",
    hint: "AI 会基于你提供的条款逐步识别风险，并主动询问关键问题。",
  }
})

const placeholder = computed(() => inputConfig.value.placeholder)
const hint = computed(() => inputConfig.value.hint)

async function scrollToBottom() {
  await nextTick()
  if (messagesScrollRef.value) {
    messagesScrollRef.value.scrollTop = messagesScrollRef.value.scrollHeight
  }
}

async function loadAll() {
  try {
    consultation.value = await getConsultation(consultationId.value)
    messages.value = await listMessages(consultationId.value)
    await scrollToBottom()
  } catch (e) {
    // P0-1 修复：加载失败不再静默，给出可见错误 + 返回入口
    loadError.value = e instanceof Error ? e.message : "加载问诊失败"
  }
}

onMounted(loadAll)

async function sendMessage() {
  if (!chatInput.value.trim()) return
  if (sending.value) return

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
    messages.value.push({
      id: resp.user_message_id,
      consultation_id: consultationId.value,
      role: "user",
      content: userContent,
      created_at: new Date().toISOString(),
    })
    messages.value.push({
      id: resp.assistant_message_id,
      consultation_id: consultationId.value,
      role: "assistant",
      content: resp.assistant_content,
      created_at: new Date().toISOString(),
    })
    await scrollToBottom()
    consultation.value = await getConsultation(consultationId.value)
    if (resp.ready_to_report) {
      ElMessage.success("信息已充分，建议点击下方「生成报告」")
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "发送失败")
    messages.value = messages.value.filter((m) => m.id !== tempId)
  } finally {
    sending.value = false
  }
}

async function startStreaming() {
  if (streaming.value) return
  if (messages.value.length === 0) {
    ElMessage.warning("请先与 AI 对话补充事实")
    return
  }
  try {
    await ElMessageBox.confirm(
      "AI 将基于当前所有事实和对话生成完整报告，是否继续？",
      "生成报告",
      { confirmButtonText: "生成", cancelButtonText: "再聊一会" }
    )
  } catch {
    return
  }

  reportText.value = ""
  errorMsg.value = ""
  firstChunkAt.value = null
  totalChunks.value = 0
  aborted.value = false
  streaming.value = true
  streamController = new AbortController()

  const t0 = performance.now()
  try {
    for await (const event of generateReportStream(
      consultationId.value,
      streamController.signal
    )) {
      if (event.type === "chunk") {
        if (firstChunkAt.value === null) {
          firstChunkAt.value = (performance.now() - t0) / 1000
        }
        reportText.value += event.text
        totalChunks.value += 1
      } else if (event.type === "done") {
        if (event.disclaimer) disclaimer.value = event.disclaimer
        // 拉取落库的结论 → 渲染成持久化报告卡片
        consultation.value = await getConsultation(consultationId.value)
        reportText.value = "" // 清空流式原文，改用结构化卡片
        await nextTick()
        reportCardRef.value?.scrollIntoView({ behavior: "smooth", block: "start" })
      } else if (event.type === "error") {
        errorMsg.value = event.message
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
  const con = consultation.value
  try {
    const newCon = await createConsultation(
      con.project_id,
      con.scenario as "contract_review" | "variation"
    )
    router.push(`/consultation/${newCon.id}`)
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
    <!-- 顶部：面包屑式返回（P0-5：不再依赖浏览器 history） -->
    <el-page-header
      :title="`问诊 #${consultationId}`"
      :content="scenarioLabel"
      class="mb-16"
      @back="backToProject"
    />

    <!-- 加载失败（P0-1：可见错误 + 可返回） -->
    <el-alert
      v-if="loadError"
      :title="`加载问诊失败：${loadError}`"
      type="error"
      :closable="false"
      show-icon
      class="mb-16"
    >
      <template #default>
        <el-button size="small" class="mt-8" @click="backToProject">
          返回项目
        </el-button>
      </template>
    </el-alert>

    <template v-else>
      <!-- 状态条 -->
      <div class="status-bar mb-16">
        <el-tag size="small" :type="scenarioKind === 'variation' ? 'danger' : 'primary'">
          {{ scenarioLabel }}
        </el-tag>
        <el-tag
          size="small"
          :type="status === 'completed' ? 'success' : 'warning'"
          class="ml-8"
        >
          {{ statusLabel }}
        </el-tag>
        <el-tag size="small" type="info" class="ml-8">
          已采集事实 {{ factCount }}
        </el-tag>
        <el-tag v-if="hasReport" size="small" type="info" class="ml-8">
          结论 {{ conclusions.length }} 条
        </el-tag>
        <div class="spacer" />
        <el-button size="small" @click="newChat">新建问诊</el-button>
      </div>

      <!-- 聊天区 -->
      <div ref="messagesScrollRef" class="chat-scroll">
        <div v-if="messages.length === 0" class="empty-hint">
          <el-empty :description="`开始对话，描述你的${scenarioKind === 'variation' ? '变更事实' : '合同条款'}`" />
        </div>
        <div v-for="m in messages" :key="m.id" :class="['msg', `msg-${m.role}`]">
          <div class="avatar">{{ m.role === "user" ? "我" : "AI" }}</div>
          <div class="bubble">
            <div class="content">{{ m.content }}</div>
            <div class="time">{{ m.created_at.slice(11, 16) }}</div>
          </div>
        </div>
        <div v-if="sending" class="msg msg-assistant">
          <div class="avatar">AI</div>
          <div class="bubble bubble-typing">
            <span class="dot"></span><span class="dot"></span><span class="dot"></span>
          </div>
        </div>
      </div>

      <!-- 报告卡片（持久化：来自 DB conclusions） -->
      <div v-if="hasReport || streaming || aborted || errorMsg" ref="reportCardRef" class="report-card">
        <!-- 免责声明（AGENTS.md 应用原则 4：前置展示） -->
        <el-alert
          :title="disclaimer || '⚠️ 本报告由 AI 生成，仅供工程人员参考，不构成法律意见。重大决策前请由执业律师复核。'"
          type="warning"
          :closable="false"
          show-icon
          class="disclaimer"
        />

        <div class="report-header">
          <span class="report-title">📄 {{ scenarioLabel }}报告</span>
          <div class="spacer" />
          <el-tag v-if="streaming" type="warning" size="small">生成中...</el-tag>
          <el-tag v-else type="success" size="small">已生成</el-tag>
        </div>

        <!-- 流式进行中：显示原始输出（临时） -->
        <div v-if="streaming" class="stream-preview">
          <div class="stats mb-8">
            <el-tag v-if="firstChunkAt !== null" type="info" size="small">
              首 chunk {{ firstChunkAt.toFixed(2) }}s
            </el-tag>
            <el-tag v-if="totalChunks > 0" type="info" size="small" class="ml-8">
              {{ totalChunks }} chunks
            </el-tag>
            <div class="spacer" />
            <el-button size="small" type="danger" plain @click="stopStreaming">
              停止生成
            </el-button>
          </div>
          <pre class="stream-text">{{ reportText }}<span class="cursor">▊</span></pre>
        </div>

        <!-- 生成完成：结构化风险列表 -->
        <template v-else>
          <div class="overview mb-16">
            <el-tag v-if="riskStats.red" type="danger" size="large">
              🔴 红线 {{ riskStats.red }}
            </el-tag>
            <el-tag v-if="riskStats.yellow" type="warning" size="large" class="ml-8">
              🟡 黄区 {{ riskStats.yellow }}
            </el-tag>
            <el-tag v-if="riskStats.green" type="success" size="large" class="ml-8">
              🟢 可控 {{ riskStats.green }}
            </el-tag>
          </div>

          <div
            v-for="c in conclusions"
            :key="c.id"
            :class="['risk-item', `risk-${c.level}`]"
          >
            <div class="risk-head">
              <span class="risk-icon">{{ levelMeta[c.level]?.icon ?? "•" }}</span>
              <el-tag :type="levelMeta[c.level]?.type ?? 'info'" size="small">
                {{ levelMeta[c.level]?.label ?? c.level }}
              </el-tag>
              <span class="risk-title">{{ c.title }}</span>
            </div>
            <div class="risk-body">{{ c.content }}</div>
          </div>

          <el-alert
            v-if="consultation?.dispute_summary_ai"
            :title="consultation.dispute_summary_ai"
            type="success"
            :closable="false"
            show-icon
            class="mt-16"
          />
        </template>

        <el-alert
          v-if="errorMsg"
          :title="errorMsg"
          type="error"
          :closable="false"
          show-icon
          class="mt-16"
        />

        <el-alert
          v-if="aborted"
          title="已取消生成，可再次点击「生成报告」重试"
          type="info"
          :closable="false"
          show-icon
          class="mt-16"
        />
      </div>

      <!-- 输入区（completed 时禁用而非隐藏） -->
      <div class="input-bar">
        <el-input
          v-model="chatInput"
          type="textarea"
          :rows="3"
          :placeholder="
            status === 'completed'
              ? '本问诊已生成报告。如需继续追问，请点右上角「新建问诊」'
              : placeholder
          "
          :disabled="sending || status === 'completed'"
          @keydown.ctrl.enter.prevent="sendMessage"
          @keydown.meta.enter.prevent="sendMessage"
        />
        <div class="input-actions">
          <small class="hint">
            {{ status === "completed" ? "已完成" : `${hint} (Ctrl+Enter 发送)` }}
          </small>
          <div class="spacer" />
          <el-button
            type="primary"
            :loading="sending"
            :disabled="!chatInput.trim() || status === 'completed'"
            @click="sendMessage"
          >
            发送
          </el-button>
          <el-button
            type="success"
            :loading="streaming"
            :disabled="status === 'completed'"
            class="ml-8"
            @click="startStreaming"
          >
            生成报告
          </el-button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.consultation {
  display: flex;
  flex-direction: column;
  /* 父容器 .app-main 已限定高度并提供滚动，这里用 100% 避免嵌套滚动条 */
  height: 100%;
  padding: 24px;
  background: #f5f7fa;
}

.mb-16 {
  margin-bottom: 16px;
}

.mb-8 {
  margin-bottom: 8px;
}

.mt-8 {
  margin-top: 8px;
}

.mt-16 {
  margin-top: 16px;
}

.ml-8 {
  margin-left: 8px;
}

.status-bar {
  display: flex;
  align-items: center;
}

.spacer {
  flex: 1;
}

/* 聊天区 */
.chat-scroll {
  flex: 1;
  overflow-y: auto;
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  min-height: 180px;
}

.empty-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.msg {
  display: flex;
  margin-bottom: 20px;
  align-items: flex-start;
  gap: 12px;
}

.msg-user {
  flex-direction: row-reverse;
}

.avatar {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
}

.msg-user .avatar {
  background: #409eff;
}

.msg-assistant .avatar {
  background: #67c23a;
}

.bubble {
  max-width: 70%;
  padding: 12px 16px;
  border-radius: 8px;
  background: #f4f4f5;
  color: #303133;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg-user .bubble {
  background: #409eff;
  color: #fff;
}

.bubble .content {
  margin-bottom: 4px;
}

.bubble .time {
  font-size: 11px;
  color: #909399;
  text-align: right;
}

.msg-user .bubble .time {
  color: rgba(255, 255, 255, 0.7);
}

.bubble-typing {
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 16px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #909399;
  animation: typing 1.4s infinite ease-in-out;
}

.dot:nth-child(2) {
  animation-delay: 0.2s;
}

.dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%, 60%, 100% {
    transform: scale(0.8);
    opacity: 0.5;
  }
  30% {
    transform: scale(1.2);
    opacity: 1;
  }
}

/* 报告卡片 */
.report-card {
  margin-top: 12px;
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  max-height: 45vh;
  overflow-y: auto;
}

.disclaimer {
  margin-bottom: 12px;
}

.report-header {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
}

.report-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.overview {
  display: flex;
  align-items: center;
}

.stream-preview {
  background: #fafafa;
  border-radius: 4px;
  padding: 12px;
}

.stats {
  display: flex;
  align-items: center;
}

.stream-text {
  margin: 0;
  font-family: "Menlo", "Monaco", "Courier New", monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #606266;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow-y: auto;
}

.cursor {
  display: inline-block;
  animation: blink 1s step-end infinite;
  color: #409eff;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

/* 风险条目 */
.risk-item {
  border-left: 3px solid #dcdfe6;
  padding: 10px 0 10px 12px;
  margin-bottom: 12px;
  background: #fafafa;
  border-radius: 0 4px 4px 0;
}

.risk-item.risk-red {
  border-left-color: #f56c6c;
  background: #fef0f0;
}

.risk-item.risk-yellow {
  border-left-color: #e6a23c;
  background: #fdf6ec;
}

.risk-item.risk-green {
  border-left-color: #67c23a;
  background: #f0f9eb;
}

.risk-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.risk-icon {
  font-size: 14px;
}

.risk-title {
  font-weight: 600;
  color: #303133;
}

.risk-body {
  color: #606266;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
}

/* 输入区 */
.input-bar {
  margin-top: 12px;
  background: #fff;
  border-radius: 8px;
  padding: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
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
</style>
