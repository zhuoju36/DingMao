// 路由配置
import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router"
import AppLayout from "@/components/AppLayout.vue"

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "Login",
    component: () => import("@/views/Login.vue"),
    meta: { requiresAuth: false },
  },
  {
    // 所有需登录页面都嵌在 AppLayout 下（统一导航栏）
    path: "/",
    component: AppLayout,
    meta: { requiresAuth: true },
    children: [
      { path: "", redirect: "/dashboard" },
      {
        path: "dashboard",
        name: "Dashboard",
        component: () => import("@/views/Dashboard.vue"),
      },
      {
        path: "projects",
        name: "Projects",
        component: () => import("@/views/Projects.vue"),
      },
      {
        path: "projects/:id",
        name: "ProjectDetail",
        component: () => import("@/views/ProjectDetail.vue"),
      },
      {
        path: "scenarios",
        name: "Scenarios",
        component: () => import("@/views/Scenarios.vue"),
      },
      {
        path: "scenarios/:scenario",
        name: "ScenarioDetail",
        component: () => import("@/views/ScenarioDetail.vue"),
      },
      {
        path: "consultation/:id",
        name: "Consultation",
        component: () => import("@/views/Consultation.vue"),
      },
    ],
  },
  {
    // 兜底：未匹配路由回工作台
    path: "/:pathMatch(.*)*",
    redirect: "/dashboard",
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫
router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem("token")
  const requiresAuth = to.meta.requiresAuth !== false

  if (requiresAuth && !token) {
    next("/login")
  } else {
    next()
  }
})

export default router
