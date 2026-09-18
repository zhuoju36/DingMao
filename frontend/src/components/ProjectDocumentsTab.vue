<script setup lang="ts">
// 项目档案 Tab（P0-7-C）
// 依据 docs/product/upload-flow.md §七 UI/UX 设计。
//
// 职责：
//   - 拖拽 / 点击上传 → 确认对话框（类型 + 标题）→ 入队解析
//   - 列表 + 状态徽章 + pending/parsing 时轮询（ia.md 原则 5 状态永远可见）
//   - 抽屉预览解析出的 Markdown
//   - 下载原文 / 重新解析 / 删除
//
// 设计约束（勿轻易改）：
//   - 不显示解析进度条：后端不暴露真实百分比，画进度条等于编造
//   - parsing 行禁用删除/重解析：避免与 worker 抢同一文件（后端无锁）
//   - 轮询用列表接口：一次请求刷新所有行
import { computed, onMounted, onUnmounted, reactive, ref } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import type { UploadFile, UploadInstance } from "element-plus"
import {
  Delete,
  Document,
  Download,
  Picture,
  Refresh,
  UploadFilled,
  View,
} from "@element-plus/icons-vue"

import {
  DOCUMENT_TYPE_LABELS,
  deleteDocument,
  downloadDocument,
  getDocument,
  listDocuments,
  reparseDocument,
  uploadDocument,
  type DocumentListItem,
  type DocumentResponse,
  type DocumentType,
  type ParseStatus,
} from "@/api/documents"
import { renderMarkdown } from "@/utils/markdown"

const props = defineProps<{ projectId: number }>()

// 把档案数抛给父组件（Tab 徽章用），避免父组件为此再发一次列表请求
const emit = defineEmits<{ (e: "count-change", count: number): void }>()

// ===== 列表 + 轮询 =====

const items = ref<DocumentListItem[]>([])
const loading = ref(false)
/** 轮询 tick：既驱动列表刷新，也驱动「已进行 N 秒」文案更新 */
const nowMs = ref(Date.now())

const POLL_MS = 3000 // 解析 3s~数分钟，3s 粒度足够感知
let pollTimer: ReturnType<typeof setInterval> | null = null

const typeOptions = Object.entries(DOCUMENT_TYPE_LABELS) as [DocumentType, string][]

const statusMeta: Record<
  ParseStatus,
  { label: string; type: "success" | "warning" | "info" | "danger"; icon: string }
> = {
  pending: { label: "待解析", type: "info", icon: "⏳" },
  parsing: { label: "解析中", type: "warning", icon: "🔄" },
  parsed: { label: "已解析", type: "success", icon: "✅" },
  failed_upload: { label: "上传失败", type: "danger", icon: "❌" },
  failed_parse: { label: "解析失败", type: "danger", icon: "⚠️" },
  archived: { label: "已归档", type: "info", icon: "📦" },
}

const hasActive = computed(() =>
  items.value.some(
    (d) => d.parse_status === "pending" || d.parse_status === "parsing"
  )
)

async function load() {
  loading.value = true
  try {
    items.value = await listDocuments(props.projectId)
    nowMs.value = Date.now()
    emit("count-change", items.value.length)
  } catch {
    // 错误提示由 Axios 拦截器统一处理
  } finally {
    loading.value = false
    syncPolling()
  }
}

/** 有 pending/parsing 才轮询；全部终态则停（省请求） */
function syncPolling() {
  if (hasActive.value && pollTimer === null) {
    pollTimer = setInterval(load, POLL_MS)
  } else if (!hasActive.value && pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onMounted(load)
onUnmounted(() => {
  // 必须清理，否则离开页面后仍在请求
  if (pollTimer !== null) clearInterval(pollTimer)
  pollTimer = null
})

// ===== 展示格式化 =====

function fmtTime(v: string) {
  // 后端返回 UTC ISO（带 Z）。转本地时间展示。
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return "—"
  const p = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function fmtSize(bytes: number) {
  if (!bytes) return "—"
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function fmtChars(n: number) {
  if (!n) return "—"
  return n >= 10000 ? `${(n / 10000).toFixed(1)} 万字` : `${n} 字`
}

/** parsing 已进行秒数（now - updated_at；worker 置 parsing 时刷过 updated_at） */
function parsingSeconds(d: DocumentListItem) {
  const started = new Date(d.updated_at).getTime()
  if (Number.isNaN(started)) return 0
  return Math.max(0, Math.floor((nowMs.value - started) / 1000))
}

function isImage(d: DocumentListItem) {
  return d.mime_type.startsWith("image/")
}

const MAX_FILE_SIZE = 50 * 1024 * 1024

// ===== 上传 =====

const uploadRef = ref<UploadInstance>()
const dialogVisible = ref(false)
const pickedFile = ref<File | null>(null)
const fileError = ref("")
const uploading = ref(false)
const form = reactive<{ document_type: DocumentType; title: string }>({
  document_type: "contract",
  title: "",
})

/** el-upload 的 on-change：拿到 File → 清空内部列表 → 开确认对话框 */
function onFilePicked(file: UploadFile) {
  const raw = file.raw
  // 立即清空 el-upload 内部列表，使每次选择都是独立的一次（无需 limit 管理）
  uploadRef.value?.clearFiles()
  if (!raw) return

  pickedFile.value = raw
  fileError.value =
    raw.size > MAX_FILE_SIZE
      ? `文件 ${fmtSize(raw.size)} 超过 50MB 限制，请压缩或拆分后再上传`
      : ""
  form.document_type = "contract"
  form.title = raw.name.replace(/\.[^.]+$/, "").slice(0, 300) || raw.name
  dialogVisible.value = true
}

function closeDialog() {
  dialogVisible.value = false
  pickedFile.value = null
  fileError.value = ""
}

async function submitUpload() {
  const f = pickedFile.value
  if (!f || fileError.value) return
  if (!form.title.trim()) {
    fileError.value = "请填写文档标题"
    return
  }

  uploading.value = true
  try {
    await uploadDocument(props.projectId, f, form.document_type, form.title.trim())
    ElMessage.success("已上传，正在解析…")
    closeDialog()
    await load() // 列表顶部立即出现 pending 行，并由 load() 启动轮询
  } catch {
    // 拦截器已提示；保留对话框让用户改后重试
  } finally {
    uploading.value = false
  }
}

// ===== 详情抽屉 =====

const drawerVisible = ref(false)
const detail = ref<DocumentResponse | null>(null)
const detailLoading = ref(false)

const markdownHtml = computed(() =>
  renderMarkdown(detail.value?.parsed_content?.markdown)
)

async function openDetail(d: DocumentListItem) {
  drawerVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await getDocument(props.projectId, d.id)
  } catch {
    drawerVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

// ===== 行内操作 =====

/** 每行可用操作由状态决定（见 upload-flow.md §7.3） */
function canReparse(d: DocumentListItem) {
  return d.parse_status === "parsed" || d.parse_status === "failed_parse"
}
function canDelete(d: DocumentListItem) {
  return d.parse_status !== "parsing"
}

async function onDownload(d: DocumentListItem) {
  try {
    await downloadDocument(props.projectId, d.id, d.file_name)
  } catch {
    // 拦截器已提示
  }
}

async function onReparse(d: DocumentListItem) {
  try {
    await ElMessageBox.confirm(
      "重新解析会清空当前解析结果并重新排队，确定继续？",
      "重新解析",
      { type: "warning", confirmButtonText: "重新解析", cancelButtonText: "取消" }
    )
  } catch {
    return // 用户取消
  }
  try {
    const r = await reparseDocument(props.projectId, d.id)
    if (r.queued) ElMessage.success("已重新入队解析")
    else ElMessage.warning(r.message)
    await load()
  } catch {
    // 拦截器已提示
  }
}

async function onDelete(d: DocumentListItem) {
  try {
    await ElMessageBox.confirm(
      `确认删除「${d.title}」？将同时删除源文件与解析结果，此操作不可撤销。`,
      "删除档案",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteDocument(props.projectId, d.id)
    ElMessage.success("已删除")
    await load()
  } catch {
    // 拦截器已提示
  }
}
</script>

<template>
  <div class="doc-tab">
    <!-- 上传区：拖拽与点击同一路径（都开确认对话框） -->
    <el-upload
      ref="uploadRef"
      class="uploader"
      drag
      action="#"
      :auto-upload="false"
      :show-file-list="false"
      :on-change="onFilePicked"
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <div class="el-upload__text">
        拖拽文件到这里，或 <em>点击选择</em>
      </div>
      <template #tip>
        <div class="el-upload__tip">支持 PDF / 图片等，单个 ≤ 50MB</div>
      </template>
    </el-upload>

    <!-- 列表 -->
    <div v-loading="loading" class="list-wrap">
      <el-empty
        v-if="!items.length && !loading"
        description="还没有归档文件"
      >
        <div class="empty-hint">
          上传合同、签证单、监理通知单等，解析后可辅助问诊分析
        </div>
      </el-empty>

      <template v-else>
        <div class="list-head">归档文件（{{ items.length }}）</div>

        <div v-for="d in items" :key="d.id" class="doc-item">
          <div class="item-head">
            <el-icon class="doc-icon">
              <Picture v-if="isImage(d)" />
              <Document v-else />
            </el-icon>
            <span class="doc-title">{{ d.title }}</span>
            <el-tag size="small" :type="statusMeta[d.parse_status].type">
              {{ statusMeta[d.parse_status].icon }}
              {{ statusMeta[d.parse_status].label }}
            </el-tag>
            <div class="spacer" />
            <span class="doc-time">{{ fmtTime(d.created_at) }}</span>
          </div>

          <div class="item-meta">
            {{ DOCUMENT_TYPE_LABELS[d.document_type] }} ·
            {{ d.file_name }} · {{ fmtSize(d.file_size) }}
          </div>

          <!-- 状态副文本（诚实：不编造进度百分比） -->
          <div v-if="d.parse_status === 'parsing'" class="item-status">
            已进行 {{ parsingSeconds(d) }} 秒（大文件通常 1–3 分钟）
          </div>
          <div v-else-if="d.parse_status === 'pending'" class="item-status">
            排队中…
          </div>
          <div v-else-if="d.parse_status === 'parsed'" class="item-status ok">
            {{ d.page_count }} 页 · {{ fmtChars(d.markdown_chars) }}
            <template v-if="d.parse_elapsed_sec">
              · 耗时 {{ d.parse_elapsed_sec }}s
            </template>
          </div>
          <div v-else-if="d.parse_status === 'failed_parse'" class="item-status err">
            原因：{{ (d.parse_error || "未知错误").slice(0, 80) }}
          </div>

          <div class="item-actions">
            <el-button
              v-if="d.parse_status === 'parsed'"
              text
              type="primary"
              size="small"
              :icon="View"
              @click="openDetail(d)"
            >
              查看解析
            </el-button>
            <el-button
              text
              size="small"
              :icon="Download"
              @click="onDownload(d)"
            >
              下载原文
            </el-button>
            <el-button
              v-if="canReparse(d)"
              text
              size="small"
              :icon="Refresh"
              @click="onReparse(d)"
            >
              重新解析
            </el-button>
            <el-button
              text
              type="danger"
              size="small"
              :icon="Delete"
              :disabled="!canDelete(d)"
              @click="onDelete(d)"
            >
              删除
            </el-button>
          </div>
        </div>
      </template>
    </div>

    <!-- 上传确认对话框 -->
    <el-dialog
      v-model="dialogVisible"
      title="上传文件"
      width="520px"
      :close-on-click-modal="false"
      @close="closeDialog"
    >
      <el-form :model="form" label-width="90px">
        <el-form-item label="已选文件">
          <span class="picked-name">
            {{ pickedFile?.name }}
            <span class="muted">（{{ fmtSize(pickedFile?.size ?? 0) }}）</span>
          </span>
        </el-form-item>
        <el-form-item label="文件类型" required>
          <el-select v-model="form.document_type" style="width: 100%">
            <el-option
              v-for="[value, label] in typeOptions"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="文档标题" required>
          <el-input
            v-model="form.title"
            maxlength="300"
            placeholder="默认取文件名，可修改"
          />
        </el-form-item>
      </el-form>

      <el-alert
        v-if="fileError"
        :title="fileError"
        type="error"
        :closable="false"
        show-icon
      />

      <template #footer>
        <el-button @click="closeDialog">取消</el-button>
        <el-button
          type="primary"
          :loading="uploading"
          :disabled="!!fileError"
          @click="submitUpload"
        >
          开始上传
        </el-button>
      </template>
    </el-dialog>

    <!-- 解析结果抽屉 -->
    <el-drawer
      v-model="drawerVisible"
      :title="detail?.title ?? '解析结果'"
      size="60%"
    >
      <div v-loading="detailLoading" class="drawer-body">
        <template v-if="detail">
          <div class="drawer-meta">
            {{ DOCUMENT_TYPE_LABELS[detail.document_type] }} ·
            {{ detail.file_name }} · {{ fmtSize(detail.file_size) }} ·
            {{ fmtTime(detail.created_at) }}
          </div>
          <div
            v-if="detail.parsed_content"
            class="drawer-meta muted"
          >
            解析：{{ detail.parsed_content.tier }} 档 ·
            {{ detail.parsed_content.page_count }} 页 ·
            {{ fmtChars(detail.parsed_content.markdown_chars) }} ·
            耗时 {{ detail.parsed_content.elapsed_sec }}s
          </div>

          <!-- markdown-it 以 html:false 渲染，原始 HTML 被转义，无 XSS 风险 -->
          <div class="markdown-body" v-html="markdownHtml" />

          <el-empty
            v-if="!detail.parsed_content?.markdown"
            description="暂无解析内容"
          />
        </template>
      </div>

      <template #footer>
        <el-button
          v-if="detail"
          :icon="Download"
          @click="onDownload(detail as unknown as DocumentListItem)"
        >
          下载原文
        </el-button>
        <span class="muted footer-note">
          「在问诊中使用」将在 P0-7-D 提供
        </span>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.doc-tab {
  padding-top: 4px;
}

.uploader {
  margin-bottom: 4px;
}

.list-wrap {
  min-height: 120px;
}

.list-head {
  font-size: 14px;
  font-weight: 600;
  margin: 16px 0 8px;
}

.empty-hint {
  color: #909399;
  font-size: 13px;
  margin-top: 4px;
}

.doc-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px 14px;
  margin-bottom: 10px;
  transition: box-shadow 0.2s;
}

.doc-item:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.item-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.doc-icon {
  color: #909399;
}

.doc-title {
  font-weight: 600;
  font-size: 14px;
}

.spacer {
  flex: 1;
}

.doc-time {
  color: #909399;
  font-size: 12px;
}

.item-meta {
  color: #909399;
  font-size: 12px;
  margin-top: 6px;
}

.item-status {
  font-size: 12px;
  color: #e6a23c;
  margin-top: 4px;
}

.item-status.ok {
  color: #67c23a;
}

.item-status.err {
  color: #f56c6c;
}

.item-actions {
  margin-top: 6px;
  display: flex;
  gap: 4px;
}

.picked-name {
  word-break: break-all;
}

.muted {
  color: #909399;
}

.footer-note {
  font-size: 12px;
  margin-left: 12px;
}

.drawer-body {
  min-height: 200px;
}

.drawer-meta {
  font-size: 13px;
  margin-bottom: 6px;
  word-break: break-all;
}

.markdown-body {
  margin-top: 12px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}

/* 解析结果里的表格/代码块可能很宽，统一允许横向滚动 */
.markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #dcdfe6;
  padding: 6px 10px;
  text-align: left;
}

.markdown-body :deep(pre) {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  overflow-x: auto;
}

.markdown-body :deep(img) {
  max-width: 100%;
}
</style>
