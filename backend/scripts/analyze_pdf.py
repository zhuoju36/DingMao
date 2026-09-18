"""抽样分析 2 本规范 PDF 的结构。

输出：
- 总页数
- 是否有文本层（OCR vs 真文本）
- 字体情况（用于识别黑体字）
- 抽样内容（前几页 + 强制性条文标记）
"""

import sys
from pathlib import Path

import pymupdf  # PyMuPDF

REPO_ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = REPO_ROOT / "knowledge-base" / "standards" / "mohurd-source"


def analyze_one(pdf_path: Path) -> None:
    print(f"\n{'=' * 70}")
    print(f"📄 {pdf_path.name}")
    print("=" * 70)

    doc = pymupdf.open(pdf_path)
    total_pages = doc.page_count
    print(f"总页数: {total_pages}")

    # 跳过封面/版权页（前 2 页通常是元数据）
    print("\n--- 前 4 页文本 ---")
    for i in range(min(4, total_pages)):
        page = doc[i]
        text = page.get_text()[:300].strip()
        print(f"\n[Page {i + 1}] {text if text else '(空)'}")

    # 字体统计（全本）
    print("\n--- 字体统计（全部页面）---")
    font_counter: dict[str, int] = {}
    for page in doc:
        blocks = page.get_text("dict").get("blocks", [])
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line.get("spans", []):
                    font_name = span.get("font", "")
                    if font_name:
                        font_counter[font_name] += len(span.get("text", ""))

    sorted_fonts = sorted(font_counter.items(), key=lambda x: -x[1])[:10]
    for font, count in sorted_fonts:
        print(f"  {font:40s} {count:>6} 字符")

    # "强制性条文"标记统计
    print("\n--- 强制性条文标记 ---")
    mandatory_count = 0
    for page in doc:
        text = page.get_text()
        if "强制性条文" in text or "黑体字" in text or "必须严格执行" in text:
            mandatory_count += 1
    print(f"  含'强制性条文'或'黑体字'标记的页数: {mandatory_count}")

    # 抽样典型条文格式
    print("\n--- 抽样典型条文 ---")
    found = 0
    samples = []
    for page in doc:
        text = page.get_text()
        for line in text.split("\n"):
            line = line.strip()
            # 匹配"X.X.X 为强制性条文"标记
            if "强制性条文" in line and len(line) > 5:
                samples.append(line[:150])
                found += 1
                if found >= 5:
                    break
        if found >= 5:
            break
    for s in samples:
        print(f"  - {s}")
    if not samples:
        print("  (未找到'强制性条文'标记)")

    # 找一段普通条文样式
    print("\n--- 抽样普通条文样式 ---")
    for page in doc:
        text = page.get_text()
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("第") and ("条" in line) and len(line) > 5 and len(line) < 100:
                print(f"  - {line[:100]}")
                break
        else:
            continue
        break

    doc.close()


def main() -> None:
    # 抽 2 本有代表性的
    samples = [
        "GB55008-2021 混凝土结构通用规范.pdf",  # 关键工程，强条多
        "GB55037-2022 建筑防火通用规范.pdf",     # 最大文件
    ]
    for name in samples:
        path = PDF_DIR / name
        if path.exists():
            analyze_one(path)
        else:
            print(f"未找到: {name}")


if __name__ == "__main__":
    sys.exit(main() or 0)
