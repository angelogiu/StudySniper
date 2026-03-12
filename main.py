"""
main.py — UBC Study Sniper
Entry point. Loops back to home on errors. Exit option. Time-range scanning.
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

HEADLESS = True

if not booker.USERNAME or not booker.PASSWORD:
    ui.err("Credentials not found. Copy .env.example to .env and fill in your CWL details.")
    sys.exit(1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _input(label):
    bl = ui.c(ui.CYAN, "[")
    br = ui.c(ui.CYAN, "]")
    ar = ui.c(ui.BOLD + ui.CYAN, " >> ")
    lb = ui.c(ui.WHITE, label)
    mg = ui.c(ui.MAGENTA, "›")
    return ui._safe_input(f"  {bl}{ar}{br}  {lb}  {mg} ").strip()


def _parse_hhmm(s):
    """Parse HH:MM string, return datetime.time or None."""
    try:
        return datetime.strptime(s.strip(), "%H:%M").time()
    except ValueError:
        return None


def _time_slots_in_range(range_start, range_end, duration_hours=1):
    """
    Generate all HH:MM slot starts that fit within [range_start, range_end].
    e.g. 09:00–12:00 with 1h → [09:00, 10:00, 11:00]
    """
    slots = []
    cur = datetime.combine(datetime.today(), range_start)
    end = datetime.combine(datetime.today(), range_end)
    delta = timedelta(hours=duration_hours)
    while cur + delta <= end:
        slots.append(cur.strftime("%H:%M"))
        cur += timedelta(minutes=30)
    return slots


# ── Home screen ───────────────────────────────────────────────────────────────

def ask_mode():
    while True:
        ui.section("Home")
        opt1 = ui.c(ui.GOLD, "[1]")
        opt2 = ui.c(ui.GOLD, "[2]")
        opt3 = ui.c(ui.RED,  "[3]")
        ui._safe_print("     " + opt1 + "  " + ui.c(ui.BOLD + ui.WHITE, "AUTO  ") + "  " + ui.c(ui.GREY, "— instantly book the next available room"))
        ui._safe_print("     " + opt2 + "  " + ui.c(ui.BOLD + ui.WHITE, "MANUAL") + "  " + ui.c(ui.GREY, "— choose library, time range, and preferences"))
        ui._safe_print("     " + opt3 + "  " + ui.c(ui.BOLD + ui.WHITE, "EXIT  ") + "  " + ui.c(ui.GREY, "— quit Study Sniper"))
        ui._safe_print("")
        val = _input("Select (1, 2, or 3)")
        if val == "3":
            return "exit"
        if val in ("1", "2"):
            return val
        ui.err("Enter 1, 2, or 3.")


def ask_library():
    ui.section("Select Library")
    for k, lib in booker.LIBRARIES.items():
        ui._safe_print("     " + ui.c(ui.GOLD, "[" + k + "]") + "  " + ui.c(ui.BOLD + ui.WHITE, lib["name"]))
    ui._safe_print("")
    while True:
        val = _input("Select library (or 0 to go back)")
        if val == "0":
            return None
        if val in booker.LIBRARIES:
            return booker.LIBRARIES[val]
        ui.err("Enter 0-" + str(len(booker.LIBRARIES)) + ".")


def ask_date():
    today = datetime.today().strftime("%Y-%m-%d")
    while True:
        d = ui.prompt("Date (YYYY-MM-DD)", default=today)
        try:
            datetime.strptime(d, "%Y-%m-%d")
            return d
        except ValueError:
            ui.err("Invalid date format. Use YYYY-MM-DD (e.g. 2026-03-15).")


def ask_time_range():
    """Ask for a range like 09:00–17:00 and return (start, end) strings."""
    ui._safe_print("")
    ui._safe_print("  " + ui.c(ui.GREY, "Enter a time range and I'll show all bookable slots within it."))
    ui._safe_print("")
    while True:
        rs = ui.prompt("Range start (HH:MM, e.g. 09:00)")
        t  = _parse_hhmm(rs)
        if t:
            range_start = t
            break
        ui.err("Invalid time. Use HH:MM format.")
    while True:
        re_str = ui.prompt("Range end   (HH:MM, e.g. 17:00)")
        t = _parse_hhmm(re_str)
        if t:
            if t <= range_start:
                ui.err("End time must be after start time.")
                continue
            range_end = t
            break
        ui.err("Invalid time. Use HH:MM format.")
    return range_start, range_end


def ask_filter():
    ui._safe_print("")
    return ui.prompt("Filter by keyword? (room #, floor — Enter to skip)").lower()


# ── Time-range scanner ────────────────────────────────────────────────────────

async def scan_time_range(page, lib, date, range_start, range_end, keyword=""):
    """
    Scan every 30-min-offset slot within the range.
    Returns dict: { "HH:MM": [available_rooms] }
    """
    slots    = _time_slots_in_range(range_start, range_end, booker.BOOKING_DURATION_HOURS)
    duration = timedelta(hours=booker.BOOKING_DURATION_HOURS)
    results  = {}

    ui.section("Scanning Available Slots")
    ui._safe_print("  " + ui.c(ui.GREY, "Checking " + str(len(slots)) + " time slots in range..."))
    ui._safe_print("")

    for slot_start in slots:
        s_dt  = datetime.strptime(slot_start, "%H:%M")
        s_end = (s_dt + duration).strftime("%H:%M")
        url   = booker.build_search_url(lib["slug"], date, slot_start, s_end)
        with ui.Spinner(slot_start + " – " + s_end):
            available, _ = await booker.scrape_rooms(page, url, keyword)
        if available:
            results[slot_start] = available

    return results


def display_slot_results(results, duration_hours):
    """Pretty-print the scan results grouped by time slot."""
    if not results:
        ui.warn("No rooms found in that time range.")
        return

    duration = timedelta(hours=duration_hours)
    ui.section("Available Booking Slots")
    for slot_start in sorted(results.keys()):
        rooms  = results[slot_start]
        s_dt   = datetime.strptime(slot_start, "%H:%M")
        s_end  = (s_dt + duration).strftime("%H:%M")
        label  = ui.c(ui.BOLD + ui.GOLD, slot_start + " – " + s_end)
        count  = ui.c(ui.GREY, "(" + str(len(rooms)) + " room" + ("s" if len(rooms) != 1 else "") + ")")
        ui._safe_print("  " + ui.c(ui.CYAN, "┌─") + " " + label + "  " + count)
        for r in rooms:
            ui._safe_print("  " + ui.c(ui.CYAN, "│") + "  " + ui.c(ui.WHITE, "  • " + r["name"]))
        ui._safe_print("  " + ui.c(ui.CYAN, "└"))
        ui._safe_print("")


async def pick_slot_and_book(page, lib, date, results):
    """Let user pick a slot+room from the scan results and book it."""
    duration = timedelta(hours=booker.BOOKING_DURATION_HOURS)

    # Flatten into a numbered list
    options = []
    for slot_start in sorted(results.keys()):
        s_dt  = datetime.strptime(slot_start, "%H:%M")
        s_end = (s_dt + duration).strftime("%H:%M")
        for r in results[slot_start]:
            options.append({
                "room":  r,
                "start": slot_start,
                "end":   s_end,
                "label": slot_start + " – " + s_end,
            })

    ui.section("Pick a Slot")
    for i, opt in enumerate(options, 1):
        num   = ui.c(ui.GOLD, "[" + str(i) + "]")
        time  = ui.c(ui.GOLD, opt["label"])
        rname = ui.c(ui.BOLD + ui.WHITE, opt["room"]["name"])
        ui._safe_print("     " + num + "  " + time + "  —  " + rname)
    ui._safe_print("     " + ui.c(ui.GREY, "[0]  back to home"))
    ui._safe_print("")

    while True:
        try:
            idx = int(_input("Pick slot (1-" + str(len(options)) + ", or 0 to go back)"))
            if idx == 0:
                return False
            if 1 <= idx <= len(options):
                opt = options[idx - 1]
                return await booker.book_room(
                    page, opt["room"], date, opt["start"], opt["end"], HEADLESS
                )
        except ValueError:
            pass
        ui.err("Enter a number between 0 and " + str(len(options)) + ".")


# ── Auto mode ─────────────────────────────────────────────────────────────────

async def auto_book(page):
    try:
        date, start, end = booker.next_hour_slot()
        duration = timedelta(hours=booker.BOOKING_DURATION_HOURS)

        ui.section("Auto Book")
        ui.info("Scanning all libraries for earliest available room...")
        ui._safe_print("")

        # Collect ALL available rooms across all libraries at the next hour
        all_found = []
        for lib in booker.LIBRARIES.values():
            lib_name = lib["name"]
            url      = booker.build_search_url(lib["slug"], date, start, end)
            with ui.Spinner("Checking " + lib_name):
                available, later = await booker.scrape_rooms(page, url)
            for r in available:
                all_found.append({"room": r, "lib": lib, "lib_name": lib_name,
                                   "start": start, "end": end, "type": "now"})
            # Also parse later times from this library
            for r in later:
                t    = booker.parse_available_time(r.get("availability", ""))
                hhmm = booker.time_str_to_hhmm(t) if t else None
                if hhmm:
                    s_end = (datetime.strptime(hhmm, "%H:%M") + duration).strftime("%H:%M")
                    all_found.append({"room": r, "lib": lib, "lib_name": lib_name,
                                      "start": hhmm, "end": s_end, "type": "later"})
            if available:
                ui.ok(str(len(available)) + " room(s) free now at " + lib_name)
            else:
                ui.info("Nothing at " + start + " at " + lib_name)

        if not all_found:
            ui.warn("No rooms found across any library today.")
            ui._safe_print("")
            _input("Press Enter to return to home")
            return False

        # Sort: rooms available NOW first, then by earliest start time
        all_found.sort(key=lambda x: (0 if x["type"] == "now" else 1, x["start"]))

        # Find the single earliest option
        best      = all_found[0]
        room_name = best["room"]["name"]
        lib_name  = best["lib_name"]
        bstart    = best["start"]
        bend      = best["end"]

        ui._safe_print("")
        ui.section("Earliest Available")

        if best["type"] == "now":
            ui._safe_print("  " + ui.c(ui.GREEN,  "✦") + "  " + ui.c(ui.BOLD + ui.WHITE, room_name))
            ui._safe_print("     " + ui.c(ui.GREY, "Library : ") + ui.c(ui.WHITE, lib_name))
            ui._safe_print("     " + ui.c(ui.GREY, "Time    : ") + ui.c(ui.GOLD,  bstart + " – " + bend))
            ui._safe_print("     " + ui.c(ui.GREEN, "Available RIGHT NOW"))
        else:
            ui._safe_print("  " + ui.c(ui.GOLD,   "✦") + "  " + ui.c(ui.BOLD + ui.WHITE, room_name))
            ui._safe_print("     " + ui.c(ui.GREY, "Library : ") + ui.c(ui.WHITE, lib_name))
            ui._safe_print("     " + ui.c(ui.GREY, "Time    : ") + ui.c(ui.GOLD,  bstart + " – " + bend))
            ui._safe_print("     " + ui.c(ui.GOLD,  "Next available slot"))

        # Show a few more alternatives
        others = all_found[1:4]
        if others:
            ui._safe_print("")
            ui._safe_print("  " + ui.c(ui.GREY, "Other options:"))
            for o in others:
                ui._safe_print("     " + ui.c(ui.GREY, "• " + o["room"]["name"] + "  " + o["start"] + " – " + o["end"] + "  @ " + o["lib_name"]))

        ui._safe_print("")
        if ui.confirm("Book " + room_name + " at " + bstart + " – " + bend + "?"):
            # Re-scrape to get a fresh checksum URL for the exact slot
            url = booker.build_search_url(best["lib"]["slug"], date, bstart, bend)
            with ui.Spinner("Getting booking link"):
                avail2, _ = await booker.scrape_rooms(page, url)
            match = next((x for x in avail2 if room_name in x["name"] or x["name"] in room_name), None)
            if match:
                return await booker.book_room(page, match, date, bstart, bend, HEADLESS)
            ui.warn("Could not get a fresh booking link. Try Manual mode.")
        else:
            ui.info("No booking made.")

    except Exception as ex:
        ui.err("Auto booking failed: " + str(ex))

    ui._safe_print("")
    _input("Press Enter to return to home")
    return False


# ── Manual mode ───────────────────────────────────────────────────────────────

async def manual_book(page):
    try:
        # ── Library ───────────────────────────────────────────────────────────
        lib = ask_library()
        if lib is None:
            return False   # back to home

        lib_name = lib["name"]
        lib_slug = lib["slug"]

        # ── Date ──────────────────────────────────────────────────────────────
        ui._safe_print("")
        date = ask_date()

        # ── Time range ────────────────────────────────────────────────────────
        range_start, range_end = ask_time_range()
        keyword                = ask_filter()

        # ── Scan all slots in range ───────────────────────────────────────────
        results = await scan_time_range(page, lib, date, range_start, range_end, keyword)
        display_slot_results(results, booker.BOOKING_DURATION_HOURS)

        if not results:
            ui._safe_print("")
            _input("Press Enter to return to home")
            return False

        # ── Let user pick and book ────────────────────────────────────────────
        booked = await pick_slot_and_book(page, lib, date, results)
        if not booked:
            return False   # user picked 0, back to home

        return booked

    except Exception as ex:
        ui.err("Something went wrong: " + str(ex))
        ui._safe_print("")
        _input("Press Enter to return to home")
        return False


# ── Entry ─────────────────────────────────────────────────────────────────────

async def main():
    ui.start_animation()

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

        # ── Main loop — keeps returning to home until exit ────────────────────
        while True:
            mode = ask_mode()

            if mode == "exit":
                ui.info("Goodbye.")
                break

            try:
                if mode == "1":
                    await auto_book(page)
                else:
                    await manual_book(page)
            except Exception as ex:
                ui.err("Unexpected error: " + str(ex))
                ui._safe_print("")
                _input("Press Enter to return to home")

        if booker.DEBUG_SHOTS:
            ui.info("Screenshots saved to ./screenshots/")
        await browser.close()

    ui.stop_animation()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        ui.stop_animation()
        print("\n\n  " + ui.c(ui.GREY, "Cancelled.") + "\n")