"""Build the four storyboard frames for docs/media/proof.gif from the running app.

1. Drives a running OSRA (BASE_URL, default http://127.0.0.1:8000) with Playwright for
   Python: signs in, imports the bundled demo set through Import CSV, and screenshots the
   validation result, the model comparison, one journey and data readiness.
2. Reads every number and phrase used in the captions from those pages and writes them to
   run.json next to this file.
3. Renders each frame from frame.html and screenshots it to out/frames/.

It raises if the app stops showing what a caption says, so the GIF can't silently drift
from the product. See README.md in this folder.
"""

from __future__ import annotations

import csv
import html
import io
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
SHOTS = OUT / "shots"
FRAMES = OUT / "frames"
BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USER = os.environ.get("OSRA_USER", "")
PASSWORD = os.environ.get("OSRA_PASSWORD", "")
DEMO = ROOT / "sample_data" / "demo"

CAMPAIGN_A = "google / cpc / q1-search"
CAMPAIGN_B = "linkedin / paid-social / abm-launch"
JOURNEY_OPPORTUNITY = "Northwind platform"
CURRENCY = "USD"


class DemoDrift(AssertionError):
    pass


def check(cond: object, msg: str) -> None:
    if not cond:
        raise DemoDrift(f"readme-demo: {msg}")


def text(page: Page, selector: str) -> str:
    return " ".join(page.locator(selector).first.inner_text().split())


def shot(page: Page, name: str, locator=None, clip=None) -> dict:
    path = SHOTS / f"{name}.png"
    if locator is not None:
        locator.screenshot(path=str(path))
        box = locator.bounding_box()
        width, height = box["width"], box["height"]
    else:
        page.screenshot(path=str(path), clip=clip, full_page=True)
        width, height = clip["width"], clip["height"]
    return {"file": path.as_uri(), "width": width, "height": height}


def table_rows(page: Page, table) -> tuple[list[str], list[list[str]]]:
    """Header labels and body cells (row header first) of an HTML table, as shown."""
    # textContent, not innerText: the header row is uppercased by CSS.
    headers = table.locator("thead th").evaluate_all(
        "ths => ths.map(t => t.textContent.replace(/\\s+/g, ' ').trim())"
    )
    rows = table.locator("tbody tr").evaluate_all(
        "rows => rows.map(r => [...r.children].map(c => c.innerText.replace(/\\s+/g, ' ').trim()))"
    )
    return headers, rows


def main() -> None:
    check(USER and PASSWORD, "set OSRA_USER and OSRA_PASSWORD to a user of the running app")
    SHOTS.mkdir(parents=True, exist_ok=True)
    FRAMES.mkdir(parents=True, exist_ok=True)
    run: dict = {"capturedAt": datetime.now(UTC).isoformat(timespec="seconds"), "baseUrl": BASE}

    with sync_playwright() as p:
        browser = p.chromium.launch()

        def new_page(width: int) -> Page:
            ctx = browser.new_context(
                viewport={"width": width, "height": 900}, device_scale_factor=2
            )
            return ctx.new_page()

        page = new_page(840)
        page.goto(f"{BASE}/accounts/login/")
        page.fill("input[name=username]", USER)
        page.fill("input[name=password]", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE}/")
        storage = page.context.storage_state()

        # Frame 1: import the bundled demo set through the Import CSV page.
        page.goto(f"{BASE}/import/")
        demo_button = page.get_by_role("button", name="Import the demo data set")
        demo_note = " ".join(
            page.locator("form p.context", has_text="demo data set").inner_text().split()
        )
        check("10 invalid rows on purpose" in demo_note, f"import page note changed: {demo_note}")
        demo_button.click()
        page.wait_for_url(re.compile(r"/validation/"))
        page.evaluate("document.fonts.ready")
        verdict = text(page, ".verdict")
        m = re.search(r"(\d+) rows refused\. The other (\d+) rows were loaded", verdict)
        check(m, f"validation verdict changed: {verdict}")
        refused, loaded = int(m[1]), int(m[2])
        _, by_file = table_rows(page, page.locator("table").first)
        received = sum(int(r[1]) for r in by_file)
        files = [r[0] for r in by_file]
        check(len(files) == 4, f"expected four files, got {files}")
        # Validation result: from the h1 down to the end of the rows-by-file table.
        h1 = page.locator("main h1").bounding_box()
        table_box = page.locator("table").first.bounding_box()
        main_box = page.locator("main").bounding_box()
        pad = 16
        validation_shot = shot(
            page,
            "validation",
            clip={
                "x": main_box["x"] + pad,
                "y": h1["y"] - 12,
                "width": main_box["width"] - 2 * pad,
                "height": table_box["y"] + table_box["height"] - h1["y"] + 24,
            },
        )
        run["import"] = {
            "page": "/import/",
            "button": "Import the demo data set",
            "note": demo_note,
            "verdict": verdict,
            "files": files,
            "rowsReceived": received,
            "loaded": loaded,
            "refused": refused,
        }

        # Frame 2: the model comparison, USD block.
        page = browser.new_context(
            viewport={"width": 1100, "height": 900}, device_scale_factor=2, storage_state=storage
        ).new_page()
        page.goto(f"{BASE}/?metric=pipeline")
        page.evaluate("document.fonts.ready")
        usd_h2 = page.locator("h2", has_text=f"Credit by campaign · {CURRENCY}")
        check(usd_h2.count() == 1, "no USD block on the model comparison")
        usd_table = usd_h2.locator("xpath=following-sibling::div[contains(@class,'table-wrap')][1]")
        usd_context = " ".join(usd_h2.locator("xpath=following-sibling::p[1]").inner_text().split())
        headers, rows = table_rows(page, usd_table)
        models = headers[1:-1]
        check(
            models[:2] == ["First-touch", "Last-touch"],
            f"model columns changed: {headers}",
        )
        by_campaign = {r[0]: dict(zip(headers[1:], r[1:], strict=True)) for r in rows}
        a, b = by_campaign.get(CAMPAIGN_A), by_campaign.get(CAMPAIGN_B)
        check(a and b, f"campaign rows missing: {list(by_campaign)}")
        total_cells = usd_table.locator("tfoot td").all_inner_texts()
        totals = [t.strip() for t in total_cells[: len(models)]]
        check(len(set(totals)) == 1, f"model totals differ: {totals}")
        usd_total = totals[0]
        check(a["First-touch"] != "0" and a["Last-touch"] == "0", f"{CAMPAIGN_A}: {a}")
        check(b["First-touch"] == "0" and b["Last-touch"] != "0", f"{CAMPAIGN_B}: {b}")
        notice = text(page, "main .notice")
        check("not causal impact" in notice, f"comparison notice changed: {notice}")
        window = " ".join(
            page.locator("#results p.context", has_text="Window:").inner_text().split()
        )
        usd_box = usd_h2.bounding_box()
        tbl_box = usd_table.bounding_box()
        compare_shot = shot(
            page,
            "compare-usd",
            clip={
                "x": tbl_box["x"] - 12,
                "y": usd_box["y"] - 10,
                "width": tbl_box["width"] + 24,
                "height": tbl_box["y"] + tbl_box["height"] - usd_box["y"] + 16,
            },
        )
        run["comparison"] = {
            "page": "/?metric=pipeline",
            "models": models,
            "currency": CURRENCY,
            "context": usd_context,
            "window": window,
            "total": usd_total,
            "campaigns": {CAMPAIGN_A: a, CAMPAIGN_B: b},
            "notice": notice,
        }

        # Frame 3: one opportunity's journey.
        link = page.get_by_role("link", name=JOURNEY_OPPORTUNITY).first
        href = link.get_attribute("href")
        # The journey table scrolls sideways below ~1250 px, so this one is captured wider.
        page = browser.new_context(
            viewport={"width": 1280, "height": 900}, device_scale_factor=2, storage_state=storage
        ).new_page()
        page.goto(BASE + href)
        page.evaluate("document.fonts.ready")
        journey_verdict = text(page, ".verdict")
        jt = page.locator("table.journey-table")
        jheaders, jrows = table_rows(page, jt)
        touches = [dict(zip(jheaders, r, strict=True)) for r in jrows]
        jtotal = [t.strip() for t in jt.locator("tfoot td").all_inner_texts()]
        contact_h2 = page.locator("h2", has_text="Touches of")
        contact = " ".join(contact_h2.inner_text().split())
        check(len(touches) >= 3, f"journey has {len(touches)} touches")
        first, second = touches[0], touches[1]
        check(
            CAMPAIGN_A.replace(" ", "") in first["Source / medium / campaign"].replace(" ", ""),
            f"first touch is not {CAMPAIGN_A}: {first}",
        )
        check(
            CAMPAIGN_B.replace(" ", "") in second["Source / medium / campaign"].replace(" ", ""),
            f"second touch is not {CAMPAIGN_B}: {second}",
        )
        after = [t for t in touches if "AFTER CONVERSION" in t["Eligibility"].upper()]
        check(after, "no touch after the conversion in the journey")
        ch = contact_h2.bounding_box()
        jbox = jt.bounding_box()
        journey_shot = shot(
            page,
            "journey",
            clip={
                "x": jbox["x"] - 12,
                "y": ch["y"] - 10,
                "width": jbox["width"] + 24,
                "height": jbox["y"] + jbox["height"] - ch["y"] + 14,
            },
        )
        run["journey"] = {
            "page": href,
            "opportunity": JOURNEY_OPPORTUNITY,
            "verdict": journey_verdict,
            "contact": contact,
            "touches": touches,
            "totals": jtotal,
        }

        # Frame 4: data readiness and the opportunities.csv row behind its first fix.
        page = browser.new_context(
            viewport={"width": 1000, "height": 900}, device_scale_factor=2, storage_state=storage
        ).new_page()
        page.goto(f"{BASE}/readiness/")
        page.evaluate("document.fonts.ready")
        r_verdict = text(page, ".verdict")
        first_fix = page.locator("li.finding").first
        fix_title = " ".join(first_fix.locator(".finding-head strong").inner_text().split())
        fix_count = " ".join(first_fix.locator(".finding-head .mono").inner_text().split())
        dds = [" ".join(t.split()) for t in first_fix.locator("dd").all_inner_texts()]
        dts = [t.strip().upper() for t in first_fix.locator("dt").all_inner_texts()]
        fix = dict(zip(dts, dds, strict=True))
        records = re.findall(r"opp-\d+", fix.get("RECORDS", ""))
        check(records, f"first readiness check lists no opportunity: {fix}")
        no_touch = text(page, "#results p.context.small")
        v_box = page.locator(".verdict").bounding_box()
        f_box = first_fix.bounding_box()
        readiness_shot = shot(
            page,
            "readiness",
            clip={
                "x": f_box["x"] - 12,
                "y": v_box["y"] - 10,
                "width": f_box["width"] + 24,
                "height": f_box["y"] + f_box["height"] - v_box["y"] + 8,
            },
        )
        run["readiness"] = {
            "page": "/readiness/",
            "verdict": r_verdict,
            "firstCheck": {"title": fix_title, "count": fix_count, **fix},
            "records": records,
            "noTouch": no_touch,
        }
        browser.close()

    # Input files.
    tp_lines = (DEMO / "touchpoints.csv").read_text().splitlines()
    opp_text = (DEMO / "opportunities.csv").read_text()
    opp_lines = opp_text.splitlines()
    opp_rows = list(csv.DictReader(io.StringIO(opp_text)))
    record = records[0]
    bad = next(r for r in opp_rows if r["opportunity_id"] == record)
    check(bad["contact_id"] == "", f"{record} has a contact in opportunities.csv: {bad}")
    unattributed = re.search(r"([\d.]+) is Unattributed", run["comparison"]["context"])
    check(
        unattributed and unattributed[1] == bad["amount"],
        f"{record} amount {bad['amount']} is not the Unattributed amount: {usd_context}",
    )
    run["input"] = {
        "touchpoints": "sample_data/demo/touchpoints.csv",
        "opportunities": "sample_data/demo/opportunities.csv",
        "unattributedOpportunity": {
            k: bad[k] for k in ("opportunity_id", "name", "amount", "currency")
        },
    }
    (HERE / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n")

    # ── Frames ────────────────────────────────────────────────────────────────
    esc = html.escape

    def csv_card(label, path, lines, marks, foot, picks=()):
        out = []
        for n, line in lines:
            if n is None:
                out.append('<span class="l gap"><span class="n"></span>…</span>')
                continue
            cls = "hdr" if n == 1 else marks.get(n, "")
            body = esc(line)
            for pick in picks:
                body = body.replace(esc(pick), f"<em>{esc(pick)}</em>")
            out.append(f'<span class="l {cls}"><span class="n">{n}</span>{body}</span>')
        return (
            f'<div class="card"><div class="card-head"><b>{esc(label)}</b> · {esc(path)}</div>'
            f'<pre class="csv">{"".join(out)}</pre><div class="card-foot">{foot}</div></div>'
        )

    def product(url, s, width=None):
        style = f' style="width:{width}px"' if width else ""
        return (
            f'<div class="card"{style}><div class="card-head">{esc(url)}</div>'
            f'<img class="shot" src="{s["file"]}" alt=""></div>'
        )

    def top(n, headline):
        return (
            f'<div class="top"><span class="step">{n} / 4</span>'
            f'<span class="headline">{headline}</span></div>'
        )

    def bnum(x):
        return f"<b>{esc(str(x))}</b>"

    def note(inner, style=""):
        return f'<p class="note"{style}>{inner}</p>'

    def versus(name, row):
        cells = "".join(
            f'<div><div class="label">{esc(m)}</div>'
            f'<div class="num{" zero" if row[m] == "0" else ""}">{esc(row[m])}</div></div>'
            for m in ("First-touch", "Last-touch")
        )
        head = f'<div class="campaign">{esc(name)}</div>'
        return f'<div class="card">{head}<div class="nums">{cells}</div></div>'

    # touchpoints.csv excerpt: the q1-search and abm-launch touches of the two credited
    # contacts (Northwind platform's con-nw-ana and Umbra pilot's con-um-eve), rows between
    # them elided.
    a_campaign = CAMPAIGN_A.split(" / ")[-1]
    b_campaign = CAMPAIGN_B.split(" / ")[-1]
    tp_ids = {t["Touch"].split()[0] for t in touches[:2]}

    def wanted(n, line):
        cells = line.split(",")
        if n == 1 or cells[0] in tp_ids:
            return True
        return cells[1] == "con-um-eve" and cells[5] in (a_campaign, b_campaign)

    keep = [n for n, line in enumerate(tp_lines, start=1) if wanted(n, line)]
    shown, skipped, prev = [], [], None
    for n in keep:
        if prev is not None and n != prev + 1:
            shown.append((None, ""))
            skipped.append(f"{prev + 1}-{n - 1}" if n - 1 > prev + 1 else f"{prev + 1}")
        shown.append((n, tp_lines[n - 1]))
        prev = n
    marks = {n: ("a" if f",{a_campaign}," in tp_lines[n - 1] else "b") for n in keep if n > 1}
    check(set(marks.values()) == {"a", "b"}, f"touchpoints excerpt lost a campaign: {marks}")

    imp = run["import"]
    comp = run["comparison"]
    ca, cb = comp["campaigns"][CAMPAIGN_A], comp["campaigns"][CAMPAIGN_B]
    j = run["journey"]
    t1, t2 = j["touches"][0], j["touches"][1]
    t3 = next(t for t in j["touches"] if "AFTER" in t["Eligibility"].upper())
    rd = run["readiness"]
    fixes = re.search(r"(\d+ checks?) needs? a fix", rd["verdict"])
    check(fixes, f"readiness verdict changed: {rd['verdict']}")
    fix_checks = fixes[1]
    opp_idx = next(i for i, line in enumerate(opp_lines) if line.startswith(record + ","))

    def touch_id(t):
        return esc(t["Touch"].split()[0])

    legend = (
        f'<span class="key a"></span>{esc(a_campaign)} &nbsp; '
        f'<span class="key b"></span>{esc(b_campaign)}'
        f" · rows {', '.join(skipped)} left out here"
    )
    frame1 = (
        top(
            1,
            f"The bundled synthetic sample: {len(imp['files'])} CSVs, {imp['rowsReceived']} rows, "
            f"{imp['refused']} of them invalid on purpose.",
        )
        + csv_card("SAMPLE", run["input"]["touchpoints"], shown, marks, legend)
        + '<div class="row"><div class="grow">'
        + note(
            f"<strong>Import CSV → {esc(imp['button'])}</strong> (or "
            "<code>load_sample_data</code>) validates every row against the data contract first."
        )
        + note(
            f"{bnum(imp['loaded'])} rows loaded, {bnum(imp['refused'])} refused, each with a "
            "reason code and a fix. Synthetic <code>*.example</code> data.",
            ' style="margin-top:10px"',
        )
        + f"</div>{product('/validation/', validation_shot, width=560)}</div>"
    )
    frame2 = (
        top(
            2,
            f"Same touches, two named models: <code>{esc(a_campaign)}</code> gets "
            f"{esc(ca['First-touch'])} of {esc(comp['total'])} {CURRENCY} under first-touch, "
            f"{esc(ca['Last-touch'])} under last-touch.",
        )
        + product("/ · Model comparison · Pipeline", compare_shot)
        + f'<div class="vs">{versus(CAMPAIGN_A, ca)}{versus(CAMPAIGN_B, cb)}</div>'
        + note(
            f"Every model column totals {bnum(comp['total'])} {CURRENCY}. The gap is the rules' "
            "difference: association under a named model, not causal impact."
        )
    )
    frame3 = (
        top(
            3,
            f"Check every step of the math: {esc(JOURNEY_OPPORTUNITY)}, touch by touch, "
            f"each column adding up to {esc(j['totals'][0])} {CURRENCY}.",
        )
        + product(f"{j['page'].split('?')[0]} · Journey", journey_shot)
        + note(
            f"<strong>{touch_id(t1)}</strong> ({esc(a_campaign)}) gets "
            f"{bnum(t1['First-touch'])} under first-touch and {bnum(t1['Last-touch'])} under "
            f"last-touch; <strong>{touch_id(t2)}</strong> ({esc(b_campaign)}) the reverse. "
            f"<strong>{touch_id(t3)}</strong> came after the conversion, so no model credits it."
        )
    )
    frame4 = (
        top(
            4,
            f"Before you trust it: data readiness finds {esc(fix_checks)} to fix, "
            "each with how to verify it.",
        )
        + csv_card(
            "INPUT",
            run["input"]["opportunities"],
            [
                (1, opp_lines[0]),
                (None, ""),
                (opp_idx, opp_lines[opp_idx - 1]),
                (opp_idx + 1, opp_lines[opp_idx]),
            ],
            {opp_idx + 1: "bad"},
            f'Row {opp_idx + 1}: <span style="font-family:var(--mono)">{esc(record)}</span> has an '
            "empty contact_id.",
            picks=(f"{record},{bad['account_id']},,",),
        )
        + product("/readiness/ · first check to fix", readiness_shot)
        + note(
            f"No contact, no touches: {esc(bad['name'])}'s {bnum(bad['amount'])} "
            f"{esc(bad['currency'])} shows as Unattributed under every model instead of being "
            "hidden."
        )
    )
    frames = [frame1, frame2, frame3, frame4]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        fp = browser.new_page(viewport={"width": 880, "height": 640}, device_scale_factor=1)
        fp.goto((HERE / "frame.html").as_uri())
        for i, body in enumerate(frames, start=1):
            fp.evaluate("h => { document.getElementById('stage').innerHTML = h; }", body)
            fp.evaluate(
                """async () => {
                  await document.fonts.ready;
                  await Promise.all([...document.images].map(im => im.complete ? null :
                    new Promise(r => { im.onload = im.onerror = r; })));
                }"""
            )
            overflow = fp.evaluate("() => document.getElementById('stage').scrollHeight > 640")
            fp.screenshot(path=str(FRAMES / f"frame-{i}.png"))
            check(not overflow, f"frame {i} is taller than 640 px (see {FRAMES})")
        browser.close()

    print(json.dumps({k: run[k] for k in ("import",)}, indent=2))
    print(f"frames: {FRAMES}")


if __name__ == "__main__":
    main()
