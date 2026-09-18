#!/usr/bin/env python3
"""单本 PDF 解析（用于 .py 文件模式，避开 heredoc + multiprocessing spawn 问题）。"""
import sys
import time
from pathlib import Path

from mineru.parser import parse


def main() -> int:
    pdf_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    try:
        result = parse(str(pdf_path), tier="flash")
        (out_dir / "document.md").write_text(result.markdown(), encoding="utf-8")
        (out_dir / "middle.json").write_text(result.to_json(), encoding="utf-8")
        dt = time.perf_counter() - t0
        print(f"[OK] {pdf_path.name}: {dt:.1f}s, md={len(result.markdown())} chars")
        return 0
    except Exception as e:
        dt = time.perf_counter() - t0
        print(f"[FAIL] {pdf_path.name}: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
