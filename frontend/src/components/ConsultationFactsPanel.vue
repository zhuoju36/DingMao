<script setup lang="ts">
// 左栏「采集进度」面板 —— consultation-ui.md §4.2/§4.3 线框 A/B
//
// 设计要点：
// 1. 必填清单**常驻可见**，用户随时知道"还差什么"。这是把问诊从"聊天工具"
//    掰回"结构化事实采集"的关键——此前只剩一个数字徽章。
// 2. 清单来自后端下发的 registry（constants.FACT_REGISTRY），前端不硬编码。
// 3. 待人工确认项（未过置信度闸门）单独成组并高亮：这类项**没有写库**，
//    必须让用户知道要自己补（应用原则 2）。
import { computed } from "vue"
import type { ConsultationFact, FactProgress } from "@/types/consultation"

const props = defineProps<{
  progress: FactProgress | null
  facts: ConsultationFact[]
  step: string
  /** 正在生成报告：禁用确认按钮 */
  busy?: boolean
}>()

const emit = defineEmits<{ confirm: [] }>()

// ===== 枚举值 → 中文 =====
const DISPUTE_TYPE_LABEL: Record<string, string> = {
  payment: "付款争议",
  quality: "质量争议",
  schedule: "工期争议",
  scope: "工程范围争议",
  other: "其他",
}
const OUTCOME_LABEL: Record<string, string> = {
  extend_compensation: "延期 + 索赔",
  extend_schedule: "仅延期",
  quality_fix: "整改",
  other: "其他",
}
const EVIDENCE_TYPE_LABEL: Record<string, string> = {
  contract_clause: "合同条款",
  correspondence: "沟通记录",
  variation_order: "签证单",
  inspection: "检验记录",
  photo: "现场照片",
  chat_record: "聊天记录",
  other: "其他",
}

const requiredSpecs = computed(
  () => props.progress?.registry.filter((s) => s.required) ?? []
)
const optionalSpecs = computed(
  () => props.progress?.registry.filter((s) => !s.required) ?? []
)

const factByKey = computed(() => {
  const m: Record<string, ConsultationFact> = {}
  for (const f of props.facts) m[f.fact_key] = f
  return m
})
const pendingByKey = computed(() => {
  const m: Record<string, { fact_label: string; reason: string }> = {}
  for (const p of props.progress?.pending ?? []) m[p.fact_key] = p
  return m
})

const have = computed(() => props.progress?.required_have ?? 0)
const total = computed(() => props.progress?.required_total ?? 0)
const pct = computed(() =>
  total.value ? Math.round((have.value / total.value) * 100) : 0
)
const allRequiredDone = computed(() => total.value > 0 && have.value === total.value)
const missingLabels = computed(() =>
  (props.progress?.missing_required ?? []).map(
    (k) => props.progress?.registry.find((s) => s.fact_key === k)?.fact_label ?? k
  )
)

/** 必填项里第一个缺失的，标记为「正在问」 */
const askingKey = computed(() => props.progress?.missing_required[0] ?? "")

const canConfirm = computed(
  () =>
    !props.busy &&
    ["collecting_facts", "awaiting_confirm", "init", "await_text"].includes(
      props.step
    )
)

function isFilled(key: string): boolean {
  return key in factByKey.value
}

/** 事实值的展示化（json/enum 要转人话） */
function display(key: string): string {
  const f = factByKey.value[key]
  if (!f) return ""
  const v = f.fact_value
  if (f.fact_value_type === "enum") {
    return DISPUTE_TYPE_LABEL[v] ?? OUTCOME_LABEL[v] ?? v
  }
  if (f.fact_value_type === "bool") return v === "true" ? "是" : "否"
  if (f.fact_value_type === "number") {
    const n = Number(v)
    if (key === "claimed_amount" && Number.isFinite(n)) {
      return `¥${n.toLocaleString("zh-CN")}`
    }
    return Number.isFinite(n) ? n.toLocaleString("zh-CN") : v
  }
  if (f.fact_value_type === "json") {
    try {
      const arr = JSON.parse(v)
      if (Array.isArray(arr)) {
        if (key === "parties_in_dispute") {
          return arr.map((p) => p?.name ?? "?").join("、")
        }
        return `${arr.length} 项`
      }
    } catch {
      /* 脏数据原样展示 */
    }
  }
  return v
}

/** evidence_list 展开成条目 */
const evidenceItems = computed(() => {
  const f = factByKey.value["evidence_list"]
  if (!f) return []
  try {
    const arr = JSON.parse(f.fact_value)
    if (!Array.isArray(arr)) return []
    return arr.map((e) => ({
      type: EVIDENCE_TYPE_LABEL[e?.type] ?? e?.type ?? "证据",
      ref: e?.ref ?? "",
      desc: e?.description ?? "",
      date: e?.date ?? "",
      amount: e?.amount ?? "",
    }))
  } catch {
    return []
  }
})
</script>

<template>
  <aside class="facts-panel">
    <!-- ===== 必填进度 ===== -->
    <header class="panel-head">
      <div class="head-row">
        <span class="head-title">采集进度</span>
        <span class="head-count" :class="{ done: allRequiredDone }">
          必填 {{ have }}/{{ total }}
        </span>
      </div>
      <el-progress
        :percentage="pct"
        :stroke-width="6"
        :show-text="false"
        :color="allRequiredDone ? '#67c23a' : '#409eff'"
      />
    </header>

    <div class="panel-body">
      <!-- ===== 必填清单 ===== -->
      <ul class="checklist">
        <li
          v-for="s in requiredSpecs"
          :key="s.fact_key"
          class="check-item"
          :class="{
            filled: isFilled(s.fact_key),
            asking: s.fact_key === askingKey,
            pending: !!pendingByKey[s.fact_key],
          }"
        >
          <span class="mark">{{
            isFilled(s.fact_key) ? "✓" : pendingByKey[s.fact_key] ? "⚠" : "○"
          }}</span>
          <span class="label">{{ s.fact_label }}</span>
          <span v-if="isFilled(s.fact_key)" class="value" :title="display(s.fact_key)">
            {{ display(s.fact_key) }}
          </span>
          <span v-else-if="s.fact_key === askingKey" class="tag-asking">正在问</span>
          <el-tooltip v-else :content="s.question" placement="top">
            <span class="tag-missing">缺</span>
          </el-tooltip>
        </li>
      </ul>

      <!-- ===== 选填清单 ===== -->
      <div class="divider" />
      <div class="sub-head">
        选填
        <span class="sub-count">
          {{ optionalSpecs.filter((s) => isFilled(s.fact_key)).length }}/{{
            optionalSpecs.length
          }}
        </span>
      </div>
      <ul class="checklist">
        <li
          v-for="s in optionalSpecs"
          :key="s.fact_key"
          class="check-item"
          :class="{ filled: isFilled(s.fact_key) }"
        >
          <span class="mark">{{
            isFilled(s.fact_key) ? "✓" : pendingByKey[s.fact_key] ? "⚠" : "○"
          }}</span>
          <span class="label">{{ s.fact_label }}</span>
          <span v-if="isFilled(s.fact_key)" class="value" :title="display(s.fact_key)">
            {{ display(s.fact_key) }}
          </span>
          <el-tooltip v-else :content="s.question" placement="top">
            <span class="tag-missing">—</span>
          </el-tooltip>
        </li>
      </ul>

      <!-- ===== 待人工确认（未过置信度闸门，未写库）===== -->
      <template v-if="progress?.pending?.length">
        <div class="divider" />
        <div class="sub-head warn">待人工确认</div>
        <ul class="pending-list">
          <li v-for="p in progress.pending" :key="p.fact_key" class="pending-item">
            <span class="pending-label">⚠️ {{ p.fact_label }}</span>
            <span class="pending-value">待确认</span>
            <div class="pending-reason">
              系统未采信自动识别的值（{{ p.reason }}），请在对话中直接说明。
            </div>
          </li>
        </ul>
      </template>

      <!-- ===== 证据清单展开 ===== -->
      <template v-if="evidenceItems.length">
        <div class="divider" />
        <div class="sub-head">
          证据清单
          <span class="sub-count">{{ evidenceItems.length }}</span>
        </div>
        <ul class="evidence-list">
          <li v-for="(e, i) in evidenceItems" :key="i" class="evidence-item">
            <span class="ev-type">{{ e.type }}</span>
            <span class="ev-ref">{{ e.ref }}</span>
            <span v-if="e.date" class="ev-meta">{{ e.date }}</span>
            <span v-if="e.amount" class="ev-meta">{{ e.amount }}</span>
          </li>
        </ul>
      </template>

      <el-empty
        v-if="!facts.length"
        description="还没有采集到事实，先在右侧描述争议"
        :image-size="64"
      />
    </div>

    <!-- ===== 底部主按钮（随状态 morph，§5.1）===== -->
    <footer v-if="canConfirm" class="panel-foot">
      <el-button
        type="primary"
        class="confirm-btn"
        :disabled="!canConfirm"
        @click="emit('confirm')"
      >
        {{ allRequiredDone ? "确认生成报告" : "生成报告" }}
      </el-button>
      <p v-if="allRequiredDone" class="foot-hint">将同时生成 5 类文书</p>
      <p v-else class="foot-hint warn">
        还差 {{ missingLabels.length }} 项：{{ missingLabels.join("、") }}
      </p>
    </footer>
  </aside>
</template>

<style scoped>
.facts-panel {
  display: flex;
  flex-direction: column;
  width: 380px;
  flex-shrink: 0;
  height: var(--pane-h);
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.panel-head {
  padding: 14px 16px 12px;
  border-bottom: 1px solid #ebeef5;
  flex-shrink: 0;
}
.head-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 8px;
}
.head-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.head-count {
  font-size: 13px;
  color: #909399;
  font-variant-numeric: tabular-nums;
}
.head-count.done {
  color: #67c23a;
  font-weight: 600;
}

.panel-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 16px 16px;
}

.checklist {
  list-style: none;
  margin: 0;
  padding: 0;
}
.check-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  font-size: 13px;
  line-height: 1.5;
}
.check-item .mark {
  width: 14px;
  flex-shrink: 0;
  text-align: center;
  color: #c0c4cc;
  font-weight: 600;
}
.check-item.filled .mark {
  color: #67c23a;
}
.check-item.pending .mark {
  color: #e6a23c;
}
.check-item .label {
  flex-shrink: 0;
  color: #606266;
}
.check-item.filled .label {
  color: #303133;
}
.check-item.asking .label {
  color: #409eff;
  font-weight: 600;
}
.check-item .value {
  flex: 1;
  min-width: 0;
  text-align: right;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.check-item.asking {
  background: #ecf5ff;
  border-radius: 4px;
  margin: 0 -6px;
  padding: 0 6px;
}

.tag-asking {
  flex-shrink: 0;
  font-size: 11px;
  color: #409eff;
  border: 1px solid #b3d8ff;
  background: #ecf5ff;
  border-radius: 3px;
  padding: 0 4px;
}
.tag-missing {
  flex-shrink: 0;
  font-size: 11px;
  color: #c0c4cc;
}

.divider {
  height: 1px;
  background: #f2f6fc;
  margin: 12px 0 8px;
}
.sub-head {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.sub-head.warn {
  color: #e6a23c;
  font-weight: 600;
}
.sub-count {
  font-variant-numeric: tabular-nums;
}

.pending-list,
.evidence-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.pending-item {
  background: #fdf6ec;
  border-radius: 4px;
  padding: 6px 8px;
  margin-bottom: 6px;
}
.pending-label {
  font-size: 13px;
  color: #b88230;
  font-weight: 600;
}
.pending-value {
  float: right;
  font-size: 12px;
  color: #e6a23c;
}
.pending-reason {
  margin-top: 3px;
  font-size: 11px;
  line-height: 1.5;
  color: #a8843c;
}

.evidence-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 12px;
  padding: 3px 0;
  border-bottom: 1px dashed #f2f6fc;
}
.evidence-item:last-child {
  border-bottom: none;
}
.ev-type {
  flex-shrink: 0;
  color: #409eff;
}
.ev-ref {
  flex: 1;
  min-width: 0;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ev-meta {
  flex-shrink: 0;
  color: #909399;
}

.panel-foot {
  flex-shrink: 0;
  padding: 12px 16px;
  border-top: 1px solid #ebeef5;
  background: #fafcff;
}
.confirm-btn {
  width: 100%;
}
.foot-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: #909399;
  text-align: center;
  line-height: 1.5;
}
.foot-hint.warn {
  color: #e6a23c;
}

/* 窄屏：由父级控制折叠 */
@media (max-width: 1280px) {
  .facts-panel {
    width: 100%;
    height: auto;
    max-height: 46vh;
  }
}
</style>
