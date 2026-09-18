#!/usr/bin/env python3
"""MinerU Standard 档测试：在 GTX 1080 (Pascal sm_61) 上跑通。

前置条件：
  - torch+cu128 wheel 已装（torch>=2.7）
  - mineru-llama-cpp 已装（CUDA 后端）
  - VLM GGUF 模型已下载到 $MINERU_HOME/models/...
  - $MINERU_HOME/config.yaml 配置 standard + llama-cpp + torch

输出：
  - Markdown
  - MiddleJson (含 bbox 定位)
  - images/ 目录（含原图块）
"""
import os
import sys
import time
from pathlib import Path

# 强制 VLM 引擎选 llama.cpp（在 Pascal 上唯一支持）
os.environ.setdefault("MINERU_MODEL_VLM_ENGINE", "llama-cpp")

from mineru.parser import parse
from mineru.version import __version__


PDF = Path("/home/zhuoju36/workspace/lawyer/knowledge-base/standards/mohurd-source/GB55005-2021 木结构通用规范.pdf")
OUT = Path("/home/zhuoju36/workspace/lawyer/experiments/mineru-test/output/standard_smoke")
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    print(f"[i] MinerU {__version__}, tier=standard, vlm=llama-cpp")
    print(f"[i] input: {PDF.name} ({PDF.stat().st_size / 1024 / 1024:.2f} MB)")
    print(f"[i] output: {OUT}")
    print(f"[i] GPU before:")
    os.system("nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader")

    t0 = time.perf_counter()
    try:
        result = parse(str(PDF), tier="standard")
    except Exception as e:
        print(f"[FAIL] {type(e).__name__}: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
        return 1
    elapsed = time.perf_counter() - t0

    # 三种产物
    md_path = OUT / "document.md"
    md_path.write_text(result.markdown(), encoding="utf-8")
    mj_path = OUT / "middle.json"
    mj_path.write_text(result.to_json(), encoding="utf-8")

    print(f"[OK] parse done in {elapsed:.1f}s")
    print(f"     markdown: {len(result.markdown())} chars → {md_path.name}")
    print(f"     middle_json: {len(result.to_json()) / 1024:.1f} KB → {mj_path.name}")
    print(f"[i] GPU after:")
    os.system("nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader")
    return 0


if __name__ == "__main__":
    sys.exit(main())
