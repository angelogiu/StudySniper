"""
booker.py — Core scraping and booking logic for UBC Study Sniper
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

import ui

# ── Config (set by main.py) ───────────────────────────────────────────────────
USERNAME               = ""
PASSWORD               = ""
BOOKING_DURATION_HOURS = 1
DEBUG_SHOTS            = True
SCREENSHOT_DIR         = Path("screenshots")

UBC_LIBCAL_BASE = "https://libcal.library.ubc.ca"

LIBRARIES = {
    "1": {"name": "Irving K. Barber Learning Centre (IKB)", "slug": "ikbstudy"},
    "2": {"name": "Koerner Library",                        "slug": "koerner_library"},
    "3": {"name": "Woodward Library",                       "slug": "woodward_library"},
    "4": {"name": "Music, Art & Architecture (MAA) Library","slug": "maa"},
}


# ── Utilities ─────────────────────────────────────────────────────────────────

async def shot(page: Page, name: str):
    if not DEBUG_SHOTS:
        return
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    path = SCREENSHOT_DIR / f"{datetime.now().strftime('%H%M%S')}_{name}.png"
    await page.screenshot(path=str(path), full_page=True)


def build_search_url(slug: str, date: str, start: str, end: str) -> str:
    s = start.replace(":", "%3A")
    e = end.replace(":", "%3A")
    return (
        f"{UBC_LIBCAL_BASE}/r/search/{slug}"
        f"?m=t&gid=0&capacity=0"
        f"&date={date}&date-end={date}"
        f"&start={s}&end={e}"
    )


def next_hour_slot() -> tuple[str, str, str]:
    now      = datetime.now()
    start_dt = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    end_dt   = start_dt + timedelta(hours=BOOKING_DURATION_HOURS)
    return (
        start_dt.strftime("%Y-%m-%d"),
        start_dt.strftime("%H:%M"),
        end_dt.strftime("%H:%M"),
    )


def parse_available_time(text: str) -> str | None:
    m = re.search(r"available from\s+([\d:]+[ap]m)", text, re.IGNORECASE)
    return m.group(1) if m else None


def time_str_to_hhmm(t: str) -> str | None:
    for fmt in ("%I:%M%p", "%I:%M %p"):
        try:
            return datetime.strptime(t.strip(), fmt).strftime("%H:%M")
        except ValueError:
            continue
    return None


def room_base_name(name: str) -> str:
    m = re.match(r"([A-Za-z]?\d+)", name.strip())
    return m.group(1) if m else name[:4]


def similar_rooms(target_name: str, candidates: list[dict]) -> list[dict]:
    base   = room_base_name(target_name)
    digits = re.sub(r"[^0-9]", "", base)
    floor  = digits[0] if digits else ""
    scored = []
    for c in candidates:
        cb = room_base_name(c["name"])
        cd = re.sub(r"[^0-9]", "", cb)
        if re.sub(r"[A-Za-z]", "", cb) == re.sub(r"[A-Za-z]", "", base):
            scored.append((0, c))
        elif cd and floor and cd[0] == floor:
            scored.append((1, c))
        else:
            scored.append((2, c))
    scored.sort(key=lambda x: (x[0], x[1]["name"]))
    return [r for _, r in scored]


# ── Scraping ──────────────────────────────────────────────────────────────────

def _split_rooms(raw: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split into available-now (has checksum) and available-later."""
    now, later = [], []
    for r in raw:
        href = r.get("href", "") or ""
        (now if ("checksum=" in href and "start=" in href) else later).append(r)
    return now, later


async def scrape_rooms(page: Page, url: str, keyword: str = "") -> tuple[list[dict], list[dict]]:
    await page.goto(url, wait_until="domcontentloaded", timeout=25000)
    await page.wait_for_timeout(2500)
    await shot(page, "search_results")

    try:
        ok_btn = page.locator("button:has-text('OK'), button:has-text('Accept')")
        if await ok_btn.count() > 0:
            await ok_btn.first.click(timeout=2000)
    except Exception:
        pass

    raw     = []
    anchors = await page.locator("h3 a[href*='/space/'], h2 a[href*='/space/']").all()
    for anchor in anchors:
        try:
            name = (await anchor.inner_text()).strip()
            href = await anchor.get_attribute("href")
            if not href:
                continue
            card  = anchor.locator("xpath=ancestor::div[contains(@class,'col') or contains(@class,'s-lc')][1]")
            avail = ""
            if await card.count() > 0:
                for p in await card.locator("p").all():
                    t = (await p.inner_text()).strip()
                    if t:
                        avail = t
                        break
            if keyword and keyword not in name.lower() and keyword not in avail.lower():
                continue
            full_href = href if href.startswith("http") else UBC_LIBCAL_BASE + href
            raw.append({"name": name, "href": full_href, "availability": avail})
        except Exception:
            continue

    return _split_rooms(raw)


# ── Auth ──────────────────────────────────────────────────────────────────────

async def handle_cwl_login(page: Page, headless: bool) -> bool:
    """
    Show the browser during CWL/Duo auth, wait until back on libcal, then
    if running headless we can't re-hide the window — but we keep it open
    only for the auth step.
    """
    await page.wait_for_load_state("domcontentloaded", timeout=15000)
    await page.wait_for_timeout(1000)
    await shot(page, "cwl_login_page")

    url     = page.url
    content = await page.content()
    needs   = (
        "authentication.ubc.ca" in url
        or "cwl" in url.lower()
        or "shibboleth" in url.lower()
        or "userid" in content
    )
    if not needs:
        return True

    ui.auth_banner()

    max_wait = 180
    waited   = 0
    while waited < max_wait:
        await page.wait_for_timeout(1000)
        waited += 1
        cur = page.url
        if "libcal" in cur or ("library.ubc.ca" in cur and "authentication" not in cur):
            sys.stdout.write("\r" + " " * 70 + "\r")
            ui.ok("Login complete — continuing!")
            await page.wait_for_timeout(1500)
            await shot(page, "cwl_done")
            return True
        ui.waiting_tick(waited, max_wait, cur)

    print()
    ui.err("Timed out waiting for login (3 minutes).")
    return False


# ── Booking ───────────────────────────────────────────────────────────────────

async def book_room(page: Page, room: dict, date: str, start: str, end: str, headless: bool) -> bool:
    href = room.get("href", "")
    if not href:
        ui.err("No booking link for this room.")
        return False
    if not href.startswith("http"):
        href = UBC_LIBCAL_BASE + href

    ui.step(f"Opening room page: {room['name']}")
    await page.goto(href, wait_until="domcontentloaded", timeout=15000)
    await page.wait_for_timeout(2000)
    await shot(page, "step1_room_page")

    # ── Click Book Now ────────────────────────────────────────────────────────
    book_now = page.locator("a:has-text('Book Now'), button:has-text('Book Now')")
    if await book_now.count() == 0:
        await shot(page, "step1_no_book_now")
        ui.warn("No 'Book Now' button found — check step1_room_page.png")
        return False

    ui.step("Clicking Book Now ...")
    await book_now.first.click(timeout=5000)
    await page.wait_for_load_state("domcontentloaded", timeout=20000)
    await page.wait_for_timeout(3000)
    await shot(page, "step2_after_book_now")

    # ── CWL / Duo auth ────────────────────────────────────────────────────────
    content  = await page.content()
    needs_auth = (
        any(x in page.url.lower() for x in ["cwl", "shibboleth", "login", "auth", "duosecurity"])
        or "userid" in content
        or "cwl login" in content.lower()
    )
    if needs_auth:
        ok = await handle_cwl_login(page, headless)
        if not ok:
            return False
        await page.wait_for_timeout(2000)
        await shot(page, "step3_post_auth")

    # ── Wait for Booking Review form ──────────────────────────────────────────
    try:
        await page.wait_for_selector("text=Fill out this form to complete", timeout=10000)
        ui.ok("Booking review form loaded")
    except PlaywrightTimeout:
        try:
            await page.wait_for_selector("input[value='Submit booking']", timeout=5000)
        except PlaywrightTimeout:
            await shot(page, "step3_form_not_found")
            ui.warn("Booking form not found — check step3_booking_form.png")
            ui.warn(f"URL: {page.url}")
            input("\n  Browser is open — complete manually if needed, then press Enter ...")
            return False

    await shot(page, "step3_booking_form")
    await page.wait_for_timeout(1000)

    # ── Fill radio confirmations ──────────────────────────────────────────────
    ui.step("Filling booking form ...")
    radios  = await page.locator("input[type='radio']").all()
    checked = 0
    for radio in radios:
        try:
            if not await radio.is_checked():
                await radio.check()
                checked += 1
        except Exception:
            continue
    if checked:
        ui.ok(f"Checked {checked} confirmation(s)")

    try:
        cb = page.locator("input[type='checkbox']")
        if await cb.count() > 0 and not await cb.first.is_checked():
            await cb.first.check()
            ui.ok("Accepted Terms & Conditions")
    except Exception:
        pass

    await page.wait_for_timeout(500)
    await shot(page, "step4_form_filled")

    # ── Submit ────────────────────────────────────────────────────────────────
    submit = page.locator("input[value='Submit booking']")
    if await submit.count() == 0:
        submit = page.locator("form input[type='submit'], form button[type='submit']").last
        if await submit.count() == 0:
            await shot(page, "step4_no_submit")
            ui.warn("Submit button not found — check step3_booking_form.png")
            input("\n  Browser is open — complete manually if needed, then press Enter ...")
            return False

    await submit.scroll_into_view_if_needed()
    await page.wait_for_timeout(500)

    ui.step("Submitting booking ...")
    await submit.first.click(timeout=5000)
    await page.wait_for_load_state("domcontentloaded", timeout=20000)
    await page.wait_for_timeout(3000)
    await shot(page, "step5_final")

    # ── Confirm ───────────────────────────────────────────────────────────────
    body = (await page.inner_text("body")).lower()
    if any(w in body for w in ["confirmed", "success", "thank you", "your booking", "booked", "confirmation"]):
        ui.success(f"Booking confirmed!", f"Room: {room['name']}  |  {date}  {start}–{end}")
        input("  Press Enter to close ...")
        return True

    ui.warn("Form submitted but no confirmation detected.")
    ui.warn(f"URL: {page.url}")
    ui.info("Check step5_final.png and your UBC email.")
    input("\n  Browser open — complete manually if needed, then press Enter ...")
    return False


import sys