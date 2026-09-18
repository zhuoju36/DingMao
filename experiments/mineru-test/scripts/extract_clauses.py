#!/usr/bin/env python3
"""强条提取：从 MinerU MiddleJson + Markdown 抽取结构化的"标准 → 章节 → 条文"树。

适用 GB 55000 系列通用规范（全文强制性）—— 所有 X.Y.Z 条款都是强条。

输出：
  - clauses_overview.csv：所有规范的统计
  - clauses_full.json：每本规范的条款明细（含条号、级别、内容）

使用：
  python scripts/extract_clauses.py
"""
import csv
import json
import re
import sys
from pathlib import Path


SRC_PARSED = Path("/home/zhuoju36/workspace/lawyer/knowledge-base/standards/parsed")
DST_REPORT = Path("/home/zhuoju36/workspace/lawyer/experiments/mineru-test/output")

# 条文号：1, 1.1, 1.1.1
CLAUSE_PATTERN = re.compile(r"^([0-9]+(?:\.[0-9]+){0,2})\s+(.+)$")


def parse_md(md_text: str) -> list[dict]:
    """从 Markdown 提取正文条款（跳过目次段）。"""
    clauses = []
    in_toc = False
    for line in md_text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("## 目次") or s.startswith("## 目录"):
            in_toc = True
            continue
        if s.startswith("## ") and not (s.startswith("## 目次") or s.startswith("## 目录")):
            in_toc = False
        if in_toc:
            continue
        m = CLAUSE_PATTERN.match(s)
        if m:
            clauses.append({
                "clause_no": m.group(1),
                "level": m.group(1).count(".") + 1,  # 1=章, 2=节, 3=条
                "content": m.group(2).strip(),
                "is_mandatory": True,  # GB 55000 全文强制
            })
    return clauses


def _flatten_text(node) -> str:
    """递归从 MiddleJson content 节点提取纯文本。"""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        c = node.get("content")
        if c is not None:
            return _flatten_text(c) if not isinstance(c, str) else c
        return ""
    if isinstance(node, list):
        return "".join(_flatten_text(x) for x in node)
    return ""


def parse_middle_json(mj: dict) -> list[dict]:
    """从 MiddleJson 提取所有块（带 page_idx、bbox、type）。"""
    out = []
    for page in mj.get("pages", []):
        for block in page.get("blocks", []):
            out.append({
                "page_idx": page["page_idx"],
                "block_idx": block.get("index", 0),
                "type": block.get("type"),
                "level": block.get("level"),
                "bbox": block.get("bbox"),
                "text": _flatten_text(block.get("content", [])),
            })
    return out


def extract_one(pdf_dir: Path) -> dict:
    md = (pdf_dir / "document.md").read_text(encoding="utf-8")
    mj = json.loads((pdf_dir / "middle.json").read_text(encoding="utf-8"))
    clauses = parse_md(md)
    blocks = parse_middle_json(mj)
    return {
        "pdf_stem": pdf_dir.name,
        "num_pages": len(mj.get("pages", [])),
        "num_blocks": len(blocks),
        "num_md_chars": len(md),
        "num_clauses": len(clauses),
        "num_mandatory_clauses": sum(1 for c in clauses if c["is_mandatory"]),
        "clauses": clauses,
    }


def main() -> int:
    DST_REPORT.mkdir(parents=True, exist_ok=True)
    pdf_dirs = sorted([p for p in SRC_PARSED.iterdir() if (p / "document.md").exists()])
    print(f"[extract] found {len(pdf_dirs)} parsed standards")

    all_rows = []
    full_dump = []
    for d in pdf_dirs:
        info = extract_one(d)
        all_rows.append({
            "code": d.name.split(" ")[0],
            "name": d.name.split(" ", 1)[1] if " " in d.name else "",
            "pages": info["num_pages"],
            "blocks": info["num_blocks"],
            "md_chars": info["num_md_chars"],
            "clauses": info["num_clauses"],
            "mandatory_clauses": info["num_mandatory_clauses"],
        })
        full_dump.append(info)
        print(f"  {d.name[:60]:60s}  {info['num_pages']:3d}p  {info['num_clauses']:4d} clauses "
              f"({info['num_mandatory_clauses']} mandatory)")

    csv_path = DST_REPORT / "clauses_overview.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)

    dump_path = DST_REPORT / "clauses_full.json"
    with dump_path.open("w", encoding="utf-8") as f:
        json.dump(full_dump, f, ensure_ascii=False, indent=2)

    total_clauses = sum(r["clauses"] for r in all_rows)
    total_mandatory = sum(r["mandatory_clauses"] for r in all_rows)
    print(f"\n[summary] {len(pdf_dirs)} standards, {total_clauses} clauses total "
          f"({total_mandatory} mandatory)")
    print(f"[csv]     {csv_path}")
    print(f"[dump]    {dump_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
