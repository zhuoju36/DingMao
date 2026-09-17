"""全局常量。

放跨模块共享的固定文本/配置，避免各处硬编码漂移。
"""

# 免责声明（AGENTS.md 应用原则 4：文书输出前必须显示前置免责声明）
#
# 使用位置：
# - app/services/llm_mock.py       生成报告时带出
# - app/services/consultation_engine.py  流式报告 done 事件带出
# - 前端 Consultation.vue          渲染在报告卡片顶部
DISCLAIMER = (
    "⚠️ 本报告由 AI 生成，仅供工程人员参考，不构成法律意见。"
    "重大决策前请由执业律师复核。"
)
