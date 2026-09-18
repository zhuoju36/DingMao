#!/usr/bin/env python3
"""批量解析全部国标通用规范（同进程，避免 subprocess 加载 ONNX 开销）。

用法：
  nohup python scripts/batch_run.py > /tmp/batch_standards.log 2>&1 &
  # 查看进度
  tail -f /tmp/batch_standards.log

设计要点：
  - 直接 import mineru.parser.parse（保留 ONNX 模型缓存）
  - 跳过已转换成功的 PDF（resume）
  - 失败也写 manifest（status=fail:...）
  - 每本打印耗时，结束时输出总耗时 + manifest 路径
"""
import csv
import sys
import time
from pathlib import Path

from mineru.parser import parse


SRC = Path("/home/zhuoju36/workspace/lawyer/knowledge-base/standards/mohurd-source")
DST = Path("/home/zhuoju36/workspace/lawyer/knowledge-base/standards/parsed")
MANIFEST = Path("/home/zhuoju36/workspace/lawyer/experiments/mineru-test/output/batch_manifest.csv")


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(SRC.glob("*.pdf"))
    pending = [p for p in pdfs if not (DST / p.stem / "document.md").exists()]
    skipped = len(pdfs) - len(pending)
    print(f"[driver] total={len(pdfs)}, pending={len(pending)}, skipped={skipped}", flush=True)
    print(f"[driver] dst={DST}", flush=True)
    print(flush=True)

    rows = []
    t_start = time.perf_counter()
    for i, pdf in enumerate(pending, 1):
        out_dir = DST / pdf.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / "document.md"
        mj_path = out_dir / "middle.json"

        t0 = time.perf_counter()
        try:
            result = parse(str(pdf), tier="flash")
            md_path.write_text(result.markdown(), encoding="utf-8")
            mj_path.write_text(result.to_json(), encoding="utf-8")
            dt = time.perf_counter() - t0
            md_chars = len(result.markdown())
            mj_kb = round(mj_path.stat().st_size / 1024, 1)
            status = "ok"
            err = ""
        except Exception as e:
            dt = time.perf_counter() - t0
            md_chars = 0
            mj_kb = 0
            status = "fail"
            err = f"{type(e).__name__}: {str(e)[:120]}"
            print(f"        err: {err}", flush=True)

        rows.append({
            "idx": i + skipped,
            "pdf": pdf.name,
            "size_mb": round(pdf.stat().st_size / 1024 / 1024, 2),
            "md_chars": md_chars,
            "mj_kb": mj_kb,
            "elapsed_sec": round(dt, 1),
            "status": status,
            "error": err,
        })

        # 单本输出
        eta_min = (len(pending) - i) * dt / 60 if i > 0 else 0
        print(
            f"[{i}/{len(pending)}] {pdf.name}  {dt:6.1f}s  md={md_chars:6d}  mj={mj_kb:6.1f}KB  {status}  "
            f"ETA={eta_min:.0f}min",
            flush=True,
        )

        # 每 5 本写一次 manifest（防止中断丢失进度）
        if i % 5 == 0 or i == len(pending):
            with MANIFEST.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

    total = time.perf_counter() - t_start
    ok = sum(1 for r in rows if r["status"] == "ok")
    print(flush=True)
    print(f"[summary] processed={len(rows)}, ok={ok}, fail={len(rows)-ok}", flush=True)
    print(f"[summary] total elapsed: {total/60:.1f} min", flush=True)
    print(f"[summary] avg per PDF: {total/len(rows) if rows else 0:.1f}s", flush=True)
    print(f"[manifest] {MANIFEST}", flush=True)
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
