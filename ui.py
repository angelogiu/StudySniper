"""
ui.py — Terminal UI for UBC Study Sniper
Animated gradient header runs continuously in background thread.
Menu/prompts scroll below it, header stays locked at top.
"""

import sys
import time
import threading
import os

RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
CYAN    = "\033[38;5;51m"
MAGENTA = "\033[38;5;201m"
GREEN   = "\033[38;5;82m"
GOLD    = "\033[38;5;220m"
PURPLE  = "\033[38;5;135m"
RED     = "\033[38;5;196m"
WHITE   = "\033[38;5;255m"
GREY    = "\033[38;5;240m"
DKGREY  = "\033[38;5;236m"
TEAL    = "\033[38;5;43m"

def c(colour, text):
    return colour + text + RESET

def rgb(r, g, b, text, bold=False):
    b_code = "\033[1m" if bold else ""
    return f"{b_code}\033[38;2;{r};{g};{b}m{text}{RESET}"


# ── Gradient math ─────────────────────────────────────────────────────────────

KEYFRAMES = [
    (0,   255, 255),
    (0,   80,  255),
    (140, 0,   255),
    (220, 0,   255),
    (255, 60,  180),
    (255, 180, 0  ),
    (80,  255, 80 ),
    (0,   220, 180),
    (0,   255, 255),
]
_NKF = len(KEYFRAMES) - 1

def _grad(t):
    t   = t % 1.0
    seg = t * _NKF
    i   = int(seg)
    f   = seg - i
    f   = f * f * (3 - 2 * f)
    r0, g0, b0 = KEYFRAMES[i]
    r1, g1, b1 = KEYFRAMES[i + 1]
    return (int(r0+(r1-r0)*f), int(g0+(g1-g0)*f), int(b0+(b1-b0)*f))


# ── ASCII art ─────────────────────────────────────────────────────────────────

STUDY_LINES = [
    " ███████╗████████╗██╗   ██╗██████╗ ██╗   ██╗",
    " ██╔════╝╚══██╔══╝██║   ██║██╔══██╗╚██╗ ██╔╝",
    " ███████╗   ██║   ██║   ██║██║  ██║ ╚████╔╝ ",
    " ╚════██║   ██║   ██║   ██║██║  ██║  ╚██╔╝  ",
    " ███████║   ██║   ╚██████╔╝██████╔╝   ██║   ",
    " ╚══════╝   ╚═╝    ╚═════╝ ╚═════╝    ╚═╝   ",
]
SNIPER_LINES = [
    " ███████╗███╗  ██╗██╗██████╗ ███████╗██████╗ ",
    " ██╔════╝████╗ ██║██║██╔══██╗██╔════╝██╔══██╗",
    " ███████╗██╔██╗██║██║██████╔╝█████╗  ██████╔╝",
    " ╚════██║██║╚████║██║██╔═══╝ ██╔══╝  ██╔══██╗",
    " ███████║██║ ╚███║██║██║     ███████╗██║  ██║",
    " ╚══════╝╚═╝  ╚══╝╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝",
]
W = 50

# Header occupies this many lines (used to set terminal scroll region)
# top border + blank + 6 + blank + 6 + blank + tag + blank + bottom
HEADER_H = 19


def _colour_line(art, phase, row_t):
    padded = art.ljust(W)[:W]
    out = ""
    n   = len(padded)
    for i, ch in enumerate(padded):
        if ch == " ":
            out += " "
        else:
            t = (i / n) * 0.45 + row_t + phase
            r, g, b = _grad(t)
            out += rgb(r, g, b, ch, bold=True)
    return out

def _brgb(phase, off=0.0):
    return _grad((phase + off) % 1.0)

def _build_header(phase):
    lines = []
    lc  = _brgb(phase, 0.0);  rc  = _brgb(phase, 0.5)
    mc  = _brgb(phase, 0.25); mc2 = _brgb(phase, 0.75)

    def blank(l, r):
        return "  " + rgb(*l,"║",True) + " "*W + rgb(*r,"║",True)

    lines.append("  " + rgb(*lc,"╔"+"═"*W+"╗",True))
    lines.append(blank(lc, rc))
    for i, art in enumerate(STUDY_LINES):
        rt = i * 0.035
        l = _brgb(phase,rt); r = _brgb(phase,rt+0.5)
        lines.append("  " + rgb(*l,"║",True) + _colour_line(art,phase,rt) + rgb(*r,"║",True))
    lines.append(blank(mc, mc2))
    for i, art in enumerate(SNIPER_LINES):
        rt = 0.25 + i*0.035
        l = _brgb(phase,rt); r = _brgb(phase,rt+0.5)
        lines.append("  " + rgb(*l,"║",True) + _colour_line(art,phase,rt) + rgb(*r,"║",True))
    lines.append(blank(rc, lc))
    tag = "  • UBC Library Room Booking Automation •"
    tl = _brgb(phase,0.2); tr = _brgb(phase,0.7)
    lines.append("  " + rgb(*tl,"║",True) + _colour_line(tag.ljust(W)[:W],phase,0.2) + rgb(*tr,"║",True))
    lines.append(blank(rc, lc))
    lines.append("  " + rgb(*rc,"╚"+"═"*W+"╝",True))
    return lines


# ── Background animator ───────────────────────────────────────────────────────

# ANSI: save/restore cursor, move to row/col
_SAVE    = "\033[s"
_RESTORE = "\033[u"
_HIDE    = "\033[?25l"
_SHOW    = "\033[?25h"

def _goto(row, col=1):
    return f"\033[{row};{col}H"

# Scroll region: tell terminal that lines HEADER_H+1 onward are the scroll area
# so our prints go below the header without disturbing it
def _set_scroll_region(top, bottom):
    return f"\033[{top};{bottom}r"

def _reset_scroll():
    return "\033[r"


_anim_thread  = None
_anim_stop    = threading.Event()
_print_lock   = threading.Lock()
_term_rows    = 40  # updated on start


def _animator():
    phase = 0.0
    out   = sys.stdout
    while not _anim_stop.is_set():
        with _print_lock:
            out.write(_SAVE)
            out.write(_goto(1))
            out.write(_HIDE)
            for line in _build_header(phase):
                out.write("\r" + line + "\n")
            out.write(_RESTORE)
            out.write(_SHOW)
            out.flush()
        phase = (phase + 0.008) % 1.0
        time.sleep(1.0 / 24)


def start_animation():
    """
    Call once at startup. Prints header, sets scroll region below it,
    then starts background thread to keep colours moving.
    """
    global _anim_thread, _anim_stop, _term_rows

    # Get terminal size
    try:
        size = os.get_terminal_size()
        _term_rows = size.lines
    except Exception:
        _term_rows = 40

    out = sys.stdout

    # Clear screen, draw header at top
    out.write("\033[2J\033[H")
    out.flush()
    for line in _build_header(0.0):
        out.write(line + "\n")
    out.flush()

    # Lock scroll region to below the header
    scroll_top = HEADER_H + 2
    out.write(_set_scroll_region(scroll_top, _term_rows))
    # Move cursor into the scroll zone
    out.write(_goto(scroll_top))
    out.flush()

    # Start background animation thread
    _anim_stop.clear()
    _anim_thread = threading.Thread(target=_animator, daemon=True)
    _anim_thread.start()


def stop_animation():
    """Clean up scroll region on exit."""
    _anim_stop.set()
    if _anim_thread:
        _anim_thread.join(timeout=0.5)
    sys.stdout.write(_reset_scroll())
    sys.stdout.write(_SHOW)
    sys.stdout.flush()


def _safe_print(*args, **kwargs):
    """Thread-safe print that won't collide with the animator."""
    with _print_lock:
        print(*args, **kwargs)

def _safe_input(prompt_str):
    """Thread-safe input."""
    with _print_lock:
        sys.stdout.write(prompt_str)
        sys.stdout.flush()
    # Release lock while waiting for user — animator can keep running
    return input("")


# ── Spinner ───────────────────────────────────────────────────────────────────

class Spinner:
    FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

    def __init__(self, message):
        self.message = message
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        i = 0; phase = 0.0
        while not self._stop.is_set():
            frame = self.FRAMES[i % len(self.FRAMES)]
            r, g, b = _grad(phase)
            spinner = rgb(r, g, b, frame)
            words   = self.message.split()
            styled  = ""
            for j, w in enumerate(words):
                wr, wg, wb = _grad((phase + j*0.15) % 1.0)
                styled += rgb(wr, wg, wb, w) + " "
            with _print_lock:
                sys.stdout.write("\r  " + spinner + "  " + styled.rstrip() + c(DIM+GREY," ...") + "   ")
                sys.stdout.flush()
            time.sleep(0.07)
            i += 1; phase = (phase + 0.025) % 1.0

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join()
        with _print_lock:
            sys.stdout.write("\r" + " "*72 + "\r")
            sys.stdout.flush()


# ── Section / status (use _safe_print so animator doesn't clobber) ────────────

def section(title):
    pad = max(0, 44 - len(title) - 4)
    _safe_print("\n  " + c(MAGENTA,"┌──") + " " + c(BOLD+GOLD,title.upper()) + " " + c(MAGENTA,"─"*pad+"┐"))

def ok(msg):
    _safe_print("  " + c(GREEN,"[") + c(BOLD+GREEN," OK ") + c(GREEN,"]") + "  " + c(WHITE,msg))

def info(msg):
    _safe_print("  " + c(CYAN,"[")  + c(BOLD+CYAN," .. ")  + c(CYAN,"]")  + "  " + c(GREY,msg))

def warn(msg):
    _safe_print("  " + c(GOLD,"[")  + c(BOLD+GOLD," !! ")  + c(GOLD,"]")  + "  " + c(GOLD,msg))

def err(msg):
    _safe_print("  " + c(RED,"[")   + c(BOLD+RED,"ERR!")    + c(RED,"]")   + "  " + c(RED,msg))

def step(msg):
    _safe_print("  " + c(PURPLE,"[")+ c(BOLD+CYAN," >> ")  + c(PURPLE,"]")+ "  " + c(WHITE,msg))


# ── Auth banner ───────────────────────────────────────────────────────────────

def auth_banner():
    BW = 46
    def arow(text, col=WHITE):
        inner = text.ljust(BW-2)[:BW-2]
        return "  " + c(GOLD,"║") + "  " + c(col,inner) + "  " + c(GOLD,"║")
    _safe_print("\n  " + c(GOLD,"╔"+"═"*BW+"╗"))
    _safe_print(arow("🔐  CWL LOGIN REQUIRED", BOLD+GOLD))
    _safe_print("  " + c(GOLD,"║") + " "*BW + c(GOLD,"║"))
    _safe_print(arow("Log in manually in the browser window.", WHITE))
    _safe_print(arow("Complete CWL login + Duo MFA prompt.", WHITE))
    _safe_print(arow("Script resumes automatically once done.", DIM+GREY))
    _safe_print("  " + c(GOLD,"╚"+"═"*BW+"╝") + "\n")

def waiting_tick(waited, max_wait, url=""):
    bar_len = 30
    filled  = int(bar_len * waited / max_wait)
    r, g, b = _grad(waited / max_wait * 0.5)
    bar     = rgb(r,g,b,"█"*filled) + c(DKGREY,"░"*(bar_len-filled))
    with _print_lock:
        sys.stdout.write("\r  " + c(GOLD,"[") + " " + bar + " " + c(GOLD,"]") + "  " + c(GREY,str(max_wait-waited)+"s remaining") + "   ")
        sys.stdout.flush()


# ── Success ───────────────────────────────────────────────────────────────────

def success(title, detail=""):
    SW = 46
    def grow(text, col=WHITE):
        inner = text.ljust(SW-2)[:SW-2]
        return "  " + c(GREEN,"║") + "  " + c(col,inner) + "  " + c(GREEN,"║")
    _safe_print("\n  " + c(GREEN,"╔"+"═"*SW+"╗"))
    _safe_print(grow(""))
    _safe_print(grow("  ✦  BOOKING CONFIRMED  ✦", BOLD+GREEN))
    _safe_print(grow(""))
    _safe_print(grow("  " + title, BOLD+WHITE))
    if detail:
        _safe_print(grow("  " + detail, GOLD))
    _safe_print(grow(""))
    _safe_print("  " + c(GREEN,"╚"+"═"*SW+"╝") + "\n")


# ── Prompts ───────────────────────────────────────────────────────────────────

def prompt(question, default=""):
    dflt = (" " + c(DIM+GREY,"["+default+"]")) if default else ""
    prompt_str = (
        "  " + c(CYAN,"[") + c(BOLD+CYAN," ?? ") + c(CYAN,"]") +
        "  " + c(WHITE,question) + dflt + "  " + c(MAGENTA,"›") + " "
    )
    return _safe_input(prompt_str).strip() or default

def confirm(question):
    prompt_str = (
        "  " + c(GOLD,"[") + c(BOLD+GOLD," ?? ") + c(GOLD,"]") +
        "  " + c(WHITE,question) + "  " + c(DIM+GREY,"[y/n]") + "  " + c(MAGENTA,"›") + " "
    )
    return _safe_input(prompt_str).strip().lower() in ("y","yes")

def room_list(rooms, title):
    section(title)
    for i, r in enumerate(rooms, 1):
        avail = ("  " + c(DIM+TEAL,r["availability"])) if r.get("availability") else ""
        _safe_print("     " + c(GOLD,"["+str(i)+"]") + "  " + c(BOLD+WHITE,r["name"]) + avail)
    _safe_print("")

def pick_room(rooms, allow_skip=False):
    skip_hint = (" " + c(GOLD,"[0]") + " " + c(GREY,"for suggestions")) if allow_skip else ""
    prompt_str = (
        "  " + c(CYAN,"[") + c(BOLD+CYAN," >> ") + c(CYAN,"]") +
        "  " + c(WHITE,"Pick room") + " (1-"+str(len(rooms))+")" + skip_hint +
        "  " + c(MAGENTA,"›") + " "
    )
    while True:
        try:
            idx = int(_safe_input(prompt_str).strip())
            if allow_skip and idx == 0:
                return None
            if 1 <= idx <= len(rooms):
                return rooms[idx-1]
        except ValueError:
            pass
        err("Enter a number between " + ("0" if allow_skip else "1") + " and " + str(len(rooms)) + ".")