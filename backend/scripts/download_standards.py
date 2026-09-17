"""从住建部官网下载已发布的强制性工程建设规范 PDF。

已找到 26 本的公告 URL，自动从公告页提取 PDF 附件链接并下载。
剩余 11 本（GB 55002、55009、55023-55029、55034、55035）后续补充。

用法:
    uv run python -m scripts.download_standards
"""

import asyncio
import re
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET_DIR = REPO_ROOT / "knowledge-base" / "standards" / "mohurd-source"

# 已找到的 26 本公告：(pid, art_year, gb_code, title)
# art_year 是 URL 中的 /art/{year}/ 部分
# gb_code 用于文件命名
# title 用于显示
CATALOG: list[tuple[int, int, str, str]] = [
    # 2021 年早期发布（pid 761xxx）
    (761174, 2021, "GB 55002-2021", "建筑与市政工程抗震通用规范"),
    (761185, 2021, "GB 55003-2021", "建筑与市政地基基础通用规范"),
    (761186, 2021, "GB 55004-2021", "组合结构通用规范"),
    (761187, 2021, "GB 55005-2021", "木结构通用规范"),
    (761188, 2021, "GB 55007-2021", "砌体结构通用规范"),
    (761189, 2021, "GB 55010-2021", "供热工程项目规范"),
    (761190, 2021, "GB 55011-2021", "城市道路交通工程项目规范"),
    (761191, 2021, "GB 55006-2021", "钢结构通用规范"),
    (761192, 2021, "GB 55001-2021", "工程结构通用规范"),
    (761193, 2021, "GB 55014-2021", "园林绿化工程项目规范"),
    (761194, 2021, "GB 55012-2021", "生活垃圾处理处置工程项目规范"),
    (761195, 2021, "GB 55013-2021", "市容环卫工程项目规范"),
    # 2021 年中期发布（pid 762xxx）
    (762453, 2021, "GB 55021-2021", "既有建筑鉴定与加固通用规范"),
    (762454, 2021, "GB 55008-2021", "混凝土结构通用规范"),
    (762455, 2021, "GB 55017-2021", "工程勘察通用规范"),
    (762456, 2021, "GB 55018-2021", "工程测量通用规范"),
    (762457, 2021, "GB 55022-2021", "既有建筑维护与改造通用规范"),
    (762458, 2021, "GB 55020-2021", "建筑给水排水与节水通用规范"),
    (762459, 2021, "GB 55016-2021", "建筑环境通用规范"),
    (762460, 2021, "GB 55015-2021", "建筑节能与可再生能源利用通用规范"),
    (762461, 2021, "GB 55019-2021", "建筑与市政工程无障碍通用规范"),
    # 2022 年发布（pid 765xxx / 767xxx / 768xxx）
    (765631, 2022, "GB 55023-2022", "施工脚手架通用规范"),
    (765632, 2022, "GB 55024-2022", "建筑电气与智能化通用规范"),
    (767703, 2022, "GB 55031-2022", "民用建筑通用规范"),
    (767704, 2022, "GB 55036-2022", "消防设施通用规范"),
    (767714, 2022, "GB 55032-2022", "建筑与市政工程施工质量控制通用规范"),
    (767715, 2022, "GB 55033-2022", "城市轨道交通工程项目规范"),
    (768499, 2022, "GB 55030-2022", "建筑与市政工程防水通用规范"),
    (768953, 2022, "GB 55034-2022", "建筑与市政施工现场安全卫生与职业健康通用规范"),
    # 2023 年发布（pid 770xxx / 772xxx）
    (770016, 2023, "GB 55037-2022", "建筑防火通用规范"),
    (772515, 2023, "GB 55035-2023", "城乡历史文化保护利用项目规范"),
]


def build_announce_url(pid: int, art_year: int) -> str:
    return (
        f"https://www.mohurd.gov.cn/gongkai/zc/wjk/art/{art_year}/"
        f"art_17339_{pid}.html"
    )


# PDF 链接提取：找含"通用规范"或"项目规范"的下载链接（不是"废止条文"）
PDF_LINK_RE = re.compile(
    r'href="(/api-gateway/jpaas-web-server/front/document/download\?'
    r'[^"]+)"[^>]*>\s*([^<]+通用规范|[^<]+项目规范)\s*</a>',
    re.MULTILINE,
)


def extract_pdf_url(html: str) -> tuple[str, str] | None:
    """从公告 HTML 提取（PDF 链接, 文件名）。返回主要规范的链接（非废止条文）。"""
    match = PDF_LINK_RE.search(html)
    if not match:
        return None
    pdf_path, link_text = match.group(1), match.group(2).strip()
    pdf_url = "https://www.mohurd.gov.cn" + pdf_path
    # fileName 参数作为保存文件名
    name_match = re.search(r"fileName=([^&]+)", pdf_path)
    file_name = name_match.group(1) if name_match else f"{link_text}.pdf"
    return pdf_url, file_name


async def download_one(
    client: httpx.AsyncClient,
    pid: int,
    art_year: int,
    gb_code: str,
    title: str,
) -> tuple[str, str, str]:
    """下载一本规范。返回 (status, gb_code, message)。"""
    announce_url = build_announce_url(pid, art_year)
    # 命名规则：GB 55008-2021 混凝土结构通用规范.pdf
    target_name = f"{gb_code.replace(' ', '')} {title}.pdf"
    target_path = TARGET_DIR / target_name

    # 幂等：已存在跳过
    if target_path.exists() and target_path.stat().st_size > 1024:
        return "skip", gb_code, f"已存在 ({target_path.stat().st_size // 1024} KB)"

    try:
        # 1. 拉公告页 HTML
        r = await client.get(announce_url, timeout=20.0)
        r.raise_for_status()
        html = r.text
    except Exception as e:  # noqa: BLE001
        return "fail", gb_code, f"公告页失败: {e}"

    # 2. 提取 PDF 链接
    extracted = extract_pdf_url(html)
    if not extracted:
        return "fail", gb_code, "未找到 PDF 链接（页面结构可能变了）"
    pdf_url, _file_name = extracted

    # 3. 下载 PDF
    try:
        r = await client.get(pdf_url, timeout=60.0, follow_redirects=True)
        r.raise_for_status()
        content = r.content
    except Exception as e:  # noqa: BLE001
        return "fail", gb_code, f"PDF 下载失败: {e}"

    # 4. 验证是 PDF（魔数 %PDF-）
    if not content.startswith(b"%PDF"):
        return "fail", gb_code, "下载内容不是 PDF"

    # 5. 保存
    target_path.write_bytes(content)
    return "ok", gb_code, f"下载完成 ({len(content) // 1024} KB)"


async def main() -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    print(f"→ 下载到 {TARGET_DIR.relative_to(REPO_ROOT)}/")
    print(f"→ 共 {len(CATALOG)} 本规范\n")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }

    ok = skip = fail = 0
    failures: list[tuple[str, str]] = []

    async with httpx.AsyncClient(headers=headers, http2=False) as client:
        for pid, art_year, gb_code, title in CATALOG:
            status, _, msg = await download_one(
                client, pid, art_year, gb_code, title
            )
            if status == "ok":
                ok += 1
                print(f"  ✓ {gb_code} {title:30s} - {msg}")
            elif status == "skip":
                skip += 1
                print(f"  ↻ {gb_code} {title:30s} - {msg}")
            else:
                fail += 1
                failures.append((gb_code, msg))
                print(f"  ✗ {gb_code} {title:30s} - {msg}")

    print("\n=== 完成 ===")
    print(f"  成功: {ok} 本")
    print(f"  跳过: {skip} 本（已存在）")
    print(f"  失败: {fail} 本")
    if failures:
        print("\n失败清单：")
        for gb, msg in failures:
            print(f"  - {gb}: {msg}")


if __name__ == "__main__":
    asyncio.run(main())
