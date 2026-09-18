<script setup lang="ts">
// 结论卡（含三依据）—— consultation-ui.md §4.4 线框 C
//
// 此前 Consultation.vue 只渲染 c.title 和 c.content，`fact_refs`/`law_refs`/
// `standard_refs`/`reasoning_chain`/`counter_arguments` 五个字段 API 全返回、
// TS 类型全声明，界面上一个都没有。产品最核心的「数据确凿优先」在界面上不存在。
//
// 展示层次（按重不重要排序）：
//   1. 等级 + 标题 + 正文       —— 用户先看结论
//   2. 🟦🟨🟥 三依据            —— 再看凭什么（应用原则 1 的可核验性）
//   3. 推理链 / 反例与例外      —— 默认折叠，给复核用，不淹没结论
import { computed, ref } from "vue"
import type {
  ConsultationConclusion,
  ConsultationFact,
  EvidenceWarning,
} from "@/types/consultation"

const props = defineProps<{
  conclusion: ConsultationConclusion
  facts: ConsultationFact[]
  warnings: EvidenceWarning[]
  index: number
}>()

const showReasoning = ref(false)
const showCounter = ref(false)

const LEVEL_META = {
  red: { label: "红线", icon: "🔴", cls: "lv-red" },
  yellow: { label: "黄区", icon: "🟡", cls: "lv-yellow" },
  green: { label: "可控", icon: "🟢", cls: "lv-green" },
} as const

const meta = computed(
  () => LEVEL_META[props.conclusion.level] ?? LEVEL_META.yellow
)

/** fact_refs（id 数组）→ 人类可读的事实条目 */
const citedFacts = computed(() =>
  props.conclusion.fact_refs
    .map((id) => props.facts.find((f) => f.id === id))
    .filter((f): f is ConsultationFact => !!f)
)

/** 该结论相关的降级告警 */
const myWarnings = computed(() =>
  props.warnings.filter((w) => w.index === props.index)
)
const noBasis = computed(() =>
  myWarnings.value.some((w) => w.type === "no_candidate_basis")
)
const noFact = computed(() =>
  myWarnings.value.some((w) => w.type === "no_fact_basis")
)
const unsupported = computed(
  () => myWarnings.value.find((w) => w.type === "unsupported_conclusion") ?? null
)

function shortValue(f: ConsultationFact): string {
  const v = f.fact_value
  if (f.fact_value_type === "json") {
    try {
      const a = JSON.parse(v)
      if (Array.isArray(a)) return `${a.length} 项`
    } catch {
      /* ignore */
    }
  }
  return v.length > 48 ? `${v.slice(0, 48)}…` : v
}
</script>

<template>
  <article class="conclusion" :class="meta.cls">
    <header class="c-head">
      <span class="c-icon">{{ meta.icon }}</span>
      <span class="c-level">{{ meta.label }}</span>
      <h4 class="c-title">{{ conclusion.title }}</h4>
    </header>

    <p class="c-content">{{ conclusion.content }}</p>

    <!-- ===== 三依据 ===== -->
    <section class="evidence">
      <!-- 🟦 事实 -->
      <div class="ev-row">
        <span class="ev-badge fact">🟦 依据事实</span>
        <ul v-if="citedFacts.length" class="ev-items">
          <li v-for="f in citedFacts" :key="f.id">
            <span class="ev-k">{{ f.fact_label }}</span>
            <span class="ev-v">{{ shortValue(f) }}</span>
          </li>
        </ul>
        <span v-else class="ev-none">未挂事实依据</span>
      </div>

      <!-- 🟨 法条 -->
      <div class="ev-row">
        <span class="ev-badge law">🟨 法律依据</span>
        <ul v-if="conclusion.law_refs.length" class="ev-items">
          <li v-for="(r, i) in conclusion.law_refs" :key="i">
            <span class="ev-k">《{{ r.name || r.code }}》</span>
            <span class="ev-v">{{ r.article_no }}</span>
            <span class="ev-meta">{{ r.version }} · {{ r.effective_date }} 生效</span>
          </li>
        </ul>
        <span v-else class="ev-none">无明确法律依据</span>
      </div>

      <!-- 🟥 强条 -->
      <div class="ev-row">
        <span class="ev-badge std">🟥 强制条文</span>
        <ul v-if="conclusion.standard_refs.length" class="ev-items">
          <li v-for="(r, i) in conclusion.standard_refs" :key="i">
            <span class="ev-k">{{ r.name || r.code }}</span>
            <span class="ev-v">{{ r.clause_no }}</span>
            <span class="ev-meta">
              {{ r.version }}<template v-if="r.is_mandatory"> · 强制性条文</template>
            </span>
          </li>
        </ul>
        <span v-else class="ev-none">无对应强制性条文</span>
      </div>
    </section>

    <!-- ===== 降级告警（必须可见，不能静默）===== -->
    <div v-if="unsupported" class="c-warn strong">
      ⚠️ {{ unsupported.detail }}
    </div>
    <div v-else-if="noFact" class="c-warn">
      ⚠️ 该结论未挂事实依据
    </div>
    <div v-if="noBasis" class="c-warn">
      ⚠️ 知识库无对应条款或条款版本信息缺失，本条依据按应用原则 3 未展示引用
    </div>

    <!-- ===== 复核材料（默认折叠）===== -->
    <div class="fold">
      <button class="fold-btn" @click="showReasoning = !showReasoning">
        {{ showReasoning ? "▾" : "▸" }} 推理链
      </button>
      <p v-if="showReasoning" class="fold-body">
        {{ conclusion.reasoning_chain || "（无）" }}
      </p>
    </div>
    <div v-if="conclusion.counter_arguments" class="fold">
      <button class="fold-btn" @click="showCounter = !showCounter">
        {{ showCounter ? "▾" : "▸" }} 反例与例外
      </button>
      <p v-if="showCounter" class="fold-body">
        {{ conclusion.counter_arguments }}
      </p>
    </div>
  </article>
</template>

<style scoped>
.conclusion {
  border-left: 3px solid #dcdfe6;
  border-radius: 0 6px 6px 0;
  padding: 14px 16px;
  margin-bottom: 14px;
  background: #fafafa;
}
.conclusion.lv-red {
  border-left-color: #f56c6c;
  background: #fef0f0;
}
.conclusion.lv-yellow {
  border-left-color: #e6a23c;
  background: #fdf6ec;
}
.conclusion.lv-green {
  border-left-color: #67c23a;
  background: #f0f9eb;
}

.c-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.c-icon {
  font-size: 15px;
}
.c-level {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  background: rgba(0, 0, 0, 0.05);
  color: #606266;
}
.c-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  line-height: 1.4;
}

.c-content {
  margin: 0 0 12px;
  font-size: 14px;
  line-height: 1.75;
  color: #303133;
  white-space: pre-wrap;
}

.evidence {
  border-top: 1px dashed rgba(0, 0, 0, 0.08);
  padding-top: 10px;
}
.ev-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 6px;
}
.ev-badge {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  min-width: 76px;
}
.ev-items {
  list-style: none;
  margin: 0;
  padding: 0;
  flex: 1;
  min-width: 0;
}
.ev-items li {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
  font-size: 12.5px;
  line-height: 1.7;
  color: #303133;
}
.ev-k {
  font-weight: 600;
}
.ev-v {
  color: #606266;
}
.ev-meta {
  font-size: 11.5px;
  color: #909399;
}
.ev-none {
  font-size: 12.5px;
  color: #c0c4cc;
  font-style: italic;
}

.c-warn {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.6;
  color: #b88230;
  background: #fdf6ec;
  border-radius: 4px;
  padding: 6px 8px;
}
.c-warn.strong {
  color: #c45656;
  background: #fef0f0;
}

.fold {
  margin-top: 8px;
}
.fold-btn {
  background: none;
  border: none;
  padding: 0;
  font-size: 12.5px;
  color: #409eff;
  cursor: pointer;
}
.fold-btn:hover {
  text-decoration: underline;
}
.fold-body {
  margin: 6px 0 0;
  font-size: 12.5px;
  line-height: 1.75;
  color: #606266;
  white-space: pre-wrap;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 4px;
  padding: 8px 10px;
}
</style>
