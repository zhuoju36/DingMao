// Markdown 渲染工具（P0-7-C）
//
// 用途：渲染 MinerU 解析出的 document.md。
//
// 安全说明：markdown-it 默认 html:false，会把原始 HTML 当纯文本转义，
// 因此即使 PDF 里含 <script> 也不会执行 —— 不需要额外引入 DOMPurify。
// 若将来把 html 改成 true，必须同时加消毒。
import MarkdownIt from "markdown-it"

export interface RenderEnv {
  /**
   * 是否把「相对路径图片」渲染成占位标记（默认 true）。
   *
   * 为什么：解析产物里的图片引用形如 `images/page_0_image_body_1.jpg`，
   * 它是**服务器磁盘上的相对路径**，浏览器按当前页面路由去解析必然 404，
   * 直接渲染会出现一排「碎图」图标，看起来像 bug。
   *
   * 现状：图片确实已随解析产物保存到 storage/parsed/{pid}/{did}/images/，
   * 但 MVP 尚未提供「鉴权下取二进制产物」的端点（<img src> 无法携带
   * Authorization 头），故先用可读占位标记替代。
   * TODO(P0-7-E)：加 artifacts 端点 + 前端 blob 加载后改为真实显示。
   */
  placeholderImages?: boolean
}

const md = new MarkdownIt({
  html: false, // 关键安全开关，勿改
  linkify: true, // 自动识别 URL
  breaks: true, // 单换行渲染为 <br>（贴合 PDF 解析结果）
})

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
}

// 覆盖图片渲染规则：相对路径图片 → 占位标记
md.renderer.rules.image = (tokens, idx, options, env: RenderEnv, self) => {
  const src = tokens[idx].attrGet("src") ?? ""
  const isRemoteOrInline = /^https?:|^data:|^blob:/.test(src)
  if (env?.placeholderImages !== false && !isRemoteOrInline) {
    // 用文件名（取末段）做可读标记，便于排查是哪张图
    const name = src.split("/").pop() ?? src
    return `<span class="md-img-placeholder" title="${escapeHtml(src)}">🖼 图片：${escapeHtml(name)}</span>`
  }
  return self.renderToken(tokens, idx, options)
}

export function renderMarkdown(
  text: string | null | undefined,
  env: RenderEnv = {}
): string {
  if (!text) return ""
  return md.render(text, { placeholderImages: true, ...env })
}
