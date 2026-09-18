#!/usr/bin/env python3
"""MinerU Flash 档烟雾测试：验证 PDF→Markdown 基础链路，不依赖 VLM/GPU。

用途：先用最快路径跑通一本国标 PDF，确认 MinerU 安装完整、PDF 可解析、
输出格式正确；之后再升级到 Standard 档。
"""
from pathlib import Path
import sys
import time

from mineru.parser import parse
from mineru.version import __version__

# 38 本国标里选最小的一本做首次验证（2.7MB）
PDF = Path("/home/zhuoju36/workspace/lawyer/knowledge-base/standards/mohurd-source/GB55005-2021 木结构通用规范.pdf")
OUT = Path("/home/zhuoju36/workspace/lawyer/experiments/mineru-test/output/flash_smoke")
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    print(f"[i] MinerU {__version__}")
    print(f"[i] input: {PDF.name} ({PDF.stat().st_size / 1024 / 1024:.2f} MB)")
    print(f"[i] output: {OUT}")
    print(f"[i] tier: flash (no VLM, no GPU)")

    t0 = time.perf_counter()
    try:
        result = parse(str(PDF), tier="flash")
    except Exception as e:
        print(f"[FAIL] {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - t0

    md = result.markdown()
    md_path = OUT / "document.md"
    md_path.write_text(md, encoding="utf-8")

    middle = result.to_json()
    mj_path = OUT / "middle.json"
    mj_path.write_text(middle, encoding="utf-8")

    print(f"[OK] parse done in {elapsed:.1f}s")
    print(f"     markdown: {len(md)} chars, {md.count(chr(10))} lines  → {md_path.name}")
    print(f"     middle_json: {len(middle) / 1024:.1f} KB              → {mj_path.name}")
    print(f"     markdown head: {md[:200].splitlines()[0] if md else '(empty)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
