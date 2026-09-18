#!/usr/bin/env python3
"""批量驱动：顺序调用 _run_one.py 处理全部 PDF，写 manifest。

被 nohup 后台调用，日志重定向到 /tmp/batch_standards.log。
"""
import csv
import subprocess
import sys
import time
from pathlib import Path

SCRIPT = Path("/home/zhuoju36/workspace/lawyer/experiments/mineru-test/scripts/_run_one.py")
SRC = Path("/home/zhuoju36/workspace/lawyer/knowledge-base/standards/mohurd-source")
DST = Path("/home/zhuoju36/workspace/lawyer/knowledge-base/standards/parsed")
MANIFEST = Path("/home/zhuoju36/workspace/lawyer/experiments/mineru-test/output/batch_manifest.csv")


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(SRC.glob("*.pdf"))
    # 跳过已经转换成功的（resume 支持）
    pending = [p for p in pdfs if not (DST / p.stem / "document.md").exists()]
    skipped = len(pdfs) - len(pending)
    print(f"[driver] total={len(pdfs)}, pending={len(pending)}, skipped={skipped}", flush=True)

    rows = []
    t_start = time.perf_counter()
    for i, pdf in enumerate(pending, 1):
        out_dir = DST / pdf.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), str(pdf), str(out_dir)],
            capture_output=True, text=True,
        )
        dt = time.perf_counter() - t0
        ok = proc.returncode == 0
        md_chars = 0
        md_path = out_dir / "document.md"
        if md_path.exists():
            md_chars = len(md_path.read_text(encoding="utf-8"))
        mj_kb = 0
        mj_path = out_dir / "middle.json"
        if mj_path.exists():
            mj_kb = round(mj_path.stat().st_size / 1024, 1)
        rows.append({
            "idx": i,
            "pdf": pdf.name,
            "size_mb": round(pdf.stat().st_size / 1024 / 1024, 2),
            "md_chars": md_chars,
            "mj_kb": mj_kb,
            "elapsed_sec": round(dt, 1),
            "status": "ok" if ok else f"fail:{proc.returncode}",
        })
        print(f"[{i}/{len(pending)}] {pdf.name}: {dt:.1f}s -> {rows[-1]['status']}, md={md_chars}", flush=True)
        if not ok and proc.stderr:
            print(f"        stderr: {proc.stderr[:200]}", flush=True)

    # 写 manifest（覆盖式）
    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    total = time.perf_counter() - t_start
    ok = sum(1 for r in rows if r["status"] == "ok")
    print(f"\n[summary] {len(rows)} PDFs, ok={ok}, fail={len(rows)-ok}, total={total/60:.1f} min", flush=True)
    print(f"[manifest] {MANIFEST}", flush=True)
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
