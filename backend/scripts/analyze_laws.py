"""深度分析 dengcao 数据集 - 找出所有工程相关条目（不限"法律"）。"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "knowledge-base" / "laws" / "dengcao-source" / "data"


def list_files_with_real_names() -> list[tuple[str, Path]]:
    """列出文件。解压时已修复 GBK 文件名。"""
    items: list[tuple[str, Path]] = []
    for p in DATA_DIR.glob("*.txt"):
        if not p.is_file():
            continue
        items.append((p.stem, p))
    items.sort(key=lambda x: x[0])
    return items


# 扩大的工程关键词
CONSTRUCTION_KEYWORDS = {
    # 直接相关
    "建设": "建设",
    "建筑": "建筑",
    "工程": "工程",
    "房地产": "房地产",
    "城乡规划": "城乡规划",
    "土地": "土地",
    # 招投标
    "招标": "招标",
    "投标": "投标",
    "政府采购": "政府采购",
    # 安全/质量
    "安全生产": "安全生产",
    "安全": "安全",
    "质量": "质量",
    "消防": "消防",
    # 环保（工程常涉及）
    "环境": "环境",
    "污染": "污染",
    "噪声": "噪声",
    # 合同/劳动/责任
    "劳动": "劳动",
    "合同": "合同",
    "工伤": "工伤",
    "社会保障": "社保",
    "保险": "保险",
    "担保": "担保",
    "物权": "物权",
    "侵权": "侵权",
    "公司": "公司",
    "合伙": "合伙",
    "破产": "破产",
    "反垄断": "反垄断",
}


def categorize(name: str) -> tuple[str, bool]:
    """分类 + 是否工程相关。"""
    matched_keywords = [k for k in CONSTRUCTION_KEYWORDS if k in name]
    is_construction = len(matched_keywords) > 0

    if name[-1] == "法" and "条例" not in name:
        cls = "法律"
    elif "条例" in name or "行政法规" in name:
        cls = "行政法规"
    elif "规章" in name or "规定" in name or "办法" in name:
        cls = "部门规章/规定"
    elif "解释" in name:
        cls = "司法解释"
    elif "修正案" in name or "宪法" in name:
        cls = "宪法/修正案"
    else:
        cls = "其他"

    return cls, is_construction


def main() -> None:
    files = list_files_with_real_names()
    print(f"=== 总计 {len(files)} 个文件 ===\n")

    by_class: dict[str, list[str]] = {}
    all_construction: list[tuple[str, list[str]]] = []  # (name, matched_keywords)

    for name, _ in files:
        cls, is_const = categorize(name)
        by_class.setdefault(cls, []).append(name)
        if is_const:
            matched = [k for k in CONSTRUCTION_KEYWORDS if k in name]
            all_construction.append((name, matched))

    print("📊 分类统计：")
    for cls in sorted(by_class):
        print(f"  {cls:20s} : {len(by_class[cls])} 部")

    print(f"\n🏗 工程相关（扩大关键词）: {len(all_construction)} 部")
    print("=" * 80)
    for name, matched in all_construction:
        print(f"  {name:50s} [{'/'.join(matched)}]")

    # 检查 MVP 核心法规是否存在
    print("\n\n🎯 MVP 核心法规覆盖检查：")
    core = {
        "民法典": "建筑合同 / 责任 / 侵权",
        "招标投标法": "招投标程序",
        "政府采购法": "政府采购",
        "安全生产法": "生产安全责任",
        "建设工程质量管理条例": "工程质量责任（行政法规）",
        "建设工程安全生产管理条例": "工程安全责任（行政法规）",
        "建设工程价款结算暂行办法": "结算依据（部门规章）",
        "建设工程施工合同(示范文本) GF-2017-0201": "合同范本",
        "建筑法": "建筑行业基础法",
    }
    for core_name, note in core.items():
        hit = any(core_name in name for name, _ in files)
        print(f"  {'✓' if hit else '✗'} {core_name:40s} - {note}")


if __name__ == "__main__":
    main()
