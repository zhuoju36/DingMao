<script setup lang="ts">
// 档案阅读区（P0-7-C 布局修订）
//
// 被两个位置复用，故抽成组件（原则 4 组件保持模块化）：
//   - 宽屏（≥1280px）：右侧预览面板
//   - 窄屏（<1280px）：抽屉
//
// 只负责渲染，不发请求（详情由父组件按需拉取）。
import { computed } from "vue"
import { Clock, Loading, WarningFilled } from "@element-plus/icons-vue"

import type { DocumentListItem, DocumentResponse } from "@/api/documents"
import { DOCUMENT_TYPE_LABELS } from "@/api/documents"
import { formatBytes, formatChars, formatDateTime, formatDuration } from "@/utils/format"
import { renderMarkdown } from "@/utils/markdown"

const props = defineProps<{
  /** 当前选中项（含状态与解析摘要） */
  doc: DocumentListItem | null
  /** 详情（含 markdown）；仅 parsed 状态才有 */
  detail: DocumentResponse | null
  loading: boolean
  /** 时间戳 tick，用于驱动「已进行 N 秒」刷新（由父组件轮询时更新） */
  nowMs: number
}>()

const html = computed(() => renderMarkdown(props.detail?.parsed_content?.markdown))

/** parsing 已进行秒数（now - updated_at；worker 置 parsing 时刷过 updated_at） */
const elapsedSec = computed(() => {
  if (!props.doc) return 0
  const started = new Date(props.doc.updated_at).getTime()
  if (Number.isNaN(started)) return 0
  return Math.max(0, Math.floor((props.nowMs - started) / 1000))
})

const metaLine = computed(() => {
  const d = props.doc
  if (!d) return ""
  const parts: (string | null)[] = [
    DOCUMENT_TYPE_LABELS[d.document_type],
    formatBytes(d.file_size),
  ]
  if (d.parse_status === "parsed") {
    parts.push(`${d.page_count} 页`, formatChars(d.markdown_chars))
    // tier 只存在于详情里（列表项不含）
    const tier = props.detail?.parsed_content?.tier
    if (tier) parts.push(`${tier} 档`)
    if (d.parse_elapsed_sec) parts.push(`耗时 ${formatDuration(d.parse_elapsed_sec)}`)
  }
  parts.push(formatDateTime(d.created_at))
  return parts.filter(Boolean).join(" · ")
})
</script>

<template>
  <div v-loading="loading" class="reader-wrap">
    <template v-if="doc">
      <div class="meta">{{ metaLine }}</div>

      <!-- 已解析：Markdown 正文，限宽 760px 居中（中文行长 40–45 字） -->
      <div v-if="html" class="reader" v-html="html" />

      <!-- 未出正文时按状态给明确说明，不留空白 -->
      <div v-else class="placeholder">
        <template v-if="doc.parse_status === 'pending'">
          <el-icon class="ph-icon"><Clock /></el-icon>
          <div>排队中，等待解析服务取任务…</div>
        </template>
        <template v-else-if="doc.parse_status === 'parsing'">
          <el-icon class="ph-icon is-loading"><Loading /></el-icon>
          <div>正在解析，已进行 {{ elapsedSec }} 秒</div>
          <div class="ph-sub">大文件通常需要 1–3 分钟（后端不提供实时进度百分比）</div>
        </template>
        <template v-else-if="doc.parse_status === 'failed_parse'">
          <el-icon class="ph-icon err"><WarningFilled /></el-icon>
          <div>解析失败</div>
          <div class="ph-sub err-text">{{ doc.parse_error || "未知错误" }}</div>
        </template>
        <template v-else>
          <div class="ph-sub">该档案暂无解析内容</div>
        </template>
      </div>
    </template>

    <el-empty v-else description="从左侧选择一个档案，查看解析内容" />
  </div>
</template>

<style scoped>
.reader-wrap {
  min-height: 200px;
}

.meta {
  color: #909399;
  font-size: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid #ebeef5;
  word-break: break-all;
}

/* 关键：正文限宽居中。1451px 满宽会让中文每行 85–95 字，换行易串行。 */
.reader {
  max-width: 760px;
  margin: 0 auto;
  padding-top: 16px;
  font-size: 14px;
  line-height: 1.85;
  color: #606266;
  word-break: break-word;
}

.reader :deep(h1),
.reader :deep(h2),
.reader :deep(h3) {
  color: #303133;
  margin: 18px 0 10px;
  line-height: 1.4;
}

.reader :deep(h2) {
  font-size: 16px;
}

.reader :deep(p) {
  margin: 0 0 12px;
}

.reader :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0;
}

.reader :deep(th),
.reader :deep(td) {
  border: 1px solid #dcdfe6;
  padding: 6px 10px;
  text-align: left;
}

.reader :deep(pre) {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  overflow-x: auto;
}

.reader :deep(img) {
  max-width: 100%;
}

.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 60px 20px;
  color: #909399;
  font-size: 13px;
  text-align: center;
}

.ph-icon {
  font-size: 28px;
  color: #c0c4cc;
  margin-bottom: 4px;
}

.ph-icon.err {
  color: #f56c6c;
}

.ph-sub {
  font-size: 12px;
  color: #a8abb2;
  max-width: 520px;
  word-break: break-all;
}

.err-text {
  color: #f56c6c;
}
</style>
