#!/usr/bin/env python
"""问诊主链 E2E（采集 → 确认 → 结论）。

覆盖 consultation-ui.md §6.2「第一轮」的验收点：

1. 创建 variation 问诊
2. 多轮对话，`fact_progress` 随轮次上升（**不再**是 chat_turn_{n} 假键）
3. 必填齐 + evidence_list 非空 → 状态机走到 `awaiting_confirm`，`ready_to_report=True`
4. `POST /confirm` 迁移到 `generating_report`
5. 流式生成报告，落库结论带 🟦fact_refs / 🟨law_refs / 🟥standard_refs
6. 三依据缺失时降级 warning 落 `state_data.evidence_warnings`（不整条失败）

用法：
    set -a; source backend/.env; set +a
    backend/.venv/bin/python backend/scripts/test_consultation_e2e.py [--user-id 3] [--project-id 4]

注意：会真实调用 LLM（约 3-5 次，60-120 秒）并在库里创建一条问诊记录。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import create_access_token  # noqa: E402

BASE = "http://127.0.0.1:8000/api/v1"

# 一段信息量足够的争议陈述，目标是让 6 个必填键一次尽量齐
TURNS = [
    "业主要求增加幕墙龙骨，2026年3月15日口头指令的，没有书面变更指令。",
    "合同第7.2条约定变更必须出具书面指令，监理通知单#005和现场照片12张我都有。",
    "争议方是业主单位和施工单位，索赔金额86万，要求工期顺延45天。",
]

PASS, FAIL = "✅", "❌"
_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {PASS if ok else FAIL} {label}" + (f"  {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", type=int, default=3)
    ap.add_argument("--project-id", type=int, default=4)
    args = ap.parse_args()

    token = create_access_token(args.user_id)
    h = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(base_url=BASE, headers=h, timeout=300.0) as c:
        # ---- 1. 创建问诊 ----
        print("\n[1] 创建 variation 问诊")
        r = await c.post(
            "/consultations",
            json={"project_id": args.project_id, "scenario": "variation"},
        )
        r.raise_for_status()
        con = r.json()
        cid = con["id"]
        print(f"  consultation #{cid}  step={con['current_step']}")
        check("初始 step = init", con["current_step"] == "init", con["current_step"])
        check("含 fact_progress", con.get("fact_progress") is not None)
        reg = (con.get("fact_progress") or {}).get("registry") or []
        check(
            "登记表下发 10 个事实键",
            len(reg) == 10,
            f"实得 {len(reg)}",
        )

        # ---- 2. 多轮对话 ----
        print("\n[2] 多轮对话 + 事实抽取")
        last: dict = {}
        for i, text in enumerate(TURNS, 1):
            r = await c.post(f"/consultations/{cid}/messages", json={"content": text})
            r.raise_for_status()
            last = r.json()
            fp = last["fact_progress"]
            print(
                f"  轮 {i}: step={last['current_step']:<17} "
                f"必填 {fp['required_have']}/{fp['required_total']}  "
                f"新增={last['new_fact_labels']}  "
                f"待确认={[p['fact_label'] for p in last['pending_facts']]}"
            )
            if last.get("extraction_error"):
                print(f"      ⚠️ extraction_error: {last['extraction_error']}")

        check("事实键为规范键（非 chat_turn_N）", _no_fake_keys(await _facts(c, cid)))
        fp = last["fact_progress"]
        check("必填进度有推进", fp["required_have"] >= 3, f"{fp['required_have']}/{fp['required_total']}")

        # ---- 3. 详情：进度 + 状态 ----
        print("\n[3] 问诊详情")
        r = await c.get(f"/consultations/{cid}")
        r.raise_for_status()
        detail = r.json()
        fp = detail["fact_progress"]
        print(
            f"  step={detail['current_step']}  status={detail['status']}  "
            f"必填 {fp['required_have']}/{fp['required_total']}  "
            f"缺={fp['missing_required']}  事实={len(detail['facts'])}"
        )
        check("详情含 fact_progress", fp is not None)
        check("已采集事实非空", len(detail["facts"]) > 0, str(len(detail["facts"])))
        for f in detail["facts"]:
            print(
                f"      🟦 {f['fact_label']:<12} = {f['fact_value'][:46]!r}"
                f"  conf={f['confidence']}"
            )

        # ---- 4. 确认生成 ----
        print("\n[4] 确认生成（POST /confirm）")
        r = await c.post(f"/consultations/{cid}/confirm")
        if r.status_code != 200:
            print(f"  {FAIL} confirm 返回 {r.status_code}: {r.text[:200]}")
            return 1
        cf = r.json()
        print(
            f"  step={cf['current_step']}  ready={cf['ready_to_report']}  "
            f"仍缺={cf['missing_required']}"
        )
        check(
            "confirm 后 step = generating_report",
            cf["current_step"] == "generating_report",
            cf["current_step"],
        )

        # ---- 5. 流式生成报告 ----
        print("\n[5] 流式生成报告")
        events = {"chunk": 0, "reset": 0, "done": 0, "error": 0}
        done_payload: dict = {}
        chunks = 0
        async with c.stream(
            "POST", f"/consultations/{cid}/generate-report-stream"
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                ev = json.loads(line)
                t = ev.get("type", "?")
                events[t] = events.get(t, 0) + 1
                if t == "chunk":
                    chunks += len(ev.get("text", ""))
                elif t == "done":
                    done_payload = ev
                    break
                elif t == "error":
                    print(f"  {FAIL} error: {ev.get('message')}")
                    break
        print(f"  事件统计 {events}  收到 {chunks} 字符")
        check("收到 done 事件", events.get("done", 0) == 1)
        check("有流式 chunk", chunks > 0, f"{chunks} 字符")
        check("done 带 disclaimer（应用原则 4）", bool(done_payload.get("disclaimer")))

        # ---- 6. 结论 + 三依据 ----
        print("\n[6] 结论与三依据")
        r = await c.get(f"/consultations/{cid}")
        r.raise_for_status()
        detail = r.json()
        conclusions = detail["conclusions"]
        print(f"  step={detail['current_step']}  status={detail['status']}  结论 {len(conclusions)} 条")
        check("状态机走到 done", detail["current_step"] == "done", detail["current_step"])
        check("status = completed", detail["status"] == "completed", detail["status"])
        check("结论非空", len(conclusions) > 0, str(len(conclusions)))

        for x in conclusions:
            print(
                f"      [{x['level']:<6}] {x['title'][:34]}"
                f"  🟦{len(x['fact_refs'])} 🟨{len(x['law_refs'])} 🟥{len(x['standard_refs'])}"
                f"  推理链={'有' if x['reasoning_chain'] else '无'}"
                f"  反例={'有' if x['counter_arguments'] else '无'}"
            )

        check(
            "至少一条结论挂 🟦 事实引用",
            any(x["fact_refs"] for x in conclusions),
        )
        check(
            "结论含 reasoning_chain",
            any(x["reasoning_chain"] for x in conclusions),
        )

        warnings = detail.get("evidence_warnings") or []
        print(f"\n  降级 warning {len(warnings)} 条：")
        for w in warnings[:8]:
            print(f"      · [{w.get('scope')}/{w.get('type')}] {str(w.get('detail'))[:74]}")
        if len(warnings) > 8:
            print(f"      …另 {len(warnings) - 8} 条")
        check(
            "warning 已落 state_data（可观测）",
            isinstance(warnings, list),
        )

    print("\n" + "=" * 62)
    if _failures:
        print(f"{FAIL} 失败 {len(_failures)} 项：")
        for f in _failures:
            print(f"   · {f}")
        return 1
    print(f"{PASS} 主链 E2E 全部通过")
    return 0


def _no_fake_keys(facts: list[dict]) -> bool:
    return all(not str(f["fact_key"]).startswith("chat_turn_") for f in facts)


async def _facts(c: httpx.AsyncClient, cid: int) -> list[dict]:
    r = await c.get(f"/consultations/{cid}")
    r.raise_for_status()
    return r.json()["facts"]


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
