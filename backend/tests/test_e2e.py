"""端到端测试：注册 → 登录 → 项目 → 问诊 → 报告 → 知识库搜索。

使用 httpx.AsyncClient + ASGI transport，所有请求共享同一 event loop。
"""

import asyncio
import os
import random

os.environ.setdefault("APP_ENV", "development")

from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_health(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    print("✓ health endpoint")


async def test_register_and_login(client: AsyncClient) -> str:
    """注册 + 登录，返回 access_token。"""
    email = f"test{random.randint(10000, 99999)}@dingmao.com"
    password = "testpass123"

    # 注册
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "测试用户",
            "role": "supervisor",
        },
    )
    assert r.status_code == 201, f"register failed: {r.status_code} {r.text}"
    token = r.json()["access_token"]
    print(f"✓ 注册成功 ({email})")

    # 登录
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    token = r.json()["access_token"]
    print("✓ 登录成功")

    # me
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == email
    print("✓ /auth/me 正确")

    return token


async def test_create_project(client: AsyncClient, token: str) -> int:
    """创建项目，返回 project_id。"""
    r = await client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "XX 综合楼工程",
            "code": "PRJ-2026-001",
            "location": "广州市天河区",
            "contract_amount": "12800000.00",
            "owner_org": "XX 地产公司",
            "contractor_org": "XX 工程集团",
            "contract_text": "本合同采用背靠背付款方式，业主付款后再支付施工方。审计机关审计结果作为结算依据。",
        },
    )
    assert r.status_code == 201, f"create project failed: {r.status_code} {r.text}"
    project = r.json()
    print(f"✓ 创建项目 #{project['id']} ({project['name']})")
    return project["id"]


async def test_contract_review_e2e(client: AsyncClient, token: str, project_id: int) -> None:
    """完整的合同审查端到端。"""
    # 1. 创建问诊
    r = await client.post(
        "/api/v1/consultations",
        headers={"Authorization": f"Bearer {token}"},
        json={"project_id": project_id, "scenario": "contract_review"},
    )
    assert r.status_code == 201, r.text
    consultation_id = r.json()["id"]
    print(f"✓ 创建问诊 #{consultation_id}")

    # 2. 提交合同文本（包含 背靠背 + 审计 + 违约金 关键词）
    contract = (
        "本合同付款采用背靠背方式，业主付款后再支付施工方。"
        "暂定价以审计机关审计结果为准。"
        "逾期违约金按日万分之五计算。"
    )
    r = await client.post(
        f"/api/v1/consultations/{consultation_id}/submit-text",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": contract},
    )
    assert r.status_code == 200, r.text
    print("✓ 提交合同文本")

    # 3. 生成报告
    r = await client.post(
        f"/api/v1/consultations/{consultation_id}/generate-report",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["status"] == "completed"
    assert len(report["conclusions"]) > 0
    assert "disclaimer" in report
    print(f"✓ 生成报告 ({len(report['conclusions'])} 条结论)")
    for c in report["conclusions"]:
        level_icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(c["level"], "·")
        print(f"   {level_icon} [{c['level']}] {c['title']}")

    # 4. 查询问诊详情
    r = await client.get(
        f"/api/v1/consultations/{consultation_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    detail = r.json()
    assert len(detail["facts"]) == 1
    assert len(detail["conclusions"]) > 0
    print(f"✓ 问诊详情: {len(detail['facts'])} facts + {len(detail['conclusions'])} conclusions")


async def test_knowledge_search(client: AsyncClient, token: str) -> None:
    """知识库搜索。"""
    r = await client.get(
        "/api/v1/knowledge/search",
        params={"q": "违约金"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    result = r.json()
    print(f"✓ 知识库搜索 '违约金': {result['total']} 条命中")
    for hit in result["laws"][:2]:
        print(f"   📜 {hit['law_name']} 第{hit['article_no']}条")


async def main() -> None:
    print("=" * 50)
    print("W1 后端端到端测试")
    print("=" * 50)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await test_health(client)
        token = await test_register_and_login(client)
        project_id = await test_create_project(client, token)
        await test_contract_review_e2e(client, token, project_id)
        await test_knowledge_search(client, token)
    print("=" * 50)
    print("✅ 全部通过")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
