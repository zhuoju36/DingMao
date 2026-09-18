<script setup lang="ts">
// 全局布局：顶部导航 + 内容容器
// 所有需要登录的页面都套这个 layout，避免「裸奔」页面
import { computed } from "vue"
import { useRoute, useRouter } from "vue-router"
import { ElMessage, ElMessageBox, ElTooltip } from "element-plus"
import { useUserStore } from "@/stores/user"

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

// 角色中文标签（P1-2：不再显示英文枚举）
const roleLabels: Record<string, string> = {
  owner: "业主/建设单位",
  designer: "设计单位",
  supervisor: "监理单位",
  contractor: "施工单位",
  subcontractor: "其他分包商",
}
// header 显示的是「默认角色」（新建项目时的预填值）；
// 实际进入每个项目时由 Project.role 决定 LLM 视角。
const defaultRoleLabel = computed(() =>
  userStore.defaultRole ? roleLabels[userStore.defaultRole] ?? userStore.defaultRole : "未设置"
)

const displayName = computed(
  () => userStore.userInfo?.fullName || userStore.userInfo?.email || "用户"
)

// 当前激活的顶级导航
const activeNav = computed(() => {
  const p = route.path
  if (p.startsWith("/projects")) return "/projects"
  if (p.startsWith("/scenarios")) return "/scenarios"
  // 问诊页可能来自「项目」或「场景」两个入口，不硬指向某一项，避免误导
  if (p.startsWith("/consultation")) return ""
  return "/dashboard"
})

async function handleLogout() {
  try {
    await ElMessageBox.confirm("确认退出登录？", "退出", {
      confirmButtonText: "退出",
      cancelButtonText: "取消",
      type: "warning",
    })
  } catch {
    return
  }
  userStore.logout()
  ElMessage.success("已退出")
  router.push("/login")
}

function handleNav(path: string) {
  router.push(path)
}
</script>

<template>
  <div class="app-layout">
    <header class="app-header">
      <div class="brand" @click="handleNav('/dashboard')">
        <span class="logo">⚖️</span>
        <span class="title">钉铆</span>
      </div>

      <el-menu
        :default-active="activeNav"
        mode="horizontal"
        class="nav-menu"
        :ellipsis="false"
        @select="handleNav"
      >
        <el-menu-item index="/dashboard">工作台</el-menu-item>
        <el-menu-item index="/projects">项目档案</el-menu-item>
        <el-menu-item index="/scenarios">场景中心</el-menu-item>
      </el-menu>

      <div class="spacer" />

      <div class="user-area">
        <el-tooltip content="新建项目时的默认角色，每个项目可独立选择" placement="bottom">
          <el-tag size="small" type="info">默认 {{ defaultRoleLabel }}</el-tag>
        </el-tooltip>
        <el-dropdown trigger="click" class="ml-8">
          <span class="user-name">
            {{ displayName }}
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>
                {{ userStore.userInfo?.email }}
              </el-dropdown-item>
              <el-dropdown-item divided @click="handleLogout">
                退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.app-layout {
  min-height: 100vh;
  background: #f5f7fa;
}

.app-header {
  display: flex;
  align-items: center;
  height: 60px;
  padding: 0 24px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}

.logo {
  font-size: 20px;
}

.title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
}

.nav-menu {
  margin-left: 32px;
  border-bottom: none !important;
}

.spacer {
  flex: 1;
}

.user-area {
  display: flex;
  align-items: center;
}

.user-name {
  display: flex;
  align-items: center;
  gap: 2px;
  cursor: pointer;
  color: #606266;
  font-size: 14px;
  outline: none;
}

.ml-8 {
  margin-left: 8px;
}

.app-main {
  height: calc(100vh - 60px);
  overflow-y: auto;
}
</style>
