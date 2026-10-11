#!/usr/bin/env python3
"""
Infoscreen for Waveshare 3.5" LCD  —  redesigned layout v2
480x320 landscape.

Layout (top → bottom):
  Top bar:   gradient progress pill | "WED 3 · JUNE 2026  ·  MEP $1180"
  Weekbar:   MON 20 | TUE 21 | *WED 22* | ... (7 cards)
  Big clock: 22:08 (blinking colon) + TEMP stacked right
  Bottom:    [Alberta]  [Unified panel: overdue tasks + today tasks + today events]
             [Belgrade]

service: systemctl --user restart infoscreen.service
"""

from PIL import Image, ImageDraw, ImageFont
from spotify_now_playing import SpotifyNowPlaying

import datetime
import time
import os
import calendar
import requests
from dotenv import load_dotenv
import threading
import struct
import glob
import subprocess
import json
import zoneinfo

load_dotenv()

# ──────────────────────────────────────────────
#  WORLD CLOCKS — two only
# ──────────────────────────────────────────────
WORLD_CLOCKS = [
    {"label": "Alberta",  "tz": "America/Edmonton", "utc": "UTC-6"},
    {"label": "Belgrade", "tz": "Europe/Belgrade",  "utc": "UTC+1"},
]

# ──────────────────────────────────────────────
#  DISPLAY
# ──────────────────────────────────────────────
WIDTH, HEIGHT    = 480, 320
BACKLIGHT_BRIGHT = 1024
BACKLIGHT_DIM    = 30
is_dimmed        = False
dim_lock         = threading.Lock()

# ──────────────────────────────────────────────
#  PALETTE
# ──────────────────────────────────────────────
BG           = (10,  10,  20)
HIGHLIGHT    = (255, 255, 255)
DIM_TEXT     = (160, 160, 185)
CARD_TODAY   = (50,  50,  80)
CARD_OTHER   = (25,  25,  42)
CARD_BORDER  = (80,  80,  120)
CYAN         = (0,   230, 230)
GREEN        = (160, 255, 160)
GRAY         = (170, 170, 190)
RED          = (220, 60,  60)
PURPLE_DARK  = (80,  0,   160)
PURPLE_FILL  = (180, 80,  255)
TIME_COLOR   = (255, 180, 0)
WC_DAY_BG      = (139, 0,   139)
WC_DAY_TEXT    = (255, 255, 255)
WC_DAY_BORDER  = (255, 255, 255)
WC_NIGHT_BG    = (15,  15,  38)
WC_NIGHT_TEXT  = (255, 255, 255)
WC_NIGHT_BORDER= (255, 255, 255)
WC_LABEL_COLOR = (255, 255, 255)
TASKS_BG     = (20,  20,  45)
TASKS_BORDER = (80,  80,  130)
TASK_OVERDUE = (220, 60,  60)
TASK_TODAY   = (0,   230, 230)
TASK_EVENT   = (160, 160, 200)
EVENT_DIVIDER = (60, 60, 100)
EVENT_YELLOW  = (255, 210, 80)

# ──────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────
def set_backlight(value):
    v = int(max(0, min(1024, int(value))))
    try:
        base = "/sys/class/backlight"
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                br = os.path.join(base, name, "brightness")
                mx = os.path.join(base, name, "max_brightness")
                if os.path.exists(br):
                    scaled = v
                    if os.path.exists(mx):
                        try:
                            with open(mx) as f:
                                maxv = int((f.read() or "").strip() or "0")
                            if maxv > 0 and maxv != 1024:
                                scaled = int(round(v / 1024 * maxv))
                        except Exception:
                            pass
                    with open(br, "w") as f:
                        f.write(str(scaled))
                    return True
    except Exception:
        pass
    try:
        duty = int(round(v / 1024 * 1_000_000))
        subprocess.run(["pigs", "hp", "18", "1000", str(duty)],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def find_touch_device():
    candidates = ["/dev/input/event0", "/dev/input/event1", "/dev/input/event2"]
    for device in candidates + glob.glob("/dev/input/event*"):
        if os.path.exists(device):
            try:
                with open(device, "rb"):
                    return device
            except PermissionError:
                print(f"Found {device} but no permission.")
            except Exception:
                pass
    return None


def touch_listener(touch_device):
    global is_dimmed
    if not touch_device or not os.path.exists(touch_device):
        return
    EVENT_FORMAT = "llHHI"
    EVENT_SIZE   = struct.calcsize(EVENT_FORMAT)
    try:
        with open(touch_device, "rb") as dev:
            while True:
                data = dev.read(EVENT_SIZE)
                if len(data) < EVENT_SIZE:
                    continue
                _, _, type_, code, value = struct.unpack(EVENT_FORMAT, data)
                if type_ == 1 and code == 330 and value == 1:
                    with dim_lock:
                        is_dimmed = not is_dimmed
                        set_backlight(BACKLIGHT_DIM if is_dimmed else BACKLIGHT_BRIGHT)
                    time.sleep(0.3)
    except Exception as e:
        print(f"Touch listener error: {e}")


def show_image_on_fb(image, fb_device="/dev/fb1"):
    try:
        if image.mode != "RGB":
            image = image.convert("RGB")
        pixels = image.load()
        buf    = bytearray()
        for y in range(image.height):
            for x in range(image.width):
                r, g, b = pixels[x, y]
                rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                buf.append(rgb565 & 0xFF)
                buf.append((rgb565 >> 8) & 0xFF)
        with open(fb_device, "wb") as fb:
            fb.write(buf)
        return True
    except Exception as e:
        print(f"Error writing to framebuffer: {e}")
        return False


# ──────────────────────────────────────────────
#  FONTS
# ──────────────────────────────────────────────
def load_fonts():
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    ]
    thin_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    ]

    def try_load(path_list, size):
        for p in path_list:
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    return {
        "topbar":      try_load(thin_paths, 21),
        "topbar_mep":  try_load(paths,      21),
        "dow_day":     try_load(paths,      15),
        "dow_date":    try_load(paths,      14),
        "time":        try_load(paths,     108),
        "side_label":  try_load(thin_paths, 13),
        "side_value":  try_load(paths,      40),
        "wc_label":    try_load(paths,      15),
        "wc_time":     try_load(paths,      30),
        "task_title":  try_load(paths,      16),
        "task_label":  try_load(thin_paths, 13),
        "tiny":        try_load(paths, 15), # it was 12 thin
    }


# ──────────────────────────────────────────────
#  TEXT UTILS
# ──────────────────────────────────────────────
def text_size(draw, text, font):
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1], bb


def center_x(draw, text, font, x0, width):
    tw, _, _ = text_size(draw, text, font)
    return x0 + (width - tw) // 2


def center_xy(draw, text, font, cx, cy):
    w, h, bb = text_size(draw, text, font)
    return int(cx - w / 2 - bb[0]), int(cy - h / 2 - bb[1])


def clip_text(draw, text, font, max_w):
    text = (text or "").strip()
    if text_size(draw, text, font)[0] <= max_w:
        return text
    while len(text) > 1:
        text = text[:-1]
        if text_size(draw, text + "…", font)[0] <= max_w:
            return text + "…"
    return text


# ──────────────────────────────────────────────
#  API FETCHERS
# ──────────────────────────────────────────────
API_BASE    = "https://csdemos.com.ar/services"
API_HEADERS = lambda: {"X-API-Key": os.getenv("API_KEY", "")}


def fetch_weather():
    try:
        r = requests.get(f"{API_BASE}/weather/api/weather/temperature",
                         headers=API_HEADERS(), params={"refresh": "true"}, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Weather error: {e}")
        return None


def fetch_dollar_rate():
    try:
        r = requests.get(f"{API_BASE}/dollar/api/dollar/rate",
                         headers=API_HEADERS(),
                         params={"source": "dolarapi", "refresh": "true"}, timeout=5)
        r.raise_for_status()
        return r.json().get("data", {})
    except Exception as e:
        print(f"Dollar error: {e}")
        return None


def fetch_tasks():
    """Fetch all pending tasks from ALL lists (overdue, today, upcoming). Dated only."""
    all_tasks = []
    try:
        r = requests.get(f"{API_BASE}/google-api/api/tasks/lists",
                         headers=API_HEADERS(), timeout=5)
        r.raise_for_status()
        lists = r.json().get("lists", [])
        today = datetime.date.today()
        for lst in lists:
            r2 = requests.get(f"{API_BASE}/google-api/api/tasks",
                              headers=API_HEADERS(),
                              params={"listId": lst["id"], "showCompleted": "false"}, timeout=5)
            if r2.ok:
                tasks = r2.json().get("tasks", [])
                for t in tasks:
                    if not t.get("dueDate"):
                        continue
                    try:
                        due = datetime.date.fromisoformat(t["dueDate"])
                        t["isOverdue"] = due < today
                    except Exception:
                        t["isOverdue"] = False
                    all_tasks.append(t)
        seen, deduped = set(), []
        for t in all_tasks:
            if t["id"] not in seen:
                seen.add(t["id"])
                deduped.append(t)
        # Sort: overdue first, then by due date ascending
        deduped.sort(key=lambda x: (not x.get("isOverdue", False), x.get("dueDate", "")))
        return deduped
    except Exception as e:
        print(f"Tasks error: {e}")
        return None


def fetch_today_events():
    """Fetch today's remaining calendar events (multiple)."""
    try:
        # Try the /today endpoint first (returns list)
        r = requests.get(f"{API_BASE}/google-api/api/calendar/today",
                         headers=API_HEADERS(), timeout=5)
        if r.ok:
            events = r.json().get("events", [])
            if isinstance(events, list):
                return _filter_upcoming(events)

        # Fallback: single /next endpoint, wrap in list
        r = requests.get(f"{API_BASE}/google-api/api/calendar/next",
                         headers=API_HEADERS(), timeout=5)
        r.raise_for_status()
        ev = r.json().get("event")
        if ev:
            return _filter_upcoming([ev])
        return []
    except Exception as e:
        print(f"Calendar error: {e}")
        return []


def _filter_upcoming(events):
    """Keep only today's events that haven't ended yet."""
    now = datetime.datetime.now().astimezone()
    today = now.date()
    result = []
    for ev in events:
        start_raw = ev.get("start", "")
        try:
            if "T" in start_raw:
                dt = datetime.datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                if dt.astimezone().date() == today:
                    result.append(ev)
            else:
                if datetime.date.fromisoformat(start_raw) == today:
                    result.append(ev)
        except Exception:
            pass
    return result


MEP_STATE_FILE = os.path.expanduser("~/.infoscreen_mep.json")


def load_mep_state():
    try:
        with open(MEP_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"last_rate": None}


def save_mep_state(state):
    try:
        with open(MEP_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


# ──────────────────────────────────────────────
#  DRAW: TOP BAR
# ──────────────────────────────────────────────
def draw_top_bar(draw, fonts, now, dollar_data, y):
    BAR_H  = 34
    RADIUS = BAR_H // 2
    PAD_X  = 6

    days_in_month = calendar.monthrange(now.year, now.month)[1]
    progress      = max(0.0, min(1.0, now.day / days_in_month))

    x1, y1 = PAD_X, y
    x2, y2 = WIDTH - PAD_X, y + BAR_H

    draw.rounded_rectangle((x1, y1, x2, y2), radius=RADIUS, fill=PURPLE_DARK)
    fill_w = int((x2 - x1) * progress)
    if fill_w >= RADIUS * 2:
        draw.rounded_rectangle((x1, y1, x1 + fill_w, y2), radius=RADIUS, fill=PURPLE_FILL)
    elif fill_w > 0:
        draw.rectangle((x1, y1, x1 + fill_w, y2), fill=PURPLE_FILL)

    DOW       = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    date_part = f"{DOW[now.weekday()]} {now.day} · {now.strftime('%b %Y').upper()}"
    mep_rate  = dollar_data.get("rate") if dollar_data else None
    mep_part  = f"MEP ${int(round(mep_rate))}" if mep_rate else "MEP ---"
    sep       = "  ·  "

    dw, dh, _ = text_size(draw, date_part, fonts["topbar"])
    sw, _,  _ = text_size(draw, sep,       fonts["topbar"])
    mw, _,  _ = text_size(draw, mep_part,  fonts["topbar_mep"])
    tx = (WIDTH - dw - sw - mw) // 2
    _, lh, lbb = text_size(draw, date_part, fonts["topbar"])
    ty = y1 + (BAR_H - lh) // 2 - lbb[1]

    draw.text((tx,           ty), date_part, font=fonts["topbar"],     fill=HIGHLIGHT)
    draw.text((tx + dw,      ty), sep,       font=fonts["topbar"],     fill=DIM_TEXT)
    draw.text((tx + dw + sw, ty), mep_part,  font=fonts["topbar_mep"], fill=GREEN)
    return y + BAR_H


# ──────────────────────────────────────────────
#  DRAW: WEEKBAR
# ──────────────────────────────────────────────
def draw_dow_cards(draw, fonts, now, y):
    today_wd = now.weekday()
    monday   = now - datetime.timedelta(days=today_wd)
    days     = [monday + datetime.timedelta(days=i) for i in range(7)]

    GAP    = 4
    RADIUS = 6
    card_w = (WIDTH - GAP * 6) // 7
    card_h = 46

    DOW_LABELS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

    x = 0
    for i, day in enumerate(days):
        is_today = (i == today_wd)
        x1, y1   = x, y
        x2, y2   = x + card_w, y + card_h
        bg       = CARD_TODAY if is_today else CARD_OTHER
        border   = (120, 120, 160) if is_today else CARD_BORDER

        draw.rounded_rectangle((x1, y1, x2, y2), radius=RADIUS, fill=bg, outline=border)

        if i < today_wd:
            draw.rectangle((x1 + 3, y2 - 5, x2 - 3, y2 - 2), fill=PURPLE_FILL)

        dow_txt = DOW_LABELS[i]

        if is_today:
            date_txt = str(day.day)
            _, dh_dow,  _ = text_size(draw, dow_txt,  fonts["dow_day"])
            _, dh_date, _ = text_size(draw, date_txt, fonts["dow_date"])
            total_h = dh_dow + 3 + dh_date
            top_y   = y1 + (card_h - total_h) // 2

            dx = center_x(draw, dow_txt, fonts["dow_day"], x1, card_w)
            draw.text((dx, top_y), dow_txt, font=fonts["dow_day"], fill=HIGHLIGHT)
            dx2 = center_x(draw, date_txt, fonts["dow_date"], x1, card_w)
            draw.text((dx2, top_y + dh_dow + 3), date_txt,
                      font=fonts["dow_date"], fill=CYAN)
        else:
            _, dh, _ = text_size(draw, dow_txt, fonts["dow_day"])
            dx = center_x(draw, dow_txt, fonts["dow_day"], x1, card_w)
            draw.text((dx, y1 + (card_h - dh) // 2), dow_txt,
                      font=fonts["dow_day"], fill=HIGHLIGHT)

        x += card_w + GAP

    return y + card_h


# ──────────────────────────────────────────────
#  DRAW: CLOCK + TEMP
# ──────────────────────────────────────────────
def draw_time_with_side_panels(draw, fonts, now, weather_data, y):
    show_colon = (int(time.time()) % 2 == 0)
    time_str   = now.strftime("%H:%M") if show_colon else now.strftime("%H %M")
    tw, time_h, time_bb = text_size(draw, time_str, fonts["time"])
    clock_y = y - time_bb[1] // 2  # subtract half the top bearing

    if weather_data:
        temp  = weather_data.get("temp", "--")
        feel  = weather_data.get("feelslike", "--")
        if str(temp) == str(feel) or feel == "--":
            val_str, val_color = f"{temp}°C", HIGHLIGHT
        else:
            val_str, val_color = f"{feel}°C", CYAN
    else:
        val_str, val_color = "--°C", RED

    lbl      = "TEMP"
    lw_l, lh_l, _ = text_size(draw, lbl,     fonts["side_label"])
    lw_v, lh_v, _ = text_size(draw, val_str, fonts["side_value"])
    block_h   = lh_l + 4 + lh_v
    block_top = y + (time_h - block_h) // 2 + 10

    GAP_MID = 14
    total_w = tw + GAP_MID + max(lw_l, lw_v)
    time_x  = (WIDTH - total_w) // 2
    temp_x  = time_x + tw + GAP_MID

    draw.text((time_x, clock_y), time_str, font=fonts["time"], fill=TIME_COLOR)
    draw.text((temp_x + (max(lw_l, lw_v) - lw_l) // 2, block_top),
              lbl, font=fonts["side_label"], fill=GRAY)
    draw.text((temp_x + (max(lw_l, lw_v) - lw_v) // 2, block_top + lh_l + 4),
              val_str, font=fonts["side_value"], fill=val_color)

    return y + time_h


# ──────────────────────────────────────────────
#  TASK RELATIVE TIME
# ──────────────────────────────────────────────
def relative_task_time(due_date_str):
    """Return a short relative time string for a task due date."""
    try:
        due   = datetime.date.fromisoformat(due_date_str)
        today = datetime.date.today()
        delta = (due - today).days
        if delta < -1:
            return f"{abs(delta)}d overdue"
        elif delta == -1:
            return "yesterday"
        elif delta == 0:
            return "today"
        elif delta == 1:
            return "tomorrow"
        elif delta < 7:
            return due.strftime("%a").lower()
        else:
            return due.strftime("%-d-%b").lower()
    except Exception:
        return ""


def _format_event_time(start_raw):
    """Format a calendar event start into a short time string like '10am' or '2:30pm'."""
    try:
        if "T" in start_raw:
            dt = datetime.datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            local_dt = dt.astimezone()
            h, m = local_dt.hour, local_dt.minute
            ap = "am" if h < 12 else "pm"
            h12 = h % 12 or 12
            return (f"{h12}:{m:02d}{ap}" if m else f"{h12}{ap}"), local_dt
        else:
            return "", None
    except Exception:
        return "", None


# ──────────────────────────────────────────────
#  DRAW: BOTTOM STRIP  (unified tasks + events)
# ──────────────────────────────────────────────
WC_CARD_W = 100

def draw_bottom_strip(draw, fonts, now, tasks_data, events_data, y):
    """Unified list: overdue tasks (red), today tasks (cyan), events (yellow) — sorted."""
    STRIP_H  = HEIGHT - y
    CARD_GAP = 4
    PAD      = 5
    PAD_BOT  = 8
    RADIUS   = 6

    wc_h = (STRIP_H - CARD_GAP) // 2

    # ── World clock cards (left column) ──────────────────────────
    for idx, clock in enumerate(WORLD_CLOCKS):
        try:
            tz       = zoneinfo.ZoneInfo(clock["tz"])
            local_dt = now.astimezone(tz)
        except Exception:
            local_dt = now

        is_night = not (6 <= local_dt.hour < 20)
        bg       = WC_NIGHT_BG if is_night else WC_DAY_BG

        cy1 = y + idx * (wc_h + CARD_GAP)
        cy2 = cy1 + wc_h
        cx  = WC_CARD_W // 2

        draw.rounded_rectangle((0, cy1, WC_CARD_W, cy2),
                                radius=RADIUS, fill=bg, outline=(255, 255, 255))

        lw, lh, _ = text_size(draw, clock["label"], fonts["wc_label"])
        draw.text((cx - lw // 2, cy1 + PAD),
                  clock["label"], font=fonts["wc_label"], fill=(255, 255, 255))

        t_str      = local_dt.strftime("%H:%M")
        tw, th, tbb = text_size(draw, t_str, fonts["wc_time"])
        ty_time    = cy2 - th - PAD_BOT - tbb[1] // 2
        draw.text((cx - tw // 2, ty_time), t_str,
                  font=fonts["wc_time"], fill=(255, 255, 255))

    # ── Tasks panel (right of world clocks) ──────────────────────
    tp_x1 = WC_CARD_W + CARD_GAP
    tp_x2 = WIDTH - 2
    tp_y1 = y
    tp_y2 = HEIGHT - 2
    tp_h  = tp_y2 - tp_y1
    tp_w  = tp_x2 - tp_x1

    draw.rounded_rectangle((tp_x1, tp_y1, tp_x2, tp_y2),
                            radius=RADIUS, fill=TASKS_BG, outline=TASKS_BORDER)

    inner_x  = tp_x1 + PAD + 2
    inner_w  = tp_w - (PAD + 2) * 2
    inner_y1 = tp_y1 + PAD + 2

    task_lh, _, _ = text_size(draw, "Ag", fonts["task_title"])
    task_row_h = task_lh + 3

    # ── Build unified items list ─────────────────────────────────
    # Each item: (sort_key, color, marker, label, rel_str)
    items = []

    if tasks_data:
        for t in tasks_data:
            is_overdue = t.get("isOverdue", False)
            color  = TASK_OVERDUE if is_overdue else TASK_TODAY
            marker = "!  " if is_overdue else "·  "
            title  = (t.get("title") or "").strip()
            rel    = relative_task_time(t.get("dueDate", ""))
            # Overdue = sort group 0, today/future tasks = sort group 1
            sort_key = (0 if is_overdue else 1, t.get("dueDate", ""), "a")
            items.append((sort_key, color, marker, title, rel))

    if events_data:
        now_aware = now.astimezone()
        for ev in (events_data or []):
            start_raw = ev.get("start", "")
            summary   = (ev.get("summary") or "").strip()
            time_str, local_dt = _format_event_time(start_raw)

            # Skip events already past
            if local_dt and local_dt < now_aware:
                continue

            label = f"{time_str}  {summary}" if time_str else summary
            sort_dt = local_dt.isoformat() if local_dt else start_raw
            # Events sort in group 1 alongside today tasks, by start time
            items.append(((1, sort_dt, "b"), EVENT_YELLOW, "▸  ", label, ""))

    items.sort(key=lambda x: x[0])

    # ── Nothing at all ───────────────────────────────────────────
    if not items:
        msg = "All clear ✓"
        mw, mh, _ = text_size(draw, msg, fonts["task_title"])
        tp_mid = tp_y1 + tp_h // 2
        draw.text((inner_x + (inner_w - mw) // 2, tp_mid - mh // 2),
                  msg, font=fonts["task_title"], fill=GREEN)
        return

    # ── Draw rows ────────────────────────────────────────────────
    max_rows = (tp_h - (PAD + 2) * 2) // task_row_h
    line_y   = inner_y1

    for _, color, marker, label, rel_str in items[:max_rows]:
        if rel_str:
            rel_display = f" [{rel_str}]"
            rw, _, _ = text_size(draw, rel_display, fonts["tiny"])
        else:
            rel_display = ""
            rw = 0

        title_max = inner_w - 16 - rw
        title = clip_text(draw, label, fonts["task_title"], title_max)
        draw.text((inner_x,      line_y), marker, font=fonts["task_title"], fill=color)
        draw.text((inner_x + 16, line_y), title,  font=fonts["task_title"], fill=color)

        if rel_display:
            tw_t, _, _ = text_size(draw, title, fonts["task_title"])
            draw.text((inner_x + 16 + tw_t, line_y + 2), rel_display,
                      font=fonts["tiny"], fill=EVENT_YELLOW)

        line_y += task_row_h


# ──────────────────────────────────────────────
#  COMPOSE FRAME
# ──────────────────────────────────────────────
def compose_frame(fonts, weather_data, dollar_data,
                  tasks_data=None, events_data=None,
                  spotify_data=None, spotify_client=None):
    img  = Image.new("RGB", (WIDTH, HEIGHT), color=BG)
    draw = ImageDraw.Draw(img)
    now  = datetime.datetime.now()

    if spotify_data and spotify_client:
        _draw_spotify(draw, img, fonts, spotify_data, spotify_client, now, weather_data)
        return img

    y = 4
    y = draw_top_bar(draw, fonts, now, dollar_data, y)                + 4
    y = draw_dow_cards(draw, fonts, now, y)                           + 0
    y = draw_time_with_side_panels(draw, fonts, now, weather_data, y) + 2

    # Hard floor: bottom strip always gets at least 110px
    y = max(y, HEIGHT - 125)

    draw_bottom_strip(draw, fonts, now, tasks_data, events_data, y)

    return img


# ──────────────────────────────────────────────
#  SPOTIFY OVERLAY  (unchanged)
# ──────────────────────────────────────────────
def _clip(s, n):
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _draw_spotify(draw, img, fonts, data, client, now, weather_data=None):
    PAD   = 8
    COVER = 185
    GAP   = 6

    try:
        f_label  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",      13)
        f_title  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
        f_artist = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        f_meta   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        f_time   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 46)
        f_temp   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
        f_date   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except Exception:
        f_label = f_title = f_artist = f_meta = f_time = f_temp = f_date = fonts["tiny"]

    cover = client.get_cover_image(data.get("cover_url"), size=(COVER, COVER))
    cv_x  = PAD
    cv_y  = PAD
    if cover:
        img.paste(cover, (cv_x, cv_y))
    else:
        draw.rectangle((cv_x, cv_y, cv_x + COVER, cv_y + COVER), outline=GRAY)

    rx  = cv_x + COVER + PAD
    r_w = WIDTH - rx - PAD

    def clip_to_width(s, font, max_w):
        s = (s or "").strip()
        if text_size(draw, s, font)[0] <= max_w:
            return s
        while len(s) > 1:
            s = s[:-1]
            if text_size(draw, s + "…", font)[0] <= max_w:
                return s + "…"
        return s

    def rcline(txt, font, y, color):
        tw, th, _ = text_size(draw, txt, font)
        draw.text((rx + (r_w - tw) // 2, y), txt, font=font, fill=color)
        return y + th

    show_colon = (int(time.time()) % 2 == 0)
    time_str   = now.strftime("%H:%M") if show_colon else now.strftime("%H %M")
    DOW_LABELS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    dow_str    = DOW_LABELS[now.weekday()]
    date_str   = f"{dow_str} {now.day} {now.strftime('%b').upper()}"

    if weather_data:
        temp     = weather_data.get("temp", "--")
        feel     = weather_data.get("feelslike", "--")
        temp_str = (f"{temp}°C" if (str(temp) == str(feel) or feel == "--")
                    else f"{temp}°C ({feel}°)")
    else:
        temp_str = "--°C"

    INFO_GAP   = 12
    info_lines = [
        (time_str, f_time, TIME_COLOR),
        (temp_str, f_temp, HIGHLIGHT),
        (date_str, f_date, HIGHLIGHT),
    ]

    info_h   = sum(text_size(draw, t, f)[1] for t, f, _ in info_lines) + INFO_GAP * (len(info_lines) - 1)
    info_top = cv_y + (COVER - info_h) // 2
    iy = info_top
    for txt, font, color in info_lines:
        iy = rcline(txt, font, iy, color) + INFO_GAP

    y = cv_y + COVER + GAP

    def cline(txt, font, y, color):
        tw, th, _ = text_size(draw, txt, font)
        draw.text(((WIDTH - tw) // 2, y), txt, font=font, fill=color)
        return y + th

    name    = clip_to_width((data.get("name")    or ""), f_title, WIDTH - PAD * 2)
    artists = (data.get("artists") or "").strip()
    album   = (data.get("album")   or "").strip()
    yr      = (data.get("release_date") or "")[:4]

    y = cline(yr if yr else "", f_meta,   y, HIGHLIGHT) + 4
    y = cline(name,             f_title,  y, GREEN)     + GAP
    y = cline(artists,          f_artist, y, CYAN)      + GAP
    y = cline(album,            f_meta,   y, HIGHLIGHT) + 2

    dur  = float(data.get("duration_ms") or 1)
    prog = float(data.get("progress_ms") or 0)
    bx1, bx2 = PAD * 2, WIDTH - PAD * 2
    by        = HEIGHT - PAD - 10
    draw.rectangle((bx1, by, bx2, by + 10), outline=GRAY)
    fw = int((bx2 - bx1) * min(1.0, prog / dur))
    if fw > 0:
        draw.rectangle((bx1, by, bx1 + fw, by + 10), fill=CYAN)


# ──────────────────────────────────────────────
#  MAIN LOOP
# ──────────────────────────────────────────────
def main():
    global is_dimmed

    print(f"Starting Infoscreen  {WIDTH}x{HEIGHT}")
    set_backlight(BACKLIGHT_DIM if is_dimmed else BACKLIGHT_BRIGHT)

    touch_device = find_touch_device()
    if touch_device:
        threading.Thread(target=touch_listener, args=(touch_device,), daemon=True).start()

    api_cache = {
        "dollar":  {"data": None, "last_update": 0},
        "weather": {"data": None, "last_update": 0},
        "spotify": {"data": None, "last_update": 0},
        "tasks":   {"data": None, "last_update": 0},
        "events":  {"data": None, "last_update": 0},
    }

    API_REFRESH_INTERVAL     = 180
    TASKS_REFRESH_INTERVAL   = 60
    EVENT_REFRESH_INTERVAL   = 120
    DISPLAY_REFRESH_INTERVAL = 2
    SPOTIFY_REFRESH_INTERVAL = 5

    fonts = load_fonts()
    load_mep_state()

    spotify = SpotifyNowPlaying(
        os.getenv("SPOTIFY_CLIENT_ID", ""),
        os.getenv("SPOTIFY_CLIENT_SECRET", ""),
        os.getenv("SPOTIFY_REFRESH_TOKEN", ""),
    )

    while True:
        try:
            now_ts = time.time()

            # Spotify
            if now_ts - api_cache["spotify"]["last_update"] > SPOTIFY_REFRESH_INTERVAL:
                api_cache["spotify"]["data"]        = spotify.get_current()
                api_cache["spotify"]["last_update"] = now_ts
                print(f"Spotify: {api_cache['spotify']['data']}")

            # Weather + dollar
            for key, fetcher in [("dollar", fetch_dollar_rate), ("weather", fetch_weather)]:
                if now_ts - api_cache[key]["last_update"] > API_REFRESH_INTERVAL:
                    print(f"Refreshing {key}…")
                    new_data = fetcher()
                    api_cache[key]["data"]        = new_data
                    api_cache[key]["last_update"] = now_ts
                    if key == "dollar" and new_data:
                        new_rate = new_data.get("rate")
                        if new_rate:
                            save_mep_state({"last_rate": new_rate})

            # Tasks
            if now_ts - api_cache["tasks"]["last_update"] > TASKS_REFRESH_INTERVAL:
                print("Refreshing tasks…")
                tasks = fetch_tasks()
                if tasks is not None:
                    api_cache["tasks"]["data"] = tasks
                api_cache["tasks"]["last_update"] = now_ts

            # Calendar events
            if now_ts - api_cache["events"]["last_update"] > EVENT_REFRESH_INTERVAL:
                print("Refreshing events…")
                events = fetch_today_events()
                if events is not None:
                    api_cache["events"]["data"] = events
                api_cache["events"]["last_update"] = now_ts

            if is_dimmed:
                img = Image.new("RGB", (WIDTH, HEIGHT), color=(0, 0, 0))
            else:
                img = compose_frame(
                    fonts,
                    weather_data   = api_cache["weather"]["data"],
                    dollar_data    = api_cache["dollar"]["data"],
                    tasks_data     = api_cache["tasks"]["data"],
                    events_data    = api_cache["events"]["data"],
                    spotify_data   = api_cache["spotify"]["data"],
                    spotify_client = spotify,
                )

            show_image_on_fb(img)
            time.sleep(DISPLAY_REFRESH_INTERVAL)

        except KeyboardInterrupt:
            print("\nStopping…")
            set_backlight(BACKLIGHT_BRIGHT)
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()