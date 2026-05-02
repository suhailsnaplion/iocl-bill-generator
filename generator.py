"""
IOCL Bill Generator – core generation logic.

Bill layout dimensions match the original scanned A4 receipt:
  Image canvas : 1239 × 1754 px  (~150 DPI A4)
  Font         : Courier New Bold (monospace) – same look as dot-matrix/thermal print
"""

import io
import os
import random
from datetime import timedelta

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ── paths ──────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH      = os.path.join(_HERE, "assets", "logo.png")
FONT_BOLD_PATH = "/System/Library/Fonts/Supplemental/Courier New Bold.ttf"
FONT_REG_PATH  = "/System/Library/Fonts/Supplemental/Courier New.ttf"

# ── canvas constants ───────────────────────────────────────────────────────────
IMG_W        = 1239
IMG_H        = 1754
FONT_SIZE    = 40          # px  (PIL truetype size is in pixels)
X_LEFT       = 130         # left margin for all text
Y_LOGO_TOP   = 30
LOGO_TGT_H   = 710         # logo section height (matches original proportions)
Y_ADDR_TOP   = 830         # address block start
ADDR_LINE_H  = 55          # px between address lines
FIELD_LINE_H = 64          # px between bill field rows
TEXT_COLOR   = (10, 10, 10)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_fonts():
    fb = ImageFont.truetype(FONT_BOLD_PATH, FONT_SIZE)
    fr = ImageFont.truetype(FONT_REG_PATH,  FONT_SIZE)
    return fb, fr


def _fmt(label: str, value: str) -> str:
    """Format a bill field row with fixed-width label, colon and value.
    Courier is monospace so ljust gives perfect column alignment."""
    return f"{label:<10} : {value}"


# ─────────────────────────────────────────────────────────────────────────────
# Amount splitting
# ─────────────────────────────────────────────────────────────────────────────

def split_amount(total: float, n: int, rate: float, max_volume: float) -> list[float]:
    """
    Split *total* into exactly *n* sale amounts where:
      • each sale ≤  max_volume × rate
      • each sale ≥  rate × 5  (minimum ~5 litres)
      • sum of all sales == total  (to the nearest paisa)

    Uses a sequential budgeting approach so variation is natural even when
    the total is close to the theoretical maximum.
    """
    max_sale = round(max_volume * rate, 2)
    min_sale = round(rate * 5.0, 2)      # at least 5 litres worth

    # Guard: if floor-based minimum is too high, relax it
    if min_sale * n > total:
        min_sale = round(total / n * 0.5, 2)

    parts     = []
    remaining = round(total, 2)

    for i in range(n - 1):
        left = n - i               # bills still to fill (including this one)

        # Bounds for this bill
        hi = min(max_sale, round(remaining - min_sale * (left - 1), 2))
        lo = max(min_sale, round(remaining - max_sale * (left - 1), 2))

        if lo > hi:
            lo = hi

        amount = round(random.uniform(lo, hi), 2)
        parts.append(amount)
        remaining = round(remaining - amount, 2)

    parts.append(round(remaining, 2))  # last bill absorbs rounding residual
    return parts


# ─────────────────────────────────────────────────────────────────────────────
# Date / time generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_dates_times(start_date, end_date, n: int) -> list:
    """Return *n* unique (date, hour, minute) tuples within [start_date, end_date],
    sorted chronologically.  Petrol stations operate 06:00–21:00."""
    span = (end_date - start_date).days + 1
    used = set()
    result = []
    for _ in range(20_000):
        if len(result) == n:
            break
        dt     = start_date + timedelta(days=random.randint(0, span - 1))
        hour   = random.randint(6, 21)
        minute = random.randint(0, 59)
        key    = (dt, hour, minute)
        if key not in used:
            used.add(key)
            result.append(key)
    result.sort()
    return result


def make_bill_no(dt, hour: int, minute: int) -> str:
    """Bill number = DDMMYY + HHMM  (matches sample: 2504261407)."""
    yy = str(dt.year)[2:]
    return f"{dt.day:02d}{dt.month:02d}{yy}{hour:02d}{minute:02d}"


# ─────────────────────────────────────────────────────────────────────────────
# Single-bill image renderer
# ─────────────────────────────────────────────────────────────────────────────

def render_bill(
    address:    str,
    bill_no:    str,
    vehicle_no: str,
    date_str:   str,
    time_str:   str,
    fuel:       str,
    rate:       float,
    sale:       float,
    volume:     float,
    total:      float,
) -> Image.Image:
    """Return a PIL RGB image of one bill that looks like a scanned A4 receipt."""

    img  = Image.new("RGB", (IMG_W, IMG_H), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    fb, fr = _load_fonts()

    # ── Logo ──────────────────────────────────────────────────────────────────
    logo     = Image.open(LOGO_PATH).convert("L").convert("RGB")
    lw, lh   = logo.size
    scale    = LOGO_TGT_H / lh
    tgt_w    = int(lw * scale)
    logo     = logo.resize((tgt_w, LOGO_TGT_H), Image.LANCZOS)
    x_logo   = (IMG_W - tgt_w) // 2
    img.paste(logo, (x_logo, Y_LOGO_TOP))

    # ── Address ───────────────────────────────────────────────────────────────
    y_cur = Y_ADDR_TOP
    for line in address.strip().split("\n"):
        draw.text((X_LEFT, y_cur), line.strip(), font=fb, fill=TEXT_COLOR)
        y_cur += ADDR_LINE_H

    # ── Fields ────────────────────────────────────────────────────────────────
    # Always start fields at a fixed position so the layout looks consistent,
    # regardless of address length (extra gap is intentional whitespace).
    y_fields = max(y_cur + 50, 1045)

    rows = [
        _fmt("Bill No",    bill_no),
        _fmt("Vehicle No", vehicle_no),
        _fmt("Date",       date_str),
        _fmt("Time",       time_str),
        _fmt("Fuel",       fuel),
        _fmt("Rate",       f"Rs. {rate:.2f}"),
        _fmt("Sale",       f"Rs. {sale:.2f}"),
        _fmt("Volume",     f"{volume:.2f} Ltr"),
        _fmt("Total",      f"Rs. {total:.2f}"),
    ]

    y_cur = y_fields
    for row in rows:
        draw.text((X_LEFT, y_cur), row, font=fb, fill=TEXT_COLOR)
        y_cur += FIELD_LINE_H

    # ── Thank You ─────────────────────────────────────────────────────────────
    y_cur += 28
    ty_text = "Thank You! Visit Again"
    bbox    = draw.textbbox((0, 0), ty_text, font=fr)
    ty_w    = bbox[2] - bbox[0]
    draw.text(((IMG_W - ty_w) // 2, y_cur), ty_text, font=fr, fill=TEXT_COLOR)

    # ── Bottom rule ───────────────────────────────────────────────────────────
    y_line = y_cur + 65
    draw.rectangle([(70, y_line), (IMG_W - 70, y_line + 14)], fill=TEXT_COLOR)

    # ── Scan effect ───────────────────────────────────────────────────────────
    img = _scan_effect(img)
    return img


def _scan_effect(img: Image.Image) -> Image.Image:
    """Add subtle scan artefacts: slight warmth, random noise, mild blur."""
    arr = np.array(img, dtype=np.float32)

    # Aged-paper warmth (very slight)
    arr[:, :, 0] = np.clip(arr[:, :, 0] + 2.5, 0, 255)   # red up
    arr[:, :, 2] = np.clip(arr[:, :, 2] - 3.0, 0, 255)   # blue down

    # Scanner noise
    noise = np.random.normal(0, 2.8, arr.shape)
    arr   = np.clip(arr + noise, 0, 255).astype(np.uint8)

    img = Image.fromarray(arr)
    img = img.filter(ImageFilter.GaussianBlur(radius=0.35))  # glass blur
    return img


# ─────────────────────────────────────────────────────────────────────────────
# Multi-bill PDF assembler
# ─────────────────────────────────────────────────────────────────────────────

def generate_bills_pdf(
    address:      str,
    vehicle_no:   str,
    start_date,
    end_date,
    fuel:         str,
    rate:         float,
    total_amount: float,
    max_volume:   float,
    output_path:  str,
    num_bills:    int = 0,   # 0 = random 7-8
) -> list[dict]:
    """
    Generate *num_bills* (or 7–8 random) Indian Oil bills and write them
    to a multi-page PDF at *output_path*.

    Returns a list of dicts with keys:
        bill_no, date, time, sale, volume
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas

    n      = num_bills if num_bills >= 2 else random.randint(7, 8)
    sales  = split_amount(total_amount, n, rate, max_volume)
    dtimes = generate_dates_times(start_date, end_date, n)

    A4_W, A4_H = A4   # 595 × 842 pt

    c      = rl_canvas.Canvas(output_path, pagesize=A4)
    bills  = []

    for (dt, hour, minute), sale in zip(dtimes, sales):
        volume  = round(sale / rate, 2)
        bill_no = make_bill_no(dt, hour, minute)

        pil_img = render_bill(
            address    = address,
            bill_no    = bill_no,
            vehicle_no = vehicle_no,
            date_str   = dt.strftime("%d/%m/%Y"),
            time_str   = f"{hour:02d}:{minute:02d}",
            fuel       = fuel,
            rate       = rate,
            sale       = sale,
            volume     = volume,
            total      = sale,
        )

        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=92)
        buf.seek(0)

        c.drawImage(ImageReader(buf), 0, 0, width=A4_W, height=A4_H)
        c.showPage()

        bills.append(
            dict(bill_no=bill_no,
                 date=dt.strftime("%d/%m/%Y"),
                 time=f"{hour:02d}:{minute:02d}",
                 sale=round(sale, 2),
                 volume=volume)
        )

    c.save()
    return bills
