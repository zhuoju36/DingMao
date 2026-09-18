/**
 * 回归验证：axios 默认 Content-Type 是否会破坏 FormData 上传。
 *
 * 背景：src/api/index.ts 曾在 axios.create() 里设 headers: {"Content-Type": "application/json"}。
 * axios 1.x 的 transformRequest 逻辑（lib/defaults/index.js:47,57）：
 *     if (isFormData(data)) return hasJSONContentType ? JSON.stringify(formDataToJSON(data)) : data
 * 于是 FormData 被转成 JSON → 后端 FastAPI 收不到 multipart 表单字段 → 422。
 *
 * 本脚本对**真实运行中的后端**做对照实验：
 *   A) 带 json 默认头  → 预期 422（复现 bug）
 *   B) 不带默认头      → 预期 201（修复后行为）
 *
 * 用法（需后端跑在 8000）：
 *   node scripts/verify-upload-formdata.mjs
 */
import axios from "axios"

const BASE = process.env.BASE || "http://127.0.0.1:8000/api/v1"
const email = `axiosprobe_${Date.now()}@test.com`

function makeClient(withJsonDefault) {
  return axios.create({
    baseURL: BASE,
    timeout: 60000,
    ...(withJsonDefault ? { headers: { "Content-Type": "application/json" } } : {}),
  })
}

function makeFormData() {
  const fd = new FormData()
  // 最小合法 PDF（1 页，含一段可提取文字）
  const pdf = new Blob(
    [
      `%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 60>>stream
BT /F1 12 Tf 20 100 Td (FormData Probe) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
trailer<</Root 1 0 R>>
%%EOF`,
    ],
    { type: "application/pdf" }
  )
  fd.append("file", pdf, "probe.pdf")
  fd.append("document_type", "contract")
  fd.append("title", "axios FormData 探针")
  return fd
}

async function main() {
  // --- 准备：注册 + 建项目 ---
  const anon = makeClient(false)
  const reg = await anon.post("/auth/register", {
    email,
    password: "testpass123",
    full_name: "AxiosProbe",
    default_role: "owner",
  })
  const token = reg.data.access_token
  const auth = { Authorization: `Bearer ${token}` }

  const proj = await anon.post("/projects", { name: "FormData 验证", role: "owner" }, { headers: auth })
  const projectId = proj.data.id
  console.log(`准备完成：project=${projectId}`)

  let failed = false

  // --- A) 带 json 默认头（复现 bug）---
  const bad = makeClient(true)
  try {
    await bad.post(`/projects/${projectId}/documents`, makeFormData(), { headers: auth })
    console.log("A) 带 json 默认头 → 竟然成功（预期 422）。说明 bug 场景不复现？")
  } catch (e) {
    const status = e.response?.status
    const detail = JSON.stringify(e.response?.data?.detail ?? e.response?.data ?? {})
    console.log(`A) 带 json 默认头 → HTTP ${status}`)
    console.log(`   detail: ${detail.slice(0, 200)}`)
    if (status === 422) {
      console.log("   ✓ 复现了 422（证明根因判断正确）")
    } else {
      console.log("   ⚠️ 不是 422，根因可能不止 Content-Type")
      failed = true
    }
  }

  // --- B) 不带默认头（修复后行为）---
  const good = makeClient(false)
  try {
    const r = await good.post(`/projects/${projectId}/documents`, makeFormData(), { headers: auth })
    console.log(`B) 不带默认头 → HTTP ${r.status}  doc_id=${r.data.id}  status=${r.data.parse_status}`)
    console.log("   ✓ 修复有效：FormData 正常以 multipart 发送")
    // 清理
    await good.delete(`/projects/${projectId}/documents/${r.data.id}`, { headers: auth })
  } catch (e) {
    const status = e.response?.status
    console.log(`B) 不带默认头 → HTTP ${status}  ← 预期 201`)
    console.log(`   detail: ${JSON.stringify(e.response?.data ?? {}).slice(0, 200)}`)
    failed = true
  }

  console.log("")
  console.log(failed ? "❌ 验证未通过" : "✅ 验证通过：根因已确认且修复有效")
  process.exit(failed ? 1 : 0)
}

main().catch((e) => {
  console.error("脚本异常:", e.message)
  process.exit(1)
})
