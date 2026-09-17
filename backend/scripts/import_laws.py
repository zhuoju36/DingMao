"""把 dengcao/Chinese-Laws 数据集导入到 laws / law_articles 表。

数据格式（每行）:
    《中华人民共和国反家庭暴力法》第一条规定，为了预防...

解析策略:
- 文件名（如"中华人民共和国反家庭暴力法.txt"）→ law.name + law.code
- 每行正则提取: 《法名》第X条[第Y款][第Z项][内容]

MVP 只做入库，不做关键词提取（V2 扩展）。
"""

import asyncio
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import AsyncSessionLocal
from app.models.knowledge import Law, LawArticle

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "knowledge-base" / "laws" / "dengcao-source" / "data"

# 行解析正则
# 《法名》第X条[第Y款][第Z项][，内容]
LINE_RE = re.compile(
    r"^《(?P<law_name>[^》]+)》"
    r"(?P<article_no>第[一二三四五六七八九十百零〇\d]+条)"
    r"(?P<paragraph>第[一二三四五六七八九十百零〇\d]+款)?"
    r"(?P<item>第[一二三四五六七八九十百零〇\d]+项)?"
    r"[，、]?"
    r"(?P<content>.*)$"
)


def parse_line(line: str) -> dict | None:
    """解析一行 → {law_name, article_no, paragraph, item, content}。"""
    line = line.strip()
    if not line:
        return None
    m = LINE_RE.match(line)
    if not m:
        return None
    return {
        "law_name": m.group("law_name").strip(),
        "article_no": m.group("article_no").strip(),
        "paragraph": (m.group("paragraph") or "").strip() or None,
        "item": (m.group("item") or "").strip() or None,
        "content": m.group("content").strip(),
    }


def infer_law_code(law_name: str) -> str:
    """推断法律编号（如'中华人民共和国公司法' → '公司法'）。"""
    prefixes = ["中华人民共和国", "全国人民代表大会常务委员会关于"]
    code = law_name
    for p in prefixes:
        if code.startswith(p):
            code = code[len(p):]
    for suffix in ["的决定", "的决议", "的解释", "的批复"]:
        if suffix in code:
            code = code.split(suffix)[0]
    return code.strip()


def categorize_law(law_name: str) -> str:
    """简单分类。"""
    if "建筑" in law_name or "建设" in law_name:
        return "construction"
    if "招标" in law_name or "采购" in law_name:
        return "bidding"
    if "安全" in law_name or "消防" in law_name:
        return "safety"
    if "环境" in law_name or "污染" in law_name:
        return "environmental"
    if "土地" in law_name or "房地产" in law_name or "城乡规划" in law_name:
        return "construction"
    if "劳动" in law_name or "社会保障" in law_name or "合同" in law_name:
        return "civil"
    if "公司" in law_name or "合伙" in law_name or "破产" in law_name:
        return "commercial"
    if "行政" in law_name or "处罚" in law_name:
        return "administrative"
    return "civil"


async def upsert_law(db: AsyncSession, name: str, code: str, category: str) -> int:
    """upsert 一部法律，返回 id。"""
    stmt = (
        pg_insert(Law)
        .values(code=code, name=name, category=category, status="active")
        .on_conflict_do_nothing(index_elements=["code"])
        .returning(Law.id)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row:
        return row

    result = await db.execute(select(Law).where(Law.code == code))
    existing = result.scalar_one()
    return existing.id


async def upsert_article(
    db: AsyncSession,
    law_id: int,
    article_no: str,
    content: str,
    paragraph: str | None,
    item: str | None,
) -> bool:
    """upsert 一条法条。返回是否新增。"""
    para_num = 1
    if paragraph:
        digits = paragraph.replace("第", "").replace("款", "")
        if digits.isdigit():
            para_num = int(digits)

    stmt = (
        pg_insert(LawArticle)
        .values(
            law_id=law_id,
            article_no=article_no,
            content=content,
            paragraph=para_num,
            item=item,
            keywords=[],
        )
        .on_conflict_do_nothing(index_elements=["law_id", "article_no"])
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def import_one_file(db: AsyncSession, file_path: Path) -> tuple[int, int, int]:
    """导入一个 .txt 文件。返回 (法条总数, 新增, 跳过/失败)。"""
    law_name = file_path.stem
    code = infer_law_code(law_name)
    category = categorize_law(law_name)

    law_id = await upsert_law(db, law_name, code, category)

    total = added = skipped = 0
    seen_articles: set[str] = set()
    with file_path.open(encoding="utf-8") as f:
        for line in f:
            parsed = parse_line(line)
            if not parsed:
                continue
            if parsed["article_no"] in seen_articles:
                continue
            seen_articles.add(parsed["article_no"])
            total += 1
            was_added = await upsert_article(
                db,
                law_id,
                parsed["article_no"],
                parsed["content"],
                parsed["paragraph"],
                parsed["item"],
            )
            if was_added:
                added += 1
            else:
                skipped += 1
    return total, added, skipped


async def main() -> None:
    if not DATA_DIR.exists():
        raise FileNotFoundError(
            f"未找到 {DATA_DIR}，请先运行 scripts.download_laws.py"
        )
    files = sorted(DATA_DIR.glob("*.txt"))
    print(f"→ 导入目录: {DATA_DIR.relative_to(REPO_ROOT)}/")
    print(f"→ 共 {len(files)} 个文件\n")

    grand_total = grand_added = grand_skipped = 0

    async with AsyncSessionLocal() as db:
        for i, f in enumerate(files, 1):
            try:
                total, added, skipped = await import_one_file(db, f)
                grand_total += total
                grand_added += added
                grand_skipped += skipped
                if i % 30 == 0:
                    await db.commit()
                    print(
                        f"  [{i}/{len(files)}] 累计: "
                        f"{grand_added} 新增 / {grand_total} 解析"
                    )
            except Exception as e:  # noqa: BLE001
                print(f"  ✗ {f.name}: {e}")
        await db.commit()

    print("\n=== 完成 ===")
    print(f"  法律文件数: {len(files)}")
    print(f"  解析行数: {grand_total}")
    print(f"  新增入库: {grand_added}")
    print(f"  跳过重复: {grand_skipped}")


if __name__ == "__main__":
    asyncio.run(main())
