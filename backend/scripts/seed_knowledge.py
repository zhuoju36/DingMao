"""种子数据：插入 1 部法规 + 1 条强条用于演示搜索。"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import AsyncSessionLocal
from app.models.knowledge import Law, LawArticle, Standard, StandardClause


async def seed(db: AsyncSession) -> None:
    # 法条：民法典
    existing = await db.execute(select(Law).where(Law.code == "民法典"))
    if existing.scalar_one_or_none() is None:
        law = Law(
            code="民法典",
            name="中华人民共和国民法典",
            category="civil",
            issuing_org="全国人大",
            effective_date="2021-01-01",
            status="active",
        )
        db.add(law)
        await db.flush()

        # 第 577 条 - 违约责任
        article1 = LawArticle(
            law_id=law.id,
            article_no="第五百七十七条",
            content="当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。",
            keywords=["违约", "合同义务", "违约责任"],
        )
        db.add(article1)

        # 第 585 条 - 违约金调整
        article2 = LawArticle(
            law_id=law.id,
            article_no="第五百八十五条",
            content="约定的违约金过分高于造成的损失的，当事人可以请求人民法院或者仲裁机构予以适当减少。",
            keywords=["违约金", "调减", "过分高于"],
        )
        db.add(article2)

        print("✓ 插入民法典 + 2 条")

    # 强条：GB 55008 混凝土结构通用规范
    existing = await db.execute(select(Standard).where(Standard.code == "GB 55008-2022"))
    if existing.scalar_one_or_none() is None:
        std = Standard(
            code="GB 55008-2022",
            name="混凝土结构通用规范",
            category="concrete",
            version="2022",
            effective_date="2022-04-12",
            status="active",
        )
        db.add(std)
        await db.flush()

        clause = StandardClause(
            standard_id=std.id,
            clause_no="4.1.1",
            content=(
                "混凝土结构工程应按设计文件、施工方案和技术标准进行施工。"
                "隐蔽工程在隐蔽前应进行验收，验收合格后方可进入下道工序。"
            ),
            is_mandatory=True,
            behavior_tags=["隐蔽工程", "验收"],
            keywords=["隐蔽工程", "验收", "下道工序"],
        )
        db.add(clause)

        print("✓ 插入 GB 55008-2022 + 1 强条")

    await db.commit()


async def main() -> None:
    async with AsyncSessionLocal() as db:
        await seed(db)
    print("✓ 种子数据完成")


if __name__ == "__main__":
    asyncio.run(main())
