// 展示格式化工具（P0-7-C 布局修订时抽取）
//
// 抽取时机：原先格式函数内联在 ProjectDocumentsTab.vue 里，
// 布局改为两栏后 DocumentReader.vue 也需要同一套格式 → 出现第 2 个消费方时才抽。

/** 字节数 → "12.5 MB" / "820 KB" / "512 B" */
export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "—"
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** 字符数 → "1.8 万字" / "420 字" */
export function formatChars(n: number | null | undefined): string {
  if (!n) return "—"
  return n >= 10000 ? `${(n / 10000).toFixed(1)} 万字` : `${n} 字`
}

/**
 * ISO 字符串 → "2026-09-18 14:23"（本地时区）
 *
 * 后端返回 UTC（带 Z），必须转本地展示 —— 直接 slice 会差 8 小时。
 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  const p = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 秒数 → "28 秒" / "1 分 12 秒" */
export function formatDuration(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return "—"
  const s = Math.max(0, Math.floor(sec))
  if (s < 60) return `${s} 秒`
  return `${Math.floor(s / 60)} 分 ${s % 60} 秒`
}
