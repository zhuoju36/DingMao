<script setup lang="ts">
// 律师问诊对话 + 流式报告生成
import { computed, onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { ElMessage } from "element-plus"
import {
  generateReportStream,
  getConsultation,
  submitContractText,
  type StreamEvent,
} from "@/api/consultation"

const route = useRoute()
const router = useRouter()
const consultationId = computed(() => Number(route.params.id))

// 问诊状态
const consultation = ref<Awaited<ReturnType<typeof getConsultation>> | null>(null)
const reportText = ref("")
const summary = ref("")
const errorMsg = ref("")
const streaming = ref(false)
const done = ref(false)
const firstChunkAt = ref<number | null>(null)
const totalChunks = ref(0)

// 输入区
const userInput = ref("")
const submitting = ref(false)

const scenarioLabel = computed(() => {
  const s = consultation.value?.scenario
  if (s === "variation") return "变更扯皮场景"
  if (s === "contract_review") return "合同审查场景"
  return "问诊"
})

const scenarioKind = computed<"contract_review" | "variation" | "unknown">(() => {
  const s = consultation.value?.scenario
  if (s === "variation" || s === "contract_review") return s
  return "unknown"
})

// 场景不同 → 输入区文案不同
const inputConfig = computed(() => {
  if (scenarioKind.value === "variation") {
    return {
      label: "变更事实描述",
      placeholder:
        "请描述本次变更/签证/索赔争议的事实，例如：\n" +
        "- 什么事件（设计变更/业主指令/施工方提出等）\n" +
        "- 何时发生\n" +
        "- 涉及哪些条款\n" +
        "- 目前双方争议焦点\n" +
        "- 已有证据 / 签证 / 会议纪要",
      hint: "事实描述越具体，AI 给出的建议越精准。建议至少 100 字。",
      submitText: "提交事实",
      hasInput: !userInput.value.trim(),
    }
  }
  // contract_review 或默认
  return {
    label: "合同条款文本",
    placeholder:
      "请粘贴需要审查的合同条款，例如：\n" +
      "本合同付款采用背靠背方式，业主付款后再支付施工方。" +
      "暂定价以审计机关审计结果为准。" +
      "逾期违约金按日万分之五计算。",
    hint: "支持贴整份合同或只贴关键条款。建议 50-2000 字。",
    submitText: "提交合同文本",
    hasInput: !userInput.value.trim(),
  }
})

const hasFacts = computed(() => (consultation.value?.facts.length ?? 0) > 0)
const status = computed(() => consultation.value?.status ?? "unknown")

onMounted(async () => {
  try {
    consultation.value = await getConsultation(consultationId.value)
  } catch (e) {
    console.error("加载问诊失败:", e)
  }
})

async function submitInput() {
  if (!userInput.value.trim()) {
    ElMessage.warning("请输入内容")
    return
  }
  submitting.value = true
  try {
    consultation.value = await submitContractText(
      consultationId.value,
      userInput.value
    )
    ElMessage.success("已提交")
    userInput.value = ""
  } catch (e) {
    const msg = e instanceof Error ? e.message : "提交失败"
    ElMessage.error(msg)
  } finally {
    submitting.value = false
  }
}

async function startStreaming() {
  if (!hasFacts.value) {
    ElMessage.warning("请先提交" + (scenarioKind.value === "variation" ? "事实描述" : "合同文本"))
    return
  }
  if (streaming.value) return
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
        // 刷新状态（status → completed）
        await refreshConsultation()
      } else if (event.type === "error") {
        errorMsg.value = event.message
      }
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : "未知错误"
    errorMsg.value = `流中断: ${msg}`
  } finally {
    streaming.value = false
  }
}

async function refreshConsultation() {
  try {
    consultation.value = await getConsultation(consultationId.value)
  } catch (e) {
    console.error(e)
  }
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

    <el-card v-if="consultation" class="mb-16">
      <el-descriptions :column="3" size="small" border>
        <el-descriptions-item label="场景">
          <el-tag size="small" :type="scenarioKind === 'variation' ? 'danger' : 'primary'">
            {{ scenarioLabel }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag size="small" :type="status === 'completed' ? 'success' : 'warning'">
            {{ status }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="已采集事实">
          {{ consultation.facts.length }} 条
        </el-descriptions-item>
        <el-descriptions-item label="已生成结论">
          {{ consultation.conclusions.length }} 条
        </el-descriptions-item>
        <el-descriptions-item label="项目ID" :span="2">{{ consultation.project_id }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 输入区（场景自适应） -->
    <el-card class="mb-16" v-if="status !== 'completed'">
      <template #header>
        <span class="section-title">
          {{ hasFacts ? '继续补充' + inputConfig.label : '提交' + inputConfig.label }}
        </span>
      </template>

      <el-form @submit.prevent="submitInput">
        <el-form-item :label="inputConfig.label">
          <el-input
            v-model="userInput"
            type="textarea"
            :rows="8"
            :placeholder="inputConfig.placeholder"
            :disabled="submitting"
          />
        </el-form-item>
        <el-form-item>
          <small class="hint">{{ inputConfig.hint }}</small>
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :loading="submitting"
            :disabled="!userInput.trim()"
            @click="submitInput"
          >
            <el-icon><Position /></el-icon>
            {{ inputConfig.submitText }}
          </el-button>
          <el-button
            v-if="hasFacts"
            type="success"
            :loading="streaming"
            class="ml-8"
            @click="startStreaming"
          >
            <el-icon><VideoPlay /></el-icon>
            {{ streaming ? '生成中...' : '开始生成报告' }}
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 已完成提示 -->
    <el-alert
      v-if="status === 'completed'"
      title="本问诊已生成报告"
      type="success"
      :closable="false"
      show-icon
      class="mb-16"
    />

    <!-- 错误 -->
    <el-alert
      v-if="errorMsg"
      :title="errorMsg"
      type="error"
      :closable="false"
      show-icon
      class="mb-16"
    />

    <!-- 流式输出 -->
    <el-card v-if="streaming || done || reportText">
      <template #header>
        <div class="flex-between">
          <span>报告生成（流式）</span>
          <div>
            <el-tag v-if="streaming" type="warning" size="small">生成中...</el-tag>
            <el-tag v-else-if="done" type="success" size="small">完成</el-tag>
            <el-tag v-if="firstChunkAt !== null" class="ml-8" type="info" size="small">
              首 chunk: {{ firstChunkAt.toFixed(2) }}s
            </el-tag>
            <el-tag v-if="totalChunks > 0" class="ml-8" type="info" size="small">
              {{ totalChunks }} chunks
            </el-tag>
          </div>
        </div>
      </template>

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
    </el-card>

    <el-empty
      v-if="!streaming && !reportText && !errorMsg && status !== 'completed'"
      description="上方填写事实或合同条款后，点“开始生成报告”"
    />
  </div>
</template>

<style scoped>
.consultation {
  padding: 24px;
  background: #f5f7fa;
  min-height: calc(100vh - 60px);
}

.flex-between {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-title {
  font-weight: 600;
}

.hint {
  color: #909399;
}

.ml-8 {
  margin-left: 8px;
}

.mb-16 {
  margin-bottom: 16px;
}

.mt-16 {
  margin-top: 16px;
}

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

@keyframes blink {
  50% { opacity: 0; }
}
</style>
