<script setup lang="ts">
// 律师问诊：多轮对话 + 流式报告生成
import { computed, nextTick, onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { ElMessage, ElMessageBox } from "element-plus"
import {
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

// 报告生成
const reportText = ref("")
const summary = ref("")
const errorMsg = ref("")
const streaming = ref(false)
const done = ref(false)
const firstChunkAt = ref<number | null>(null)
const totalChunks = ref(0)
const reportDialogVisible = ref(false)

// 滚动容器
const messagesScrollRef = ref<HTMLElement | null>(null)

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
const factCount = computed(() => consultation.value?.facts.length ?? 0)

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

// 滚动到底部
async function scrollToBottom() {
  await nextTick()
  if (messagesScrollRef.value) {
    messagesScrollRef.value.scrollTop = messagesScrollRef.value.scrollHeight
  }
}

onMounted(async () => {
  try {
    consultation.value = await getConsultation(consultationId.value)
    messages.value = await listMessages(consultationId.value)
    await scrollToBottom()
  } catch (e) {
    console.error("加载问诊失败:", e)
  }
})

async function sendMessage() {
  if (!chatInput.value.trim()) return
  if (sending.value) return

  const userContent = chatInput.value
  const tempUserMsg: ConsultationMessage = {
    id: -Date.now(),
    consultation_id: consultationId.value,
    role: "user",
    content: userContent,
    created_at: new Date().toISOString(),
  }
  messages.value.push(tempUserMsg)
  chatInput.value = ""
  await scrollToBottom()

  sending.value = true
  try {
    const resp = await postMessage(consultationId.value, userContent)
    // 用真实消息替换临时消息
    messages.value = messages.value.filter((m) => m.id !== tempUserMsg.id)
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
    // 刷新 consultation 拿最新 fact_count
    consultation.value = await getConsultation(consultationId.value)
    if (resp.ready_to_report) {
      ElMessage.success("信息已充分，建议点击下方「生成报告」")
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "发送失败")
    messages.value = messages.value.filter((m) => m.id !== tempUserMsg.id)
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
    return // 用户取消
  }
  reportDialogVisible.value = true

  reportText.value = ""
  errorMsg.value = ""
  summary.value = ""
  done.value = false
  firstChunkAt.value = null
  totalChunks.value = 0
  streaming.value = true

  const t0 = performance.now()
  try {
    for await (const event of generateReportStream(consultationId.value)) {
      if (event.type === "chunk") {
        if (firstChunkAt.value === null) {
          firstChunkAt.value = (performance.now() - t0) / 1000
        }
        reportText.value += event.text
        totalChunks.value += 1
      } else if (event.type === "done") {
        summary.value = event.summary
        done.value = true
        consultation.value = await getConsultation(consultationId.value)
      } else if (event.type === "error") {
        errorMsg.value = event.message
      }
    }
  } catch (e) {
    errorMsg.value = `流中断: ${e instanceof Error ? e.message : "未知错误"}`
  } finally {
    streaming.value = false
  }
}

async function newChat() {
  try {
    await ElMessageBox.confirm(
      "新建问诊会重置当前对话上下文，是否继续？",
      "新建问诊",
      { confirmButtonText: "新建", cancelButtonText: "取消" }
    )
  } catch {
    return
  }
  if (!consultation.value) return
  const con = consultation.value
  const newCon = await import("@/api/consultation").then((m) =>
    m.createConsultation(con.project_id, con.scenario as "contract_review" | "variation")
  )
  router.push(`/consultation/${newCon.id}`)
}
</script>

<template>
  <div class="consultation">
    <el-page-header
      :title="`问诊 #${consultationId}`"
      :content="scenarioLabel"
      class="mb-16"
      @back="router.back()"
    />

    <!-- 顶部状态条 -->
    <div class="status-bar mb-16">
      <el-tag size="small" :type="scenarioKind === 'variation' ? 'danger' : 'primary'">
        {{ scenarioLabel }}
      </el-tag>
      <el-tag size="small" :type="status === 'completed' ? 'success' : 'warning'" class="ml-8">
        状态: {{ status }}
      </el-tag>
      <el-tag size="small" type="info" class="ml-8">
        已采集事实: {{ factCount }}
      </el-tag>
      <el-tag v-if="status === 'completed'" size="small" type="success" class="ml-8">
        报告已生成
      </el-tag>
      <div class="spacer" />
      <el-button v-if="status !== 'completed'" size="small" @click="newChat">
        新建问诊
      </el-button>
    </div>

    <!-- 聊天区 -->
    <div ref="messagesScrollRef" class="chat-scroll">
      <div v-if="messages.length === 0" class="empty-hint">
        <el-empty description="开始对话，描述你的问题或事实" />
      </div>
      <div
        v-for="m in messages"
        :key="m.id"
        :class="['msg', `msg-${m.role}`]"
      >
        <div class="avatar">
          {{ m.role === "user" ? "我" : "AI" }}
        </div>
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

    <!-- 输入区 -->
    <div v-if="status !== 'completed'" class="input-bar">
      <el-input
        v-model="chatInput"
        type="textarea"
        :rows="3"
        :placeholder="placeholder"
        :disabled="sending"
        @keydown.ctrl.enter.prevent="sendMessage"
        @keydown.meta.enter.prevent="sendMessage"
      />
      <div class="input-actions">
        <small class="hint">{{ hint }} (Ctrl+Enter 发送)</small>
        <div class="spacer" />
        <el-button
          type="primary"
          :loading="sending"
          :disabled="!chatInput.trim()"
          @click="sendMessage"
        >
          发送
        </el-button>
        <el-button
          type="success"
          :loading="streaming"
          class="ml-8"
          @click="startStreaming"
        >
          生成报告
        </el-button>
      </div>
    </div>

    <!-- 报告流式输出（弹窗式）-->
    <el-dialog
      v-model="reportDialogVisible"
      :title="`问诊 #${consultationId} 报告`"
      width="800px"
      :close-on-click-modal="false"
    >
      <div v-if="streaming || done || reportText">
        <div class="stats mb-16">
          <el-tag v-if="streaming" type="warning" size="small">生成中...</el-tag>
          <el-tag v-else-if="done" type="success" size="small">完成</el-tag>
          <el-tag v-if="firstChunkAt !== null" class="ml-8" type="info" size="small">
            首 chunk: {{ firstChunkAt.toFixed(2) }}s
          </el-tag>
          <el-tag v-if="totalChunks > 0" class="ml-8" type="info" size="small">
            {{ totalChunks }} chunks
          </el-tag>
        </div>
        <el-alert
          v-if="errorMsg"
          :title="errorMsg"
          type="error"
          :closable="false"
          show-icon
          class="mb-16"
        />
        <div class="output-box">
          <pre><code>{{ reportText }}<span v-if="streaming" class="cursor">▊</span></code></pre>
        </div>
        <el-alert
          v-if="summary"
          :title="summary"
          type="success"
          :closable="false"
          show-icon
          class="mt-16"
        />
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.consultation {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 60px);
  padding: 24px;
  background: #f5f7fa;
}

.mb-16 {
  margin-bottom: 16px;
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

/* 报告输出 */
.output-box {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 4px;
  max-height: 500px;
  overflow-y: auto;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
}

.output-box pre {
  margin: 0;
}

.output-box code {
  background: transparent;
  color: inherit;
  font-family: inherit;
  white-space: pre-wrap;
  word-break: break-word;
}

.cursor {
  display: inline-block;
  animation: blink 1s step-end infinite;
  color: #4ec9b0;
}

.stats {
  display: flex;
  align-items: center;
}

@keyframes blink {
  50% { opacity: 0; }
}
</style>
