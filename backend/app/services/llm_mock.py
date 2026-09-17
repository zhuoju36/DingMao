"""Mock LLM 报告生成。

W1 阶段不调用真实 LLM，基于关键词匹配 + 预设结论模板生成审查报告。
W2/W3 接入真实 LLM 时，本文件作为 fallback 保留。

设计原则：
- 模拟"三源证据"结构（🟦事实 + 🟨法条 + 🟥强条）
- 红/黄/绿分级
- 每条结论附推理链
"""

from typing import Any

from app.models.user import UserRole

# 关键词 -> 风险结论（mock 知识库）
# 实际接入 LLM 后，这些来自行为-强条映射表 + 知识库检索
_KEYWORD_RULES: list[dict[str, Any]] = [
    {
        "keywords": ["背靠背", "背靠背付款", "业主付款后再支付"],
        "level": "yellow",
        "title": "背靠背付款条款",
        "content": (
            "合同约定以业主付款为支付前提。该条款将业主的付款风险转嫁给施工方，"
            "实践中极易导致施工方资金链紧张、争议频发。"
        ),
        "law_refs": [
            {
                "code": "民法典",
                "article": "第五百五十二条",
                "content_preview": "当事人可以约定一方债务人不履行债务时由第三人履行",
                "note": "背靠背条款效力争议",
            }
        ],
        "standard_refs": [],
        "reasoning": "背靠背条款效力本身无明文禁止，但司法实践中多按'附条件'或'附期限'处理，对施工方极为不利。",
    },
    {
        "keywords": ["暂定价", "暂定价格", "暂估价"],
        "level": "yellow",
        "title": "暂定价条款",
        "content": (
            "合同存在暂定价项目，最终结算应以实际确认价为准。"
            "建议明确暂定价的确认程序、时限、确认方式（询价/招标/审计）。"
        ),
        "law_refs": [
            {
                "code": "建设工程价款结算暂行办法",
                "article": "第十条",
                "content_preview": "工程价款结算应按合同约定办理",
            }
        ],
        "standard_refs": [],
        "reasoning": "暂定价未明确结算方式将导致结算争议。",
    },
    {
        "keywords": ["审计", "审计机关", "审计决定"],
        "level": "yellow",
        "title": "审计条款",
        "content": (
            "合同约定以审计机关审计结果作为结算依据。"
            "审计周期长、不确定性高，可能导致结算久拖不决。"
        ),
        "law_refs": [
            {
                "code": "民法典",
                "article": "第七百九十三条",
                "content_preview": "建设工程施工合同纠纷的处理",
            }
        ],
        "standard_refs": [],
        "reasoning": "司法实践对审计条款的处理有分歧，建议明确审计时限与异议机制。",
    },
    {
        "keywords": ["质量保修", "保修期", "缺陷责任期"],
        "level": "green",
        "title": "质量保修条款",
        "content": "合同对质量保修期做了约定，符合行业惯例。",
        "law_refs": [
            {
                "code": "建设工程质量管理条例",
                "article": "第四十条",
                "content_preview": "建设工程的最低保修期限",
            }
        ],
        "standard_refs": [],
        "reasoning": "保修期约定不低于法定最低期限即可控。",
    },
    {
        "keywords": ["违约金", "逾期违约金"],
        "level": "yellow",
        "title": "违约金比例",
        "content": (
            "合同约定了逾期违约金。请核实比例是否过高（超过实际损失 30% 可能被调减）。"
        ),
        "law_refs": [
            {
                "code": "民法典",
                "article": "第五百八十五条",
                "content_preview": "约定的违约金过分高于造成的损失的，当事人可以请求人民法院或者仲裁机构予以适当减少",
            }
        ],
        "standard_refs": [],
        "reasoning": "违约金超过实际损失 30% 以上的，司法实践中通常予以调减。",
    },
]


# 角色视角下的关注点差异（AGENTS.md 决策 5）
_ROLE_FOCUS: dict[UserRole, list[str]] = {
    UserRole.OWNER: [
        "关注：付款节点、质量验收、违约责任界定",
        "风险：监理/施工方责任转嫁条款",
    ],
    UserRole.DESIGNER: [
        "关注：设计变更程序、知识产权归属、责任限额",
        "风险：背靠背付款对设计费回收的影响",
    ],
    UserRole.SUPERVISOR: [
        "关注：监理职责范围、监理费支付节点、责任豁免",
        "风险：质量连带责任的兜底条款",
    ],
    UserRole.CONTRACTOR: [
        "关注：付款节点、工期顺延、签证索赔程序",
        "风险：背靠背付款、审计陷阱、违约金比例",
    ],
    UserRole.SUBCONTRACTOR: [
        "关注：与总包的结算节点、配合义务、责任划分",
        "风险：被总包背靠背转嫁",
    ],
}


def generate_contract_review_report(
    contract_text: str,
    role: UserRole,
) -> dict[str, Any]:
    """生成合同审查 Mock 报告。

    返回结构（可直接序列化）：
        {
            "summary": str,
            "conclusions": [
                {
                    "level": "red" | "yellow" | "green",
                    "title": str,
                    "content": str,
                    "law_refs": [...],
                    "standard_refs": [...],
                    "reasoning_chain": str,
                    "counter_arguments": str,
                }
            ],
            "disclaimer": str,
        }
    """
    findings: list[dict[str, Any]] = []
    text_lower = contract_text.lower()

    for rule in _KEYWORD_RULES:
        if any(kw.lower() in text_lower for kw in rule["keywords"]):
            findings.append(
                {
                    "level": rule["level"],
                    "title": rule["title"],
                    "content": rule["content"],
                    "fact_refs": [],  # W1 不区分事实索引
                    "law_refs": rule["law_refs"],
                    "standard_refs": rule["standard_refs"],
                    "reasoning_chain": rule["reasoning"],
                    "counter_arguments": "如需争议应对或条款修改建议，请咨询执业律师。",
                }
            )

    # 无命中时给一条绿色
    if not findings:
        findings.append(
            {
                "level": "green",
                "title": "未发现显著风险",
                "content": (
                    "在当前文本范围内，未匹配到预设的高风险关键词。"
                    "本结论仅基于关键词匹配，不构成法律意见。"
                ),
                "fact_refs": [],
                "law_refs": [],
                "standard_refs": [],
                "reasoning_chain": "Mock 报告：基于关键词 '背靠背/暂定价/审计/违约金/保修期' 扫描。",
                "counter_arguments": "如有具体争议焦点，请补充条款细节。",
            }
        )

    # 角色视角说明
    role_notes = _ROLE_FOCUS.get(role, [])

    summary = (
        f"基于您当前角色（{role.value}），本报告重点关注："
        + "; ".join(role_notes)
        + f"。共识别 {len(findings)} 项审查要点。"
    )

    return {
        "summary": summary,
        "conclusions": findings,
        "disclaimer": (
            "⚠️ 本报告由 Mock LLM 生成，仅用于流程演示，不构成法律意见。"
            "重大决策前请由执业律师复核。"
        ),
    }
