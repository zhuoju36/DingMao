<script setup lang="ts">
// 项目列表 - 接真实后端
import { onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { ElMessage } from "element-plus"
import apiClient from "@/api"

interface Project {
  id: number
  name: string
  code: string | null
  description: string | null
  location: string | null
  contract_amount: string | null
  contract_start_date: string | null
  contract_end_date: string | null
  contract_text: string | null
  owner_org: string | null
  design_org: string | null
  supervisor_org: string | null
  contractor_org: string | null
}

const router = useRouter()
const projects = ref<Project[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const creating = ref(false)

// 新建表单
const form = ref({
  name: "",
  code: "",
  location: "",
  contractor_org: "",
  owner_org: "",
})

async function fetchProjects() {
  loading.value = true
  try {
    const res = await apiClient.get<{ items: Project[]; total: number }>(
      "/projects"
    )
    projects.value = res.items
  } catch {
    ElMessage.error("加载项目列表失败")
  } finally {
    loading.value = false
  }
}

async function createProject() {
  if (!form.value.name.trim()) {
    ElMessage.warning("请填写项目名称")
    return
  }
  creating.value = true
  try {
    const created = await apiClient.post<Project>("/projects", {
      name: form.value.name,
      code: form.value.code || null,
      location: form.value.location || null,
      contractor_org: form.value.contractor_org || null,
      owner_org: form.value.owner_org || null,
    })
    ElMessage.success(`项目已创建 #${created.id}`)
    showCreateDialog.value = false
    form.value = { name: "", code: "", location: "", contractor_org: "", owner_org: "" }
    await fetchProjects()
    // 跳到项目详情
    router.push(`/projects/${created.id}`)
  } catch (e) {
    const msg = e instanceof Error ? e.message : "创建失败"
    ElMessage.error(`创建失败: ${msg}`)
  } finally {
    creating.value = false
  }
}

function goToProject(id: number) {
  router.push(`/projects/${id}`)
}

onMounted(fetchProjects)
</script>

<template>
  <div class="projects-page">
    <div class="page-header flex-between">
      <h2>项目档案</h2>
      <el-button type="primary" @click="showCreateDialog = true">
        <el-icon><Plus /></el-icon>
        新建项目
      </el-button>
    </div>

    <el-table
      v-loading="loading"
      :data="projects"
      stripe
      empty-text="还没有项目，点击右上角创建"
    >
      <el-table-column prop="code" label="工程编号" width="160">
        <template #default="{ row }">
          <span v-if="row.code">{{ row.code }}</span>
          <el-text v-else type="info">-</el-text>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="项目名称" min-width="200" />
      <el-table-column prop="location" label="地点" width="180">
        <template #default="{ row }">
          <span v-if="row.location">{{ row.location }}</span>
          <el-text v-else type="info">-</el-text>
        </template>
      </el-table-column>
      <el-table-column label="合同金额" width="160">
        <template #default="{ row }">
          <span v-if="row.contract_amount">¥ {{ Number(row.contract_amount).toLocaleString() }}</span>
          <el-text v-else type="info">-</el-text>
        </template>
      </el-table-column>
      <el-table-column prop="contractor_org" label="施工单位" min-width="160">
        <template #default="{ row }">
          <span v-if="row.contractor_org">{{ row.contractor_org }}</span>
          <el-text v-else type="info">-</el-text>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button text type="primary" @click="goToProject(row.id)">
            进入
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建项目对话框 -->
    <el-dialog v-model="showCreateDialog" title="新建项目" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="项目名称" required>
          <el-input v-model="form.name" placeholder="例如：XX 综合楼工程" />
        </el-form-item>
        <el-form-item label="工程编号">
          <el-input v-model="form.code" placeholder="例如：PRJ-2026-001（可选）" />
        </el-form-item>
        <el-form-item label="工程地点">
          <el-input v-model="form.location" placeholder="例如：广州市天河区" />
        </el-form-item>
        <el-form-item label="建设单位">
          <el-input v-model="form.owner_org" placeholder="例如：XX 地产公司" />
        </el-form-item>
        <el-form-item label="施工单位">
          <el-input v-model="form.contractor_org" placeholder="例如：XX 建工集团" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createProject">
          创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.projects-page {
  padding: 24px;
  background: #fff;
  min-height: calc(100vh - 60px);
}

.page-header {
  margin-bottom: 16px;
}

.flex-between {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
