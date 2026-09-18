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
    document.md               Markdown 正文（图片以**文件路径**引用）
    middle.json               MiddleJson（含 bbox 定位）
    images/                   提取的图片（如有）
    structured_content.json   MinerU 附赠的结构化内容
    model_output.json         MinerU 原始模型输出
    manifest.json             解析元信息（含 base64_inlined_images 供排查）

【关键约束：不要用 result.markdown()】
它会把图片以 base64 data URI 内联进正文。实测 3 页扫描件（5 张图）：
result.markdown() = 3.78 MB，而 result.save() 的 markdown.md = 1 KB（差 3600 倍）。
内联版会膨胀 DB 并让前端渲染卡死。本脚本统一用 save() 的产物。

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
        from mineru.parser.writer import FileBasedDataWriter

        result = parse(str(src), tier=args.tier)

        # ⚠️ 关键：必须用 result.save() 写出的 markdown.md，**不要**用 result.markdown()
        #
        # result.markdown() 会把图片以 **base64 data URI 内联**进正文。实测一份
        # 3 页扫描件（5 张图）：result.markdown() = 3,779,473 字节，
        # 而 save() 的 markdown.md = 1,036 字节（图片用文件路径引用）—— 差 3600 倍。
        # 内联版会同时造成两个问题：
        #   1) parsed_content 塞进 3.7MB base64 → 严重膨胀 DB（违反 §6.3 的既定原则）
        #   2) 前端渲染百万字符 → 页面被撑到极高、浏览器卡顿
        # 因此本项目统一采用「图片走文件路径、只把文本内联进 DB」的形态。
        result.save(FileBasedDataWriter(str(out_dir)))

        # 统一成本项目约定的文件名（save() 默认写 markdown.md / middle_json.json）
        md_path = out_dir / "markdown.md"
        middle_path = out_dir / "middle_json.json"
        if not md_path.exists():
            raise RuntimeError("MinerU 未产出 markdown.md（save() 行为可能已变更）")
        if not middle_path.exists():
            raise RuntimeError("MinerU 未产出 middle_json.json（save() 行为可能已变更）")

        md_path.rename(out_dir / "document.md")
        middle_path.rename(out_dir / "middle.json")

        md_text = (out_dir / "document.md").read_text(encoding="utf-8")
        middle_json_text = (out_dir / "middle.json").read_text(encoding="utf-8")

        # 防御：若 MinerU 将来又把 base64 内联回来，manifest 里留痕便于排查
        base64_inlined = md_text.count("data:image/")

        images_dir = out_dir / "images"
        images_written = (
            len([p for p in images_dir.iterdir() if p.is_file()]) if images_dir.is_dir() else 0
        )

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
                # 0 = 正常（图片走路径引用）；>0 = 正文里混入了 base64，需排查
                "base64_inlined_images": base64_inlined,
            },
        )
        if base64_inlined:
            print(
                f"[WARN] 正文含 {base64_inlined} 处 base64 内联图片，"
                f"markdown 达 {len(md_text)} 字符，可能膨胀 DB",
                file=sys.stderr,
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
