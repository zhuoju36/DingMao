"""从国家法律法规数据库补齐 laws.version / effective_date / issuing_org。

## 为什么需要这个脚本

`import_laws.py` 的数据源（ModelScope `dengcao/Chinese-Laws`）是**纯条文 .txt**，
不含公布/施行日期，因此 `laws.version` 与 `effective_date` 全为空。这两个字段是
应用原则 3（"法条引用必须有版本号 + 生效日期——引用过期条文等同误导"）的载体，
缺了它们 `evidence_linker.link_evidence` 会把所有法条引用丢弃 → 🟨 依据恒为空。

## 为什么不能从条文正文推导（实测教训）

每部法的末条都写着「本法自YYYY年M月D日起施行」，166/177 可解析。**但那是原始施行日期**，
而被修订过的法律其正文已是修订后的版本。实测建筑法：

- 数据集第四十八条 =「建筑施工企业应当依法为职工参加工伤保险缴纳工伤保险费」
  → 这是 **2011 修正后**的文本
- 但末条仍写「本法自 **1998年3月1日** 起施行」

直接采用会生成「《建筑法》第X条（1998-03-01 施行）」，而用户读的是 2019 修正版——
正是原则 3 要防的误导。且该数据集无法判断哪些法被修订过（仅 3/177 提及"修正"）。

## 数据源

国家法律法规数据库（官方权威一手来源）https://flk.npc.gov.cn
接口：`POST /law-search/search/list`，返回 `gbrq`(公布日期) / `sxrq`(施行日期) /
`sxx`(时效性: 3=现行有效) / `zdjgName`(制定机关)。

字段映射：
- `version`        ← `gbrq` 的年份（与 w3-w8-triple-evidence.md 示例 `"version":"2020"` 一致）
- `effective_date` ← `sxrq`
- `issuing_org`    ← `zdjgName`（顺带补齐，该字段此前 177 部中仅 1 部有值）

## 安全规则（宁可缺，不写错）

1. **标题必须精确匹配**——接口的 `searchType=1` 并非严格精确（实测查「民法典」返回 30 条，
   含地方变通规定），因此必须在本地逐条比对 title
2. **排除尚未生效的版本**——不能只取"最新公布"。实测商标法有
   `gbrq=2026-06-26 / sxrq=2027-01-01`（尚未生效），取它会给我们存的 2019 版文本
   盖上 2026 版本号。判据：`sxrq` 必须 ≤ 今天
3. **取现行版本** = 排除尚未生效后，`gbrq` 最新的一条
4. 日期必须能解析为 YYYY-MM-DD，否则该字段留 NULL（不猜）
5. 匹配不到、或匹配到多条且无法判定 → **不写库**，记入报告待人工处理
6. 限速 + 重试 + 跟随 WAF 重定向，避免给对方站点压力

### 关于 `sxx`（时效性）——不要用它做过滤

公开的第三方接口文档称"sxx=3 为有效"，**这是错的**。实测：

| 法律 | gbrq | sxx |
|---|---|---|
| 建筑法（现行） | 2019-04-23 | 3 |
| 建筑法（已被取代） | 2011-04-22 | 2 |
| 环境保护法（现行） | 2014-04-24 | **1** |
| 大气污染防治法（现行） | 2018-10-26 | **1** |
| 大气污染防治法（旧版） | 2015-08-29 | **1** |
| 商标法（尚未生效） | 2026-06-26 | 4 |

按 `sxx=3` 过滤会漏掉 11 部现行有效的环境类法律（实测）。
因此本脚本**不做 sxx 过滤**，改用"排除未来生效 + 取最新公布"，
并把 sxx 原样记入报告供人工复核。

用法：
    set -a; source backend/.env; set +a
    backend/.venv/bin/python backend/scripts/sync_law_metadata.py            # 干跑
    backend/.venv/bin/python backend/scripts/sync_law_metadata.py --apply    # 写库
    backend/.venv/bin/python backend/scripts/sync_law_metadata.py --limit 10 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.base import AsyncSessionLocal  # noqa: E402
from app.models.knowledge import Law  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "knowledge-base" / "LAW_METADATA_REPORT.md"

FLK_SEARCH = "https://flk.npc.gov.cn/law-search/search/list"
FLK_DETAIL = "https://flk.npc.gov.cn/law-search/search/flfgDetails"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DingMao/0.1 (law metadata sync)"

# 时效性 sxx 的取值含义未经权威确认（见模块文档），因此不做过滤，
# 只原样记入报告。判断"现行版本"改用「排除未来生效 + 取最新公布」。
_TODAY = datetime.now(UTC).astimezone().date()

# 礼貌限速：每次请求间隔（秒）。177 部约 3-4 分钟。
_REQUEST_INTERVAL = 0.8
_MAX_RETRIES = 3

_RE_TAG = re.compile(r"<[^>]+>")
_RE_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


@dataclass
class LawMeta:
    """从权威库取到的一条元数据。"""

    title: str
    bbbs: str
    gbrq: str | None       # 公布日期
    sxrq: str | None       # 施行日期
    sxx: int | None
    flxz: str              # 法律 / 行政法规 / …
    zdjg: str              # 制定机关

    @property
    def version(self) -> str | None:
        """取公布年份作版本号（如 2020）。"""
        if self.gbrq and _RE_DATE.match(self.gbrq):
            return self.gbrq[:4]
        return None

    @property
    def effective_date(self) -> str | None:
        """施行日期（非法格式一律返回 None，不猜）。"""
        if self.sxrq and _RE_DATE.match(self.sxrq):
            return self.sxrq
        return None


@dataclass
class SyncOutcome:
    """单部法律的处理结果。"""

    law_id: int
    code: str
    name: str
    status: str                      # ok / ambiguous / not_found / fetch_failed
    meta: LawMeta | None = None
    note: str = ""
    changed: list[str] = field(default_factory=list)


def _clean(title: str) -> str:
    """去掉接口返回的高亮标签。"""
    return _RE_TAG.sub("", title).strip()


async def fetch_meta(client: httpx.AsyncClient, name: str) -> list[LawMeta]:
    """按标题检索权威库，返回全部**标题精确匹配**的记录（各版本都返回）。"""
    payload = {
        "searchRange": 1,          # 按标题
        "sxrq": [],
        "gbrq": [],
        "sxx": [],                 # 不做时效性过滤（原因见模块文档）
        "searchType": 1,
        "xgzlSearch": False,
        "searchContent": name,
        "orderByParam": {"order": "-1", "sort": ""},
        "flfgCodeId": [],
        "zdjgCodeId": [],
        "gbrqYear": [],
        "pageNum": 1,
        "pageSize": 20,
    }

    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            r = await client.post(
                FLK_SEARCH,
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Referer": "https://flk.npc.gov.cn/search",
                },
            )
            r.raise_for_status()
            rows = r.json().get("rows") or []
            out: list[LawMeta] = []
            for row in rows:
                title = _clean(str(row.get("title", "")))
                if title != name:  # 本地精确比对：接口的 searchType=1 并非严格精确
                    continue
                out.append(
                    LawMeta(
                        title=title,
                        bbbs=str(row.get("bbbs", "")),
                        gbrq=row.get("gbrq"),
                        sxrq=row.get("sxrq"),
                        sxx=row.get("sxx"),
                        flxz=str(row.get("flxz", "")),
                        zdjg=str(row.get("zdjgName", "")),
                    )
                )
            return out
        except Exception as e:  # noqa: BLE001
            last_err = e
            await asyncio.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"检索失败（重试 {_MAX_RETRIES} 次）: {last_err}")


async def process_one(
    client: httpx.AsyncClient, law: Law, *, apply: bool, db: AsyncSession
) -> SyncOutcome:
    """处理一部法律：检索 → 校验 → （可选）写库。"""
    outcome = SyncOutcome(law_id=law.id, code=law.code, name=law.name, status="ok")

    try:
        matches = await fetch_meta(client, law.name)
    except Exception as e:  # noqa: BLE001
        outcome.status = "fetch_failed"
        outcome.note = str(e)
        return outcome

    if not matches:
        outcome.status = "not_found"
        outcome.note = "权威库无标题精确匹配的现行有效记录"
        return outcome

    # 排除"尚未生效"的版本：实测商标法有 gbrq=2026-06-26 / sxrq=2027-01-01，
    # 若取它会给我们存的 2019 版文本盖上 2026 版本号。
    def _not_yet_in_force(m: LawMeta) -> bool:
        d = m.effective_date
        if not d:
            return False  # 无施行日期 → 不据此排除
        try:
            return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=UTC).date() > _TODAY
        except ValueError:
            return False

    in_force = [m for m in matches if not _not_yet_in_force(m)]
    if not in_force:
        outcome.status = "not_found"
        outcome.note = f"匹配到 {len(matches)} 条但均尚未生效"
        return outcome

    # 现行版本 = 排除尚未生效后，公布日期最新的一条
    meta = sorted(in_force, key=lambda m: (m.gbrq or "", m.sxrq or ""))[-1]
    outcome.meta = meta

    new_version = meta.version
    new_effective = meta.effective_date
    new_org = meta.zdjg or None

    if new_version is None and new_effective is None:
        outcome.status = "not_found"
        outcome.note = "权威库记录缺 gbrq 与 sxrq，按规则不写库"
        return outcome

    if apply:
        if new_version and law.version != new_version:
            law.version = new_version
            outcome.changed.append(f"version={new_version}")
        if new_effective and law.effective_date != new_effective:
            law.effective_date = new_effective
            outcome.changed.append(f"effective_date={new_effective}")
        if new_org and law.issuing_org != new_org:
            law.issuing_org = new_org
            outcome.changed.append("issuing_org")
    else:
        if new_version and law.version != new_version:
            outcome.changed.append(f"version={new_version}")
        if new_effective and law.effective_date != new_effective:
            outcome.changed.append(f"effective_date={new_effective}")
        if new_org and law.issuing_org != new_org:
            outcome.changed.append("issuing_org")

    if not outcome.changed:
        outcome.note = "已是最新，无需变更"
    return outcome


def write_report(outcomes: list[SyncOutcome], *, applied: bool) -> None:
    """写可追溯报告（应用原则 7：知识库必须可重建；AGENTS.md：输出必须可追溯）。"""
    now = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    by_status: dict[str, list[SyncOutcome]] = {}
    for o in outcomes:
        by_status.setdefault(o.status, []).append(o)

    lines = [
        "# 法律元数据补齐报告",
        "",
        f"> 生成时间：{now}",
        f"> 模式：{'**已写库**' if applied else '干跑（未写库）'}",
        "> 数据源：国家法律法规数据库 <https://flk.npc.gov.cn>（官方权威一手来源）",
        "> 脚本：`backend/scripts/sync_law_metadata.py`",
        "",
        "字段映射：`version` ← `gbrq` 公布年份；`effective_date` ← `sxrq` 施行日期；",
        "`issuing_org` ← `zdjgName` 制定机关。",
        "现行版本判定：排除 `sxrq` 晚于今天的记录（尚未生效），再取 `gbrq` 最新的一条。",
        "**不做 `sxx` 过滤**——公开的第三方接口文档称\"sxx=3 为有效\"是错的，实测按它过滤会漏掉 11 部",
        "现行有效的环境类法律（如环境保护法、大气污染防治法均为 sxx=1）。`sxx` 原样列出供人工复核。",
        "",
        "## 汇总",
        "",
        "| 状态 | 数量 | 含义 |",
        "|---|---:|---|",
        f"| ok | {len(by_status.get('ok', []))} | 成功取到现行有效版本信息 |",
        f"| not_found | {len(by_status.get('not_found', []))} | 权威库无精确匹配，**未写库** |",
        f"| ambiguous | {len(by_status.get('ambiguous', []))} | 匹配歧义，**未写库** |",
        f"| fetch_failed | {len(by_status.get('fetch_failed', []))} | 请求失败，**未写库** |",
        "",
    ]

    for status, title in [
        ("ok", "成功"),
        ("ambiguous", "匹配歧义（需人工处理）"),
        ("not_found", "未匹配到（需人工处理）"),
        ("fetch_failed", "请求失败（可重跑）"),
    ]:
        items = by_status.get(status)
        if not items:
            continue
        lines += [f"## {title}（{len(items)}）", ""]
        if status == "ok":
            lines += [
                "| 法律 | code | version | effective_date | sxx | 制定机关 | 权威库 bbbs | 变更 |",
                "|---|---|---|---|---|---|---|---|",
            ]
            for o in items:
                m = o.meta
                assert m is not None
                lines.append(
                    f"| {o.name} | {o.code} | {m.version or '—'} | "
                    f"{m.effective_date or '—'} | {m.sxx if m.sxx is not None else '—'} | "
                    f"{m.zdjg or '—'} | `{m.bbbs}` | "
                    f"{', '.join(o.changed) or '无需变更'} |"
                )
        else:
            lines += ["| 法律 | code | 说明 |", "|---|---|---|"]
            for o in items:
                lines.append(f"| {o.name} | {o.code} | {o.note} |")
        lines.append("")

    lines += [
        "## 复现方式",
        "",
        "```bash",
        "set -a; source backend/.env; set +a",
        "backend/.venv/bin/python backend/scripts/sync_law_metadata.py --apply",
        "```",
        "",
        "脚本幂等：重复运行不会改变已正确的记录。",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写库（默认干跑）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 部（调试用）")
    args = ap.parse_args()

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Law).order_by(Law.id))
        laws = list(result.scalars().all())
        if args.limit:
            laws = laws[: args.limit]

        print(f"→ 待处理法律 {len(laws)} 部（模式：{'写库' if args.apply else '干跑'}）")
        print(f"→ 限速 {_REQUEST_INTERVAL}s/请求，预计 "
              f"{len(laws) * _REQUEST_INTERVAL / 60:.1f} 分钟\n")

        outcomes: list[SyncOutcome] = []
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": UA},
            follow_redirects=True,  # 站点 WAF 会返回 307 质询
        ) as client:
            for i, law in enumerate(laws, 1):
                outcome = await process_one(client, law, apply=args.apply, db=db)
                outcomes.append(outcome)

                mark = {"ok": "✓", "ambiguous": "?", "not_found": "✗"}.get(
                    outcome.status, "!"
                )
                if outcome.status == "ok":
                    m = outcome.meta
                    print(
                        f"  [{i}/{len(laws)}] {mark} {law.name[:26]:<28}"
                        f"v={m.version if m else '—':<6}"
                        f"eff={m.effective_date if m else '—'}"
                    )
                else:
                    print(f"  [{i}/{len(laws)}] {mark} {law.name[:26]:<28}{outcome.note}")

                # 每 30 条提交一次，避免长事务
                if args.apply and i % 30 == 0:
                    await db.commit()
                    print(f"      ── 已提交前 {i} 条")

                if i < len(laws):
                    await asyncio.sleep(_REQUEST_INTERVAL)

        if args.apply:
            await db.commit()

        report_outcomes = outcomes
        if not args.limit:  # 只有全量跑才写报告，避免样本覆盖完整报告
            write_report(report_outcomes, applied=args.apply)

    ok = sum(1 for o in outcomes if o.status == "ok")
    changed = sum(1 for o in outcomes if o.changed)
    print("\n=== 完成 ===")
    print(f"  成功取到元数据: {ok}/{len(outcomes)}")
    print(f"  发生变更:       {changed}")
    print(f"  歧义/未匹配:    "
          f"{sum(1 for o in outcomes if o.status == 'ambiguous')}/"
          f"{sum(1 for o in outcomes if o.status == 'not_found')}")
    if args.apply and not args.limit:
        print(f"  报告: {REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
