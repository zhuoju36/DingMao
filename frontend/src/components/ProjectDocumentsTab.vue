<script setup lang="ts">
// 项目档案 Tab（P0-7-C，2026-09-18 布局修订：两栏主从）
// 依据 docs/product/upload-flow.md §7.0 / §7.3 / §7.4。
//
// 布局：
//   ≥1280px  左侧 400px 紧凑列表 + 右侧预览（正文限宽 760px 居中）
//   <1280px  同一个列表占满宽度 + 点行开抽屉
//
// 设计约束（勿轻易改）：
//   - 左栏行只显示状态，不放操作按钮（400px 放不下，会挤压长文件名）
//   - 正文限宽 760px：中文每行 40–45 字才舒适，满宽 1451px 会串行
//   - 不显示解析进度条：后端不暴露真实百分比，画进度条等于编造
//   - parsing 行禁用删除/重解析：避免与 worker 抢同一文件（后端无锁）
//   - 轮询用列表接口：一次请求刷新所有行
import { computed, onMounted, onUnmounted, reactive, ref } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import type { UploadFile, UploadInstance } from "element-plus"
import { Delete, Document, Download, Picture, Plus, Refresh } from "@element-plus/icons-vue"

import DocumentReader from "@/components/DocumentReader.vue"
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
import { formatBytes, formatChars, formatDuration } from "@/utils/format"

const props = defineProps<{ projectId: number }>()

// 把档案数抛给父组件（Tab 徽章用），避免父组件为此再发一次列表请求
const emit = defineEmits<{ (e: "count-change", count: number): void }>()

// ===== 响应式断点 =====

/** 宽屏（≥1280px）用两栏；窄屏回退成单栏列表 + 抽屉 */
const isWide = ref(true)
let mql: MediaQueryList | null = null

function onBreakpointChange(e: MediaQueryListEvent) {
  isWide.value = e.matches
  // 切到宽屏后右侧已有预览，抽屉就该收起来
  if (isWide.value) drawerVisible.value = false
}

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

// ===== 选中态 =====

const selectedId = ref<number | null>(null)
const selected = computed(
  () => items.value.find((d) => d.id === selectedId.value) ?? null
)
const detail = ref<DocumentResponse | null>(null)
const detailLoading = ref(false)

async function loadDetailIfParsed(d: DocumentListItem) {
  if (d.parse_status !== "parsed") {
    detail.value = null
    return
  }
  if (detail.value?.id === d.id) return // 已有同一份，不重复请求
  detailLoading.value = true
  try {
    detail.value = await getDocument(props.projectId, d.id)
  } catch {
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

async function selectDoc(d: DocumentListItem) {
  selectedId.value = d.id
  if (!isWide.value) drawerVisible.value = true
  await loadDetailIfParsed(d)
}

async function load() {
  loading.value = true
  try {
    items.value = await listDocuments(props.projectId)
    nowMs.value = Date.now()
    emit("count-change", items.value.length)

    // 同步选中项：轮询后若不更新，右侧状态会停在旧值
    if (selectedId.value !== null) {
      const fresh = items.value.find((d) => d.id === selectedId.value)
      if (!fresh) {
        // 已被删除
        selectedId.value = null
        detail.value = null
      } else if (
        fresh.parse_status === "parsed" &&
        detail.value?.id !== fresh.id
      ) {
        // 刚解析完成 → 补拉详情
        await loadDetailIfParsed(fresh)
      }
    } else if (items.value.length) {
      // 默认选中第一个，避免右侧一大块空白
      await selectDoc(items.value[0])
    }
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

onMounted(() => {
  mql = window.matchMedia("(min-width: 1280px)")
  isWide.value = mql.matches
  mql.addEventListener("change", onBreakpointChange)
  load()
})

onUnmounted(() => {
  // 必须清理，否则离开页面后仍在请求
  if (pollTimer !== null) clearInterval(pollTimer)
  pollTimer = null
  mql?.removeEventListener("change", onBreakpointChange)
})

// ===== 行内展示 =====

function isImage(d: DocumentListItem) {
  return d.mime_type.startsWith("image/")
}

/** parsing 已进行秒数（父组件 tick 驱动） */
function parsingSeconds(d: DocumentListItem) {
  const started = new Date(d.updated_at).getTime()
  if (Number.isNaN(started)) return 0
  return Math.max(0, Math.floor((nowMs.value - started) / 1000))
}

/** 左栏第 2 行：类型 · 大小 · 状态相关摘要 */
function rowSub(d: DocumentListItem) {
  const base = `${DOCUMENT_TYPE_LABELS[d.document_type]} · ${formatBytes(d.file_size)}`
  // 源文件缺失优先提示：这是异常状态，比解析摘要更重要
  if (!d.file_available) return `${base} · ⚠️ 源文件已丢失`
  if (d.parse_status === "parsing") return `${base} · 已进行 ${parsingSeconds(d)} 秒`
  if (d.parse_status === "pending") return `${base} · 排队中`
  if (d.parse_status === "parsed") {
    const bits = [`${d.page_count} 页`, formatChars(d.markdown_chars)]
    if (d.parse_elapsed_sec) bits.push(`${d.parse_elapsed_sec}s`)
    return `${base} · ${bits.join(" · ")}`
  }
  if (d.parse_status === "failed_parse") return `${base} · 解析失败，详见右侧`
  return base
}

// ===== 上传 =====

const MAX_FILE_SIZE = 50 * 1024 * 1024
const dialogVisible = ref(false)
const pickedFile = ref<File | null>(null)
const fileError = ref("")
const uploading = ref(false)

/** el-upload 实例（仅用于清空其内部文件列表） */
const uploadRef = ref<UploadInstance>()

const form = reactive<{ document_type: DocumentType; title: string }>({
  document_type: "contract",
  title: "",
})

/** 统一的落点：文件选择器与拖拽都进这里，再开确认对话框 */
function handleFile(raw: File) {
  pickedFile.value = raw
  fileError.value =
    raw.size > MAX_FILE_SIZE
      ? `文件 ${formatBytes(raw.size)} 超过 50MB 限制，请压缩或拆分后再上传`
      : ""
  form.document_type = "contract"
  // 默认标题 = 文件名去扩展名（可改）
  form.title = raw.name.replace(/\.[^.]+$/, "").slice(0, 300) || raw.name
  dialogVisible.value = true
}

/** el-upload 的 on-change：取 File → 清空内部列表 → 走统一落点 */
function onFilePicked(file: UploadFile) {
  const raw = file.raw
  // 立即清空 el-upload 内部列表，使每次选择都是独立的一次（无需 limit 管理）
  uploadRef.value?.clearFiles()
  if (raw) handleFile(raw)
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

// ===== 拖拽到左栏（整块可拖）=====

const dragActive = ref(false)
let dragDepth = 0

function onDragEnter() {
  dragDepth += 1
  dragActive.value = true
}
function onDragLeave() {
  dragDepth -= 1
  if (dragDepth <= 0) {
    dragDepth = 0
    dragActive.value = false
  }
}
function onDrop(e: DragEvent) {
  dragDepth = 0
  dragActive.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) handleFile(f)
}

// ===== 详情抽屉（仅窄屏用）=====

const drawerVisible = ref(false)

// ===== 操作 =====

function canReparse(d: DocumentListItem) {
  // 源文件没了就无法重解析（后端会 422，不如直接禁用）
  return (
    d.file_available &&
    (d.parse_status === "parsed" || d.parse_status === "failed_parse")
  )
}
function canDelete(d: DocumentListItem) {
  return d.parse_status !== "parsing"
}
function canDownload(d: DocumentListItem) {
  return d.file_available
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
    detail.value = null
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
    if (selectedId.value === d.id) {
      selectedId.value = null
      detail.value = null
      drawerVisible.value = false
    }
    await load()
  } catch {
    // 拦截器已提示
  }
}
</script>

<template>
  <div class="doc-tab">
    <!-- ============ 宽屏：两栏主从 ============ -->
    <div v-if="isWide" class="split">
      <!-- 左栏：固定 400px 紧凑列表；整块可接收拖拽 -->
      <aside
        class="pane-left"
        :class="{ 'drag-active': dragActive }"
        @dragenter.prevent="onDragEnter"
        @dragover.prevent
        @dragleave.prevent="onDragLeave"
        @drop.prevent="onDrop"
      >
        <div class="left-head">
          <el-upload
            ref="uploadRef"
            action="#"
            :auto-upload="false"
            :show-file-list="false"
            :on-change="onFilePicked"
          >
            <el-button type="primary" size="small" :icon="Plus">上传文件</el-button>
          </el-upload>
          <span class="count">{{ items.length }} 个档案</span>
        </div>
        <div class="drop-tip">将文件拖到此处也可上传</div>

        <div v-loading="loading" class="list">
          <el-empty
            v-if="!items.length && !loading"
            description="还没有归档文件"
          >
            <div class="empty-hint">
              上传合同、签证单、监理通知单等<br />解析后可辅助问诊分析
            </div>
          </el-empty>

          <div
            v-for="d in items"
            :key="d.id"
            class="row2"
            :class="{ on: d.id === selectedId }"
            @click="selectDoc(d)"
          >
            <div class="l1">
              <el-icon class="doc-icon">
                <Picture v-if="isImage(d)" />
                <Document v-else />
              </el-icon>
              <span class="name">{{ d.title }}</span>
              <span style="flex: 1" />
              <span class="badge" :class="`b-${statusMeta[d.parse_status].type}`">
                {{ statusMeta[d.parse_status].icon }}
              </span>
            </div>
            <div class="l2">{{ rowSub(d) }}</div>
          </div>
        </div>

        <!-- 拖拽悬停提示：整个左栏变虚线框 -->
        <div v-if="dragActive" class="drop-overlay">
          <div class="drop-overlay-inner">松开即选择文件</div>
        </div>
      </aside>

      <!-- 右栏：预览。操作按钮放这里（左栏 400px 放不下） -->
      <section class="pane-right">
        <template v-if="selected">
          <div class="right-head">
            <span class="right-title">{{ selected.title }}</span>
            <el-tag size="small" :type="statusMeta[selected.parse_status].type">
              {{ statusMeta[selected.parse_status].icon }}
              {{ statusMeta[selected.parse_status].label }}
            </el-tag>
            <span style="flex: 1" />
            <el-button
              text
              size="small"
              :icon="Download"
              :disabled="!canDownload(selected)"
              @click="onDownload(selected)"
            >
              下载原文
            </el-button>
            <el-button
              v-if="canReparse(selected)"
              text
              size="small"
              :icon="Refresh"
              @click="onReparse(selected)"
            >
              重新解析
            </el-button>
            <el-button
              text
              type="danger"
              size="small"
              :icon="Delete"
              :disabled="!canDelete(selected)"
              @click="onDelete(selected)"
            >
              删除
            </el-button>
          </div>
          <div v-if="!selected.file_available" class="missing-file-alert">
            <el-alert
              type="warning"
              :closable="false"
              show-icon
              title="源文件已丢失"
              description="数据库记录仍在（解析结果可读），但存储中找不到原始文件，因此无法下载原文或重新解析。可删除本记录后重新上传。"
            />
          </div>
          <DocumentReader
            :doc="selected"
            :detail="detail"
            :loading="detailLoading"
            :now-ms="nowMs"
          />
        </template>

        <el-empty v-else description="从左侧选择一个档案，查看解析内容" />
      </section>
    </div>

    <!-- ============ 窄屏：单栏列表 + 抽屉 ============ -->
    <div v-else class="narrow">
      <div class="left-head">
        <el-upload
          action="#"
          :auto-upload="false"
          :show-file-list="false"
          :on-change="onFilePicked"
        >
          <el-button type="primary" size="small" :icon="Plus">上传文件</el-button>
        </el-upload>
        <span class="count">{{ items.length }} 个档案</span>
      </div>

      <div v-loading="loading" class="list">
        <el-empty v-if="!items.length && !loading" description="还没有归档文件">
          <div class="empty-hint">
            上传合同、签证单、监理通知单等<br />解析后可辅助问诊分析
          </div>
        </el-empty>

        <div
          v-for="d in items"
          :key="d.id"
          class="row2"
          :class="{ on: d.id === selectedId }"
          @click="selectDoc(d)"
        >
          <div class="l1">
            <el-icon class="doc-icon">
              <Picture v-if="isImage(d)" />
              <Document v-else />
            </el-icon>
            <span class="name">{{ d.title }}</span>
            <span style="flex: 1" />
            <span class="badge" :class="`b-${statusMeta[d.parse_status].type}`">
              {{ statusMeta[d.parse_status].icon }} {{ statusMeta[d.parse_status].label }}
            </span>
          </div>
          <div class="l2">{{ rowSub(d) }}</div>
        </div>
      </div>

      <!-- 窄屏用抽屉读正文；操作在抽屉页脚 -->
      <el-drawer
        v-model="drawerVisible"
        :title="selected?.title ?? '解析结果'"
        size="88%"
      >
        <el-alert
          v-if="selected && !selected.file_available"
          class="mb-12"
          type="warning"
          :closable="false"
          show-icon
          title="源文件已丢失"
          description="数据库记录仍在（解析结果可读），但存储中找不到原始文件，因此无法下载原文或重新解析。"
        />
        <DocumentReader
          :doc="selected"
          :detail="detail"
          :loading="detailLoading"
          :now-ms="nowMs"
        />
        <template #footer>
          <div v-if="selected" class="drawer-actions">
            <el-button
              size="small"
              :icon="Download"
              :disabled="!canDownload(selected)"
              @click="onDownload(selected)"
            >
              下载原文
            </el-button>
            <el-button
              v-if="canReparse(selected)"
              size="small"
              :icon="Refresh"
              @click="onReparse(selected)"
            >
              重新解析
            </el-button>
            <el-button
              size="small"
              type="danger"
              :icon="Delete"
              :disabled="!canDelete(selected)"
              @click="onDelete(selected)"
            >
              删除
            </el-button>
          </div>
        </template>
      </el-drawer>
    </div>

    <!-- ============ 上传确认对话框（两种布局共用） ============ -->
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
            <span class="muted">（{{ formatBytes(pickedFile?.size ?? 0) }}）</span>
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
  </div>
</template>

<style scoped>
.doc-tab {
  padding-top: 4px;
}

/* ===== 两栏 ===== */
.split {
  display: flex;
  align-items: stretch;
  min-height: 560px;
}

.pane-left {
  position: relative;
  width: 400px;
  flex: 0 0 400px;
  border-right: 1px solid #ebeef5;
  padding-right: 12px;
  display: flex;
  flex-direction: column;
}

.pane-left.drag-active {
  outline: 2px dashed #409eff;
  outline-offset: -6px;
  border-radius: 4px;
}

.pane-right {
  flex: 1 1 auto;
  min-width: 0;
  padding-left: 20px;
}

.left-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 8px;
}

.count {
  font-size: 12px;
  color: #909399;
  margin-left: auto;
}

.drop-tip {
  font-size: 12px;
  color: #c0c4cc;
  padding-bottom: 8px;
  border-bottom: 1px solid #f2f6fc;
  margin-bottom: 8px;
}

.list {
  flex: 1 1 auto;
  overflow-y: auto;
  max-height: 640px;
}

/* ===== 2 行式行（一屏 ~12 个） ===== */
.row2 {
  padding: 9px 10px;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid transparent;
}

.row2:hover {
  background: #f5f7fa;
}

.row2.on {
  background: #ecf5ff;
  border-color: #b3d8ff;
}

.l1 {
  display: flex;
  align-items: center;
  gap: 6px;
}

.doc-icon {
  color: #909399;
  flex: 0 0 auto;
}

.name {
  font-weight: 600;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.l2 {
  color: #909399;
  font-size: 12px;
  margin-top: 3px;
  padding-left: 20px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.badge {
  font-size: 12px;
  flex: 0 0 auto;
}

.b-success {
  color: #67c23a;
}
.b-warning {
  color: #e6a23c;
}
.b-danger {
  color: #f56c6c;
}
.b-info {
  color: #909399;
}

/* 拖拽悬停遮罩 */
.drop-overlay {
  position: absolute;
  inset: 0;
  background: rgba(236, 245, 255, 0.92);
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  pointer-events: none;
}

.drop-overlay-inner {
  color: #409eff;
  font-size: 14px;
  font-weight: 600;
}

/* ===== 右侧 ===== */
.right-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 10px;
  border-bottom: 1px solid #ebeef5;
}

.right-title {
  font-size: 15px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 45%;
}

/* ===== 窄屏 ===== */
.narrow {
  display: flex;
  flex-direction: column;
}

.drawer-actions {
  display: flex;
  gap: 8px;
}

/* ===== 共用 ===== */
.empty-hint {
  color: #909399;
  font-size: 13px;
  margin-top: 4px;
  line-height: 1.7;
}

.missing-file-alert {
  margin-bottom: 12px;
}

.mb-12 {
  margin-bottom: 12px;
}

.picked-name {
  word-break: break-all;
}

.muted {
  color: #909399;
}
</style>
