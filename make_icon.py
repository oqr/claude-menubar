#!/usr/bin/env python3
"""Generate menu bar icon and app icon for Claude Usage.

App icon: macOS-style squircle with a refined gauge, gradient fill,
tick marks, needle, and Claude sparkle center.
Menu bar: crisp monochrome gauge at 22pt.
"""

import math
from PIL import Image, ImageDraw, ImageFilter, ImageFont


# ── Helpers ──────────────────────────────────────────────────────────

def lerp_color(c1, c2, t):
    """Linear interpolate between two RGBA colors."""
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def draw_thick_arc(draw, cx, cy, radius, thickness, start_deg, end_deg,
                   color, steps=200):
    """Draw an anti-aliased thick arc as a filled polygon."""
    r_in = radius - thickness / 2
    r_out = radius + thickness / 2
    pts = []
    for i in range(steps + 1):
        a = math.radians(start_deg + (end_deg - start_deg) * i / steps)
        pts.append((cx + r_out * math.cos(a), cy + r_out * math.sin(a)))
    for i in range(steps, -1, -1):
        a = math.radians(start_deg + (end_deg - start_deg) * i / steps)
        pts.append((cx + r_in * math.cos(a), cy + r_in * math.sin(a)))
    draw.polygon(pts, fill=color)


def draw_gradient_arc(draw, cx, cy, radius, thickness, start_deg, end_deg,
                      color_start, color_end, segments=60):
    """Draw a thick arc with a color gradient along its length."""
    for i in range(segments):
        t0 = i / segments
        t1 = (i + 1) / segments
        a0 = start_deg + (end_deg - start_deg) * t0
        a1 = start_deg + (end_deg - start_deg) * t1
        color = lerp_color(color_start, color_end, t0)
        draw_thick_arc(draw, cx, cy, radius, thickness, a0, a1 + 0.5,
                       color, steps=8)


def draw_squircle(draw, x0, y0, x1, y1, color, n=5):
    """Draw a superellipse (squircle) approximation."""
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    rx = (x1 - x0) / 2
    ry = (y1 - y0) / 2
    pts = []
    steps = 360
    for i in range(steps):
        t = 2 * math.pi * i / steps
        cos_t = math.cos(t)
        sin_t = math.sin(t)
        x = cx + rx * abs(cos_t) ** (2/n) * (1 if cos_t >= 0 else -1)
        y = cy + ry * abs(sin_t) ** (2/n) * (1 if sin_t >= 0 else -1)
        pts.append((x, y))
    draw.polygon(pts, fill=color)


def draw_sparkle(draw, cx, cy, size, color):
    """Draw Claude's 4-point sparkle/star mark."""
    # Four elongated diamond points
    pts = [
        # Top point (tall)
        (cx, cy - size),
        (cx + size * 0.18, cy - size * 0.18),
        # Right point (wide)
        (cx + size * 0.65, cy),
        (cx + size * 0.18, cy + size * 0.18),
        # Bottom point (tall)
        (cx, cy + size),
        (cx - size * 0.18, cy + size * 0.18),
        # Left point (wide)
        (cx - size * 0.65, cy),
        (cx - size * 0.18, cy - size * 0.18),
    ]
    draw.polygon(pts, fill=color)


# ── Colors ───────────────────────────────────────────────────────────

# Claude's warm palette
CLAUDE_PEACH = (217, 119, 68, 255)      # warm terracotta/orange
CLAUDE_CREAM = (245, 225, 200, 255)     # light warm cream
BG_DARK = (24, 24, 28, 255)             # near-black
BG_MID = (36, 36, 42, 255)              # slightly lighter
TRACK_DIM = (55, 55, 65, 255)           # unfilled gauge track
WHITE_BRIGHT = (255, 255, 255, 240)
WHITE_DIM = (255, 255, 255, 60)
GLOW_COLOR = (217, 119, 68, 40)         # subtle warm glow


# ── App Icon (512x512) ──────────────────────────────────────────────

def make_app_icon(output_path, sz=512):
    # Render at 2x for anti-aliasing, then downscale
    S = sz * 2
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = S // 2, S // 2
    margin = int(S * 0.02)

    # Background squircle
    draw_squircle(draw, margin, margin, S - margin, S - margin, BG_DARK)

    # Subtle inner squircle for depth
    m2 = int(S * 0.04)
    draw_squircle(draw, m2, m2, S - m2, S - m2, BG_MID)
    m3 = int(S * 0.06)
    draw_squircle(draw, m3, m3, S - m3, S - m3, BG_DARK)

    # Gauge parameters
    gauge_cy = cy + int(S * 0.02)  # shift gauge down slightly
    gauge_r = int(S * 0.33)
    gauge_thick = int(S * 0.045)
    start_ang = 220
    end_ang = 320
    sweep = end_ang - start_ang

    # Gauge track (dim)
    draw_thick_arc(draw, cx, gauge_cy, gauge_r, gauge_thick,
                   start_ang, end_ang, TRACK_DIM)

    # Gauge fill (gradient: warm peach to cream, ~55% filled)
    fill_pct = 0.55
    fill_end = start_ang + sweep * fill_pct
    draw_gradient_arc(draw, cx, gauge_cy, gauge_r, gauge_thick - 4,
                      start_ang, fill_end, CLAUDE_PEACH, CLAUDE_CREAM,
                      segments=50)

    # Tick marks around the gauge
    num_ticks = 11
    tick_r_out = gauge_r + gauge_thick // 2 + int(S * 0.025)
    tick_r_in = gauge_r + gauge_thick // 2 + int(S * 0.008)
    for i in range(num_ticks):
        t = i / (num_ticks - 1)
        ang = math.radians(start_ang + sweep * t)
        x1 = cx + tick_r_in * math.cos(ang)
        y1 = gauge_cy + tick_r_in * math.sin(ang)
        x2 = cx + tick_r_out * math.cos(ang)
        y2 = gauge_cy + tick_r_out * math.sin(ang)
        # Major ticks at 0%, 50%, 100%
        if i in (0, num_ticks // 2, num_ticks - 1):
            tick_color = (255, 255, 255, 160)
            tick_w = 4
        else:
            tick_color = (255, 255, 255, 60)
            tick_w = 2
        draw.line([(x1, y1), (x2, y2)], fill=tick_color, width=tick_w)

    # Needle indicator at fill point
    needle_ang = math.radians(fill_end)
    needle_r_in = gauge_r - gauge_thick
    needle_r_out = gauge_r + gauge_thick // 2 + int(S * 0.01)
    nx1 = cx + needle_r_in * math.cos(needle_ang)
    ny1 = gauge_cy + needle_r_in * math.sin(needle_ang)
    nx2 = cx + needle_r_out * math.cos(needle_ang)
    ny2 = gauge_cy + needle_r_out * math.sin(needle_ang)
    draw.line([(nx1, ny1), (nx2, ny2)], fill=WHITE_BRIGHT, width=5)

    # Small dot at needle tip
    dot_r = 6
    draw.ellipse([nx2 - dot_r, ny2 - dot_r, nx2 + dot_r, ny2 + dot_r],
                 fill=WHITE_BRIGHT)

    # Center sparkle (Claude mark)
    sparkle_size = int(S * 0.10)
    draw_sparkle(draw, cx, gauge_cy + int(S * 0.01), sparkle_size,
                 WHITE_BRIGHT)

    # Subtle percentage text below gauge
    # (skip if no font available -- the sparkle is the focal point)

    # Subtle glow behind the filled arc
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    draw_thick_arc(glow_draw, cx, gauge_cy, gauge_r, gauge_thick * 3,
                   start_ang, fill_end, GLOW_COLOR, steps=100)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=30))
    img = Image.alpha_composite(glow, img)

    # Downscale with high-quality resampling
    img = img.resize((sz, sz), Image.LANCZOS)
    img.save(output_path)
    print(f"Saved: {output_path} ({sz}x{sz})")


# ── Menu Bar Template Icon ──────────────────────────────────────────

def make_template_icon(output_path, size=44):
    """Monochrome template icon for macOS menu bar (2x retina)."""
    S = size * 2  # render at 4x, downscale
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = S // 2, S // 2 + 1
    gauge_r = int(S * 0.34)
    gauge_thick = int(S * 0.08)
    start_ang = 220
    end_ang = 320
    BLACK = (0, 0, 0, 255)

    # Full gauge arc
    draw_thick_arc(draw, cx, cy, gauge_r, gauge_thick,
                   start_ang, end_ang, BLACK)

    # Tick marks (just endpoints and midpoint)
    for t in [0, 0.5, 1.0]:
        ang = math.radians(start_ang + (end_ang - start_ang) * t)
        tr_in = gauge_r + gauge_thick // 2 + 2
        tr_out = gauge_r + gauge_thick // 2 + int(S * 0.06)
        x1 = cx + tr_in * math.cos(ang)
        y1 = cy + tr_in * math.sin(ang)
        x2 = cx + tr_out * math.cos(ang)
        y2 = cy + tr_out * math.sin(ang)
        draw.line([(x1, y1), (x2, y2)], fill=BLACK, width=3)

    # Center sparkle
    sparkle_sz = int(S * 0.12)
    draw_sparkle(draw, cx, cy + 2, sparkle_sz, BLACK)

    # Downscale
    img = img.resize((size, size), Image.LANCZOS)
    img.save(output_path)
    print(f"Saved: {output_path} ({size}x{size})")


# ── Main ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Menu bar icons
    make_template_icon("icon_template@2x.png", size=44)

    img2x = Image.open("icon_template@2x.png")
    img1x = img2x.resize((22, 22), Image.LANCZOS)
    img1x.save("icon_template.png")
    print("Saved: icon_template.png (22x22)")

    # App icon
    make_app_icon("icon_app_512.png", sz=512)

    # Also generate 1024 for .icns if needed
    make_app_icon("icon_app_1024.png", sz=1024)

    print("Done.")
