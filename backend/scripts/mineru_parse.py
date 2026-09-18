#!/usr/bin/env python3
"""独立 MinerU 解析脚本（P0-7-B）。

【为什么是独立脚本】
MinerU 依赖体积 7.3 GB（torch/onnxruntime + 模型），不能装进 backend venv
（737 MB）。因此后端通过 subprocess 调用一个「装了 MinerU 的解释器」执行本脚本，
路径由 settings.mineru_python 配置。

【为什么必须是真实 .py 文件而非 heredoc】
MinerU 内部用 multiprocessing spawn，子进程需要 __main__ 的文件路径；
通过 stdin/heredoc 执行会报 FileNotFoundError: '<stdin>'。

用法：
    <mineru_python> mineru_parse.py --input <pdf> --output <dir> [--tier flash]

输出（写入 output 目录）：
    document.md       Markdown 正文
    middle.json       MiddleJson（含 bbox 定位）
    images/           提取的图片（如有）
    manifest.json     解析元信息（status/elapsed/page_count/error）

退出码：
    0  成功
    1  解析失败（manifest.json 里带 error 详情，供后端读取并写 parse_error）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path


def _write_manifest(out_dir: Path, payload: dict) -> None:
    """写 manifest.json（后端读这个文件判断结果，不依赖 stdout 解析）。"""
    (out_dir / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _count_pages(middle_json_text: str) -> int:
    """从 MiddleJson 取页数（失败不致命，返回 0）。"""
    try:
        return len(json.loads(middle_json_text).get("pages", []))
    except Exception:  # noqa: BLE001
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="MinerU 单文件解析")
    parser.add_argument("--input", required=True, help="输入文件路径（PDF/图片）")
    parser.add_argument("--output", required=True, help="输出目录")
    parser.add_argument(
        "--tier",
        default="flash",
        choices=["flash", "basic", "standard", "advanced"],
        help="解析档位。MVP 固定 flash（CPU 可跑，详见 decisions-and-results.md）",
    )
    args = parser.parse_args()

    src = Path(args.input)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    base_manifest = {
        "input": str(src),
        "tier": args.tier,
        "input_size": src.stat().st_size if src.exists() else 0,
    }

    if not src.exists():
        _write_manifest(
            out_dir,
            {**base_manifest, "status": "failed", "error": f"输入文件不存在: {src}"},
        )
        print(f"[FAIL] 输入文件不存在: {src}", file=sys.stderr)
        return 1

    try:
        # 延迟 import：让 --help / 参数错误不必加载 7GB 依赖
        from mineru.parser import parse

        result = parse(str(src), tier=args.tier)

        md_text = result.markdown()
        middle_json_text = result.to_json()

        (out_dir / "document.md").write_text(md_text, encoding="utf-8")
        (out_dir / "middle.json").write_text(middle_json_text, encoding="utf-8")

        # 图片素材（有则写 images/，失败不致命）
        images_written = 0
        try:
            from mineru.parser.writer import FileBasedDataWriter

            result.save(FileBasedDataWriter(str(out_dir)))
            images_dir = out_dir / "images"
            if images_dir.is_dir():
                images_written = len(list(images_dir.iterdir()))
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] 图片素材保存失败（不影响正文）: {exc}", file=sys.stderr)

        elapsed = time.perf_counter() - started
        page_count = _count_pages(middle_json_text)

        _write_manifest(
            out_dir,
            {
                **base_manifest,
                "status": "success",
                "elapsed_sec": round(elapsed, 1),
                "markdown_chars": len(md_text),
                "middle_json_bytes": len(middle_json_text.encode("utf-8")),
                "page_count": page_count,
                "images": images_written,
            },
        )
        print(
            f"[OK] {src.name}: {elapsed:.1f}s, "
            f"pages={page_count}, md={len(md_text)} chars, images={images_written}"
        )
        return 0

    except Exception as exc:  # noqa: BLE001
        elapsed = time.perf_counter() - started
        err = f"{type(exc).__name__}: {exc}"
        _write_manifest(
            out_dir,
            {
                **base_manifest,
                "status": "failed",
                "elapsed_sec": round(elapsed, 1),
                "error": err,
                "traceback": traceback.format_exc()[-2000:],
            },
        )
        print(f"[FAIL] {src.name}: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
