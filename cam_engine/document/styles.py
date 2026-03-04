"""
cam_engine/document/styles.py
================================
Centralised design system for the CAM Word document.

All colors, fonts, and sizes are defined here.
CAMBuilder references these constants — never uses magic numbers.
"""

from __future__ import annotations

from docx.shared import Pt, RGBColor, Inches, Cm


# ── Color palette ────────────────────────────────────────────

class Colors:
    PRIMARY    = RGBColor(0x1B, 0x36, 0x5D)   # Deep navy
    SECONDARY  = RGBColor(0x2C, 0x3E, 0x50)   # Charcoal
    WHITE      = RGBColor(0xFF, 0xFF, 0xFF)

    GREEN      = RGBColor(0x27, 0xAE, 0x60)   # Approve
    GREEN_LIGHT= RGBColor(0xD5, 0xF5, 0xE3)   # Green background
    AMBER      = RGBColor(0xE6, 0x7E, 0x22)   # Conditional
    AMBER_LIGHT= RGBColor(0xFD, 0xF2, 0xE9)   # Amber background
    RED        = RGBColor(0xCB, 0x44, 0x35)   # High risk / Reject
    RED_LIGHT  = RGBColor(0xFD, 0xED, 0xEC)   # Red background
    BLACK_RISK = RGBColor(0x17, 0x20, 0x2A)   # Black risk band

    TABLE_HDR  = RGBColor(0x1B, 0x36, 0x5D)   # Navy — table headers
    TABLE_ALT  = RGBColor(0xF4, 0xF6, 0xF7)   # Light grey — alternating rows
    BORDER     = RGBColor(0xCC, 0xD2, 0xD8)   # Table border
    SEPARATOR  = RGBColor(0x21, 0x8B, 0xC4)   # Teal — section decorator

    # Score colors
    SCORE_GREEN = RGBColor(0x1E, 0x8B, 0x4C)
    SCORE_AMBER = RGBColor(0xD4, 0x6F, 0x0D)
    SCORE_RED   = RGBColor(0xAB, 0x2B, 0x1E)


def band_color(band: str) -> RGBColor:
    mapping = {
        "GREEN": Colors.GREEN,
        "AMBER": Colors.AMBER,
        "RED":   Colors.RED,
        "BLACK": Colors.BLACK_RISK,
    }
    return mapping.get(band.upper(), Colors.SECONDARY)


def band_light_color(band: str) -> RGBColor:
    mapping = {
        "GREEN": Colors.GREEN_LIGHT,
        "AMBER": Colors.AMBER_LIGHT,
        "RED":   Colors.RED_LIGHT,
        "BLACK": Colors.RED_LIGHT,
    }
    return mapping.get(band.upper(), Colors.TABLE_ALT)


def score_color(score: int) -> RGBColor:
    if score >= 70: return Colors.SCORE_GREEN
    if score >= 50: return Colors.SCORE_AMBER
    return Colors.SCORE_RED


# ── Typography ───────────────────────────────────────────────

class Fonts:
    MAIN   = "Calibri"
    MONO   = "Courier New"

FONT_SIZES = {
    "bank_name":   28,
    "cam_title":   18,
    "h1":          14,
    "h2":          12,
    "h3":          11,
    "body":        10,
    "small":        9,
    "caption":      8,
}

# ── Page layout ──────────────────────────────────────────────

PAGE_MARGIN = Cm(2.0)
TABLE_WIDTH = Inches(6.3)
