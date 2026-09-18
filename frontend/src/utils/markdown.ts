// Markdown 渲染工具（P0-7-C）
//
// 唯一用途：渲染 MinerU 解析出的 document.md。
//
// 安全说明：markdown-it 默认 html:false，会把原始 HTML 当纯文本转义，
// 因此即使 PDF 里含 <script> 也不会执行 —— 不需要额外引入 DOMPurify。
// 若将来把 html 改成 true，必须同时加消毒。
import MarkdownIt from "markdown-it"

const md = new MarkdownIt({
  html: false, // 关键安全开关，勿改
  linkify: true, // 自动识别 URL
  breaks: true, // 单换行渲染为 <br>（贴合 PDF 解析结果）
})

export function renderMarkdown(text: string | null | undefined): string {
  if (!text) return ""
  return md.render(text)
}
