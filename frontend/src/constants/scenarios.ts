// 场景注册表
//
// 按 docs/product/ia.md 的「顶级场景菜单」架构：
// 场景是顶级导航项，跨项目聚合工作流。
// 新增场景只需在此登记，Scenarios / ProjectDetail 会自动呈现。

export interface ScenarioDef {
  /** 后端 Consultation.scenario 的取值 */
  key: string
  name: string
  icon: string
  /** 一句话说明该场景解决什么问题 */
  description: string
  /** 典型使用时机 */
  whenToUse: string
  /** available = 已可用；planned = 已规划待实现 */
  status: "available" | "planned"
}

export const SCENARIOS: ScenarioDef[] = [
  {
    key: "contract_review",
    name: "合同审查",
    icon: "📄",
    description: "贴入合同条款，AI 识别风险并给出红黄绿分级与修改建议",
    whenToUse: "签约前、收到对方合同草稿时",
    status: "available",
  },
  {
    key: "variation",
    name: "变更扯皮",
    icon: "⚖️",
    description: "描述变更/签证/索赔争议事实，AI 梳理证据链与处理路径",
    whenToUse: "口头变更未签证、业主拒付、工期争议时",
    status: "available",
  },
  {
    key: "standard_lookup",
    name: "强条速查",
    icon: "📐",
    description: "按行为或构件查国家强制性条文，判断是否触碰红线",
    whenToUse: "现场拿不准做法是否合规时",
    status: "planned",
  },
  {
    key: "accident_review",
    name: "事故责任初评",
    icon: "🚨",
    description: "还原事故经过，初步判断各方责任与后续处理路径",
    whenToUse: "质量/安全事故发生后",
    status: "planned",
  },
  {
    key: "bidding",
    name: "招投标合规",
    icon: "📋",
    description: "审查招标文件与投标文件，识别废标与围串标风险",
    whenToUse: "投标前、招标文件答疑期",
    status: "planned",
  },
  {
    key: "settlement",
    name: "结算争议",
    icon: "💰",
    description: "审计争议、送审资料、造价核减的应对思路",
    whenToUse: "竣工结算、审计核减时",
    status: "planned",
  },
]

export const SCENARIO_MAP: Record<string, ScenarioDef> = Object.fromEntries(
  SCENARIOS.map((s) => [s.key, s])
)

/** 场景中文名（找不到时回退到原始 key） */
export function scenarioName(key: string): string {
  return SCENARIO_MAP[key]?.name ?? key
}

/** 场景图标 */
export function scenarioIcon(key: string): string {
  return SCENARIO_MAP[key]?.icon ?? "•"
}

/** 可创建问诊的场景（后端会校验 scenario 合法性） */
export function isAvailable(key: string): boolean {
  return SCENARIO_MAP[key]?.status === "available"
}
