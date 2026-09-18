#!/usr/bin/env python3
"""批量转换 knowledge-base/standards/mohurd-source/ 下全部 38 本国标通用规范。

使用 MinerU Flash 档（已验证可在 Pascal/CPU 上跑通）：
  - 单本平均 135 秒（20 页）
  - 全部 38 本 ≈ 85 分钟（顺序）

输出结构：
  knowledge-base/standards/parsed/{pdf_stem}/
    ├── document.md              # Markdown
    ├── middle.json              # MiddleJson（bbox 定位）
    └── images/                  # 提取的图片（如有）

同时产出 batch_manifest.csv（每本耗时/页数/产物路径）。
"""
import csv
import sys
import time
from pathlib import Path

from mineru.parser import parse
from mineru.version import __version__


SRC = Path("/home/zhuoju36/workspace/lawyer/knowledge-base/standards/mohurd-source")
DST = Path("/home/zhuoju36/workspace/lawyer/knowledge-base/standards/parsed")
MANIFEST = Path("/home/zhuoju36/workspace/lawyer/experiments/mineru-test/output/batch_manifest.csv")


def process_one(pdf: Path) -> dict:
    """解析一本 PDF，返回 manifest 行。失败也记录（status 字段）。"""
    out_dir = DST / pdf.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "document.md"
    mj_path = out_dir / "middle.json"
    img_dir = out_dir / "images"

    t0 = time.perf_counter()
    try:
        result = parse(str(pdf), tier="flash")
        md_path.write_text(result.markdown(), encoding="utf-8")
        mj_path.write_text(result.to_json(), encoding="utf-8")
        # 把图片单独写到 images/ 目录
        if hasattr(result, "save"):
            from mineru.parser.writer import FileBasedDataWriter
            result.save(FileBasedDataWriter(str(out_dir)))
        elapsed = time.perf_counter() - t0
        return {
            "pdf": pdf.name,
            "size_mb": round(pdf.stat().st_size / 1024 / 1024, 2),
            "md_chars": len(result.markdown()),
            "mj_kb": round(len(result.to_json()) / 1024, 1),
            "elapsed_sec": round(elapsed, 1),
            "status": "ok",
            "out_dir": str(out_dir.relative_to(DST.parent.parent)),
        }
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return {
            "pdf": pdf.name,
            "size_mb": round(pdf.stat().st_size / 1024 / 1024, 2),
            "md_chars": 0,
            "mj_kb": 0,
            "elapsed_sec": round(elapsed, 1),
            "status": f"fail:{type(e).__name__}:{str(e)[:80]}",
            "out_dir": str(out_dir.relative_to(DST.parent.parent)),
        }


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(SRC.glob("*.pdf"))
    print(f"[i] MinerU {__version__}, tier=flash")
    print(f"[i] src: {SRC}")
    print(f"[i] dst: {DST}")
    print(f"[i] found {len(pdfs)} PDFs")
    print()

    rows = []
    t_start = time.perf_counter()
    for i, pdf in enumerate(pdfs, 1):
        print(f"[{i:2d}/{len(pdfs)}] {pdf.name} ({pdf.stat().st_size / 1024 / 1024:.1f} MB)")
        row = process_one(pdf)
        rows.append(row)
        print(f"           -> {row['status']}, {row['elapsed_sec']}s, md={row['md_chars']} chars")
        print()

    # 写 manifest
    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    total = time.perf_counter() - t_start
    ok = sum(1 for r in rows if r["status"] == "ok")
    fail = len(rows) - ok
    print(f"\n[summary]")
    print(f"  total: {len(rows)}, ok: {ok}, fail: {fail}")
    print(f"  elapsed: {total:.1f}s = {total/60:.1f} min")
    print(f"  manifest: {MANIFEST}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
