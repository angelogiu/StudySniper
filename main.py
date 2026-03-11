"""
main.py — UBC Study Sniper
Entry point. Orchestrates auto/manual booking flows with neon terminal UI.
"""

import asyncio
import os
import re
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
from playwright.async_api import async_playwright

import ui
import booker

# ── Load config ───────────────────────────────────────────────────────────────
load_dotenv()

booker.USERNAME               = os.getenv("UBC_USERNAME", "")
booker.PASSWORD               = os.getenv("UBC_PASSWORD", "")
booker.BOOKING_DURATION_HOURS = int(os.getenv("BOOKING_DURATION_HOURS", "1"))
booker.DEBUG_SHOTS            = os.getenv("DEBUG_SHOTS", "false").lower() == "true"

HEADLESS = True   # browser offscreen except during CWL auth

if not booker.USERNAME or not booker.PASSWORD:
    ui.err("Credentials not found. Copy .env.example to .env and fill in your CWL details.")
    sys.exit(1)


# ── Prompts ───────────────────────────────────────────────────────────────────

def _input(label):
    bracket_l = ui.c(ui.CYAN, "[")
    bracket_r = ui.c(ui.CYAN, "]")
    arrows    = ui.c(ui.BOLD + ui.CYAN, " >> ")
    lbl       = ui.c(ui.WHITE, label)
    arrow     = ui.c(ui.MAGENTA, "›")
    return input(f"  {bracket_l}{arrows}{bracket_r}  {lbl}  {arrow} ").strip()


def ask_mode():
    ui.section("Select Mode")
    opt1 = ui.c(ui.GOLD, "[1]")
    opt2 = ui.c(ui.GOLD, "[2]")
    auto = ui.c(ui.BOLD + ui.WHITE, "AUTO")
    man  = ui.c(ui.BOLD + ui.WHITE, "MANUAL")
    d1   = ui.c(ui.GREY, "— instantly book the next available room")
    d2   = ui.c(ui.GREY, "— choose library, time, and preferences")
    print(f"     {opt1}  {auto}    {d1}")
    print(f"     {opt2}  {man}  {d2}")
    print()
    while True:
        val = _input("Select mode (1 or 2)")
        if val in ("1", "2"):
            return val
        ui.err("Enter 1 or 2.")


def ask_library():
    ui.section("Select Library")
    for k, lib in booker.LIBRARIES.items():
        name = lib["name"]
        print(f"     {ui.c(ui.GOLD, '[' + k + ']')}  {ui.c(ui.BOLD + ui.WHITE, name)}")
    print()
    while True:
        val = _input("Select library")
        if val in booker.LIBRARIES:
            return booker.LIBRARIES[val]
        ui.err("Enter 1-" + str(len(booker.LIBRARIES)) + ".")


def ask_datetime():
    print()
    today = datetime.today().strftime("%Y-%m-%d")
    d = ui.prompt("Date (YYYY-MM-DD)", default=today)
    s = ui.prompt("Start time (HH:MM, e.g. 14:00)")
    e = ui.prompt("End time   (HH:MM, e.g. 15:00)")
    return d, s, e


def ask_filter():
    print()
    return ui.prompt("Filter by keyword? (room #, floor — Enter to skip)").lower()


# ── Auto mode ─────────────────────────────────────────────────────────────────

async def auto_book(page):
    date, start, end = booker.next_hour_slot()

    ui.section("Auto Book")
    ui.info("Target slot: " + date + "  " + start + "-" + end)
    ui.info("Scanning all libraries ...")
    print()

    for lib in booker.LIBRARIES.values():
        lib_name = lib["name"]
        url      = booker.build_search_url(lib["slug"], date, start, end)
        with ui.Spinner("Checking " + lib_name):
            available, _ = await booker.scrape_rooms(page, url)

        if available:
            room_name = available[0]["name"]
            ui.ok("Found: " + room_name + " @ " + lib_name)
            return await booker.book_room(page, available[0], date, start, end, HEADLESS)
        ui.info("Nothing free at " + lib_name)

    ui.err("No rooms instantly available at " + start + " across any library.")
    ui.info("Try Manual mode to find the next available slot.")
    return False


# ── Manual mode ───────────────────────────────────────────────────────────────

async def manual_book(page):
    lib              = ask_library()
    date, start, end = ask_datetime()
    keyword          = ask_filter()

    lib_name = lib["name"]
    lib_slug = lib["slug"]

    ui.section("Searching " + lib_name)
    url = booker.build_search_url(lib_slug, date, start, end)

    with ui.Spinner("Searching " + start + "-" + end + " on " + date):
        available, later = await booker.scrape_rooms(page, url, keyword)

    # ── Exact match ───────────────────────────────────────────────────────────
    if available:
        ui.room_list(available, "Available at " + start + "-" + end)
        chosen = ui.pick_room(available, allow_skip=True)
        if chosen:
            return await booker.book_room(page, chosen, date, start, end, HEADLESS)
    else:
        ui.warn("No rooms available at exactly " + start + "-" + end + ".")

    # ── Parse nearby times ────────────────────────────────────────────────────
    later_with_times = []
    for r in later:
        t    = booker.parse_available_time(r.get("availability", ""))
        hhmm = booker.time_str_to_hhmm(t) if t else None
        if hhmm:
            s_dt = datetime.strptime(hhmm, "%H:%M")
            e_dt = s_dt + timedelta(hours=booker.BOOKING_DURATION_HOURS)
            later_with_times.append({
                **r,
                "avail_start": hhmm,
                "avail_end":   e_dt.strftime("%H:%M"),
                "avail_label": t,
            })

    if not later_with_times and not available:
        ui.err("No alternative rooms found either.")
        return False

    # ── Similar rooms free right now ──────────────────────────────────────────
    if available and later_with_times:
        similar_now = []
        for wanted in later_with_times:
            for ar in available:
                bw = re.sub(r"[A-Za-z]", "", booker.room_base_name(wanted["name"]))
                ba = re.sub(r"[A-Za-z]", "", booker.room_base_name(ar["name"]))
                pair_exists = any(x[0] == wanted["name"] and x[1] is ar for x in similar_now)
                if bw == ba and not pair_exists:
                    similar_now.append((wanted["name"], ar))

        if similar_now:
            ui.section("Similar Rooms Free RIGHT NOW")
            for wanted_name, r in similar_now:
                r_name = r["name"]
                ui.info(wanted_name + " is taken  ->  " + r_name + " is free at " + start + "-" + end)
            print()
            for wanted_name, r in similar_now:
                r_name = r["name"]
                if ui.confirm("Book '" + r_name + "' (similar to " + wanted_name + ") at " + start + "-" + end + "?"):
                    return await booker.book_room(page, r, date, start, end, HEADLESS)

    # ── Nearby time suggestions ───────────────────────────────────────────────
    if later_with_times:
        later_with_times.sort(key=lambda r: r["avail_start"])

        seen        = set()
        suggestions = []
        for r in later_with_times:
            r_name = r["name"]
            if r_name in seen:
                continue
            seen.add(r_name)
            close = []
            candidates = [x for x in later_with_times if x["name"] != r_name and x["name"] not in seen]
            for s in booker.similar_rooms(r_name, candidates):
                br = re.sub(r"[A-Za-z]", "", booker.room_base_name(r_name))
                bs = re.sub(r"[A-Za-z]", "", booker.room_base_name(s["name"]))
                if br == bs:
                    close.append(s)
                    seen.add(s["name"])
            suggestions.append({"primary": r, "similar": close})

        ui.section("Rooms Available at Other Times")
        for sg in suggestions:
            r       = sg["primary"]
            rname   = r["name"]
            rlabel  = r["avail_label"]
            dot     = ui.c(ui.CYAN, "•")
            styled  = ui.c(ui.BOLD + ui.WHITE, rname)
            fr_str  = ui.c(ui.GREY, "— free from")
            t_str   = ui.c(ui.GOLD, rlabel)
            print("     " + dot + "  " + styled + "  " + fr_str + "  " + t_str)
            for alt in sg["similar"]:
                aname  = alt["name"]
                alabel = alt["avail_label"]
                print("        " + ui.c(ui.GREY, "also: " + aname + " — free from " + alabel))
        print()

        for sg in suggestions:
            r      = sg["primary"]
            alts   = sg["similar"]
            rname  = r["name"]
            rlabel = r["avail_label"]
            rstart = r["avail_start"]
            rend   = r["avail_end"]

            if ui.confirm("Book '" + rname + "' at " + rlabel + " (" + rstart + "-" + rend + ")?"):
                new_url = booker.build_search_url(lib_slug, date, rstart, rend)
                with ui.Spinner("Fetching booking link for " + rlabel):
                    avail2, _ = await booker.scrape_rooms(page, new_url)
                match = next((x for x in avail2 if rname in x["name"] or x["name"] in rname), None)
                if match:
                    return await booker.book_room(page, match, date, rstart, rend, HEADLESS)
                ui.warn("Could not get a fresh booking link for that slot.")
                continue

            for alt in alts:
                aname  = alt["name"]
                alabel = alt["avail_label"]
                astart = alt["avail_start"]
                aend   = alt["avail_end"]
                if ui.confirm("How about '" + aname + "' at " + alabel + " (" + astart + "-" + aend + ")?"):
                    new_url = booker.build_search_url(lib_slug, date, astart, aend)
                    with ui.Spinner("Fetching booking link"):
                        avail2, _ = await booker.scrape_rooms(page, new_url)
                    match = next((x for x in avail2 if aname in x["name"] or x["name"] in aname), None)
                    if match:
                        return await booker.book_room(page, match, date, astart, aend, HEADLESS)
                    ui.warn("Could not get a fresh booking link for that slot.")

    ui.info("No booking made.")
    return False


# ── Entry ─────────────────────────────────────────────────────────────────────

async def main():
    ui.splash()
    mode = ask_mode()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=400,
            args=["--window-size=1100,800", "--window-position=100,50"],
        )
        context = await browser.new_context(viewport={"width": 1100, "height": 800})
        page    = await context.new_page()

        if HEADLESS:
            await page.evaluate("() => { window.moveTo(-2000, 0); }")

        try:
            if mode == "1":
                await auto_book(page)
            else:
                await manual_book(page)
        finally:
            if booker.DEBUG_SHOTS:
                ui.info("Screenshots saved to ./screenshots/")
            await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        cancelled = ui.c(ui.GREY, "Cancelled.")
        print("\n\n  " + cancelled + "\n")