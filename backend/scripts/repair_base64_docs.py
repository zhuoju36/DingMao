#!/usr/bin/env python3
"""修复已被 base64 污染的解析记录（一次性脚本）。

背景：mineru_parse.py 早期用 result.markdown() 写正文，会把图片以 base64 内联，
导致 parsed_content 达数百万字符。修复脚本改用 save() 产物后，需把历史记录重跑一遍。

用法：
    .venv/bin/python scripts/repair_base64_docs.py [--apply]

不带 --apply 时只报告受影响记录（dry-run）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.models.base import AsyncSessionLocal
from app.models.document import ProjectDocument
from app.services import ingest
from app.services.storage import get_storage_root

# parsed_content 超过此字符数即视为可疑（正常公文 markdown 远小于此值）
SUSPICIOUS_CHARS = 200_000


async def main(apply: bool) -> int:
    async with AsyncSessionLocal() as db:
        docs = (await db.execute(select(ProjectDocument))).scalars().all()

        suspects = []
        for d in docs:
            pc = d.parsed_content or {}
            md = pc.get("markdown") or ""
            if len(md) > SUSPICIOUS_CHARS:
                suspects.append((d, len(md)))

        if not suspects:
            print("✓ 没有可疑记录（无超长 parsed_content）")
            return 0

        print(f"发现 {len(suspects)} 条可疑记录：")
        for d, n in suspects:
            print(f"  doc={d.id} project={d.project_id} md={n:,} 字符  {d.title[:40]}")
        print()

        if not apply:
            print("（dry-run，未改动。加 --apply 执行重解析）")
            return 0

        for d, n in suspects:
            src = get_storage_root() / d.storage_path
            if not src.exists():
                print(f"  ✗ doc={d.id} 源文件缺失（{d.storage_path}），跳过")
                d.parse_status = "failed_parse"
                d.parse_error = "源文件已丢失，无法重解析以修复 base64 膨胀"
                continue

            print(f"  重解析 doc={d.id} …")
            res = await ingest.parse_document(
                project_id=d.project_id,
                document_id=d.id,
                file_path=src,
            )
            if res.status == "success":
                d.parse_status = "parsed"
                d.parse_error = None
                d.parsed_content = {
                    "markdown": res.markdown,
                    "page_count": res.page_count,
                    "markdown_chars": res.markdown_chars,
                    "middle_json_bytes": res.middle_json_bytes,
                    "images": res.images,
                    "elapsed_sec": res.elapsed_sec,
                    "tier": "flash",
                    "parsed_dir": str(res.output_dir.relative_to(get_storage_root())),
                }
                after = len(res.markdown or "")
                print(f"    ✓ {n:,} → {after:,} 字符（↓{n / max(after, 1):.0f}×）")
            else:
                d.parse_status = "failed_parse"
                d.parse_error = (res.error or "重解析失败")[:1000]
                print(f"    ✗ 失败: {res.error}")

        await db.commit()
        print("\n✓ 已写回数据库")
        return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际执行重解析（默认 dry-run）")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.apply)))
