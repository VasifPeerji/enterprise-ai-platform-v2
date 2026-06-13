"""
Brand-palette extraction + bot-theme derivation for AutoPilot.

Given a screenshot of a company's website, pull a small dominant-colour palette
(Pillow + KMeans) and turn it into a coherent, *readable* :class:`BotTheme`:

* a brand **primary** with enough contrast that white header text stays legible
  (darkened automatically if the brand colour is too light),
* a complementary **accent**,
* a **surface/text** pair that follows the site's light/dark feel, and
* a matching **visitor bubble** (the assistant bubble is left on its adaptive
  default so it reads well in both modes).

The site's ``<meta name="theme-color">`` (when present) is treated as a strong
primary hint — it is the brand's own declared colour.

Pure and dependency-only-on-already-installed libs (Pillow / numpy / scikit-learn),
so it is unit-testable without a browser or a network call.
"""

from __future__ import annotations

import colorsys
import io
import re
from typing import Optional

import numpy as np
from PIL import Image

_DEFAULT_PRIMARY = "#4f46e5"

# ---------------------------------------------------------------------------
# Colour math
# ---------------------------------------------------------------------------

RGB = tuple[int, int, int]


def _clamp8(v: float) -> int:
    return max(0, min(255, int(round(v))))


def to_hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(_clamp8(rgb[0]), _clamp8(rgb[1]), _clamp8(rgb[2]))


def parse_color(value: str) -> Optional[RGB]:
    """Parse ``#rgb`` / ``#rrggbb`` / ``rgb(...)`` / ``rgba(...)`` -> (r,g,b)."""
    if not value:
        return None
    s = value.strip().lower()
    m = re.fullmatch(r"#([0-9a-f]{3})", s)
    if m:
        h = m.group(1)
        return (int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16))
    m = re.fullmatch(r"#([0-9a-f]{6})", s)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = re.fullmatch(r"rgba?\(\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})\s*(?:,\s*[0-9.]+\s*)?\)", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _srgb_channel(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: RGB) -> float:
    r, g, b = (_srgb_channel(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: RGB, b: RGB) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def saturation(rgb: RGB) -> float:
    h, s, v = colorsys.rgb_to_hsv(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)
    return s


def _hue(rgb: RGB) -> float:
    h, s, v = colorsys.rgb_to_hsv(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)
    return h


def _mix(rgb: RGB, target: RGB, t: float) -> RGB:
    return tuple(_clamp8(rgb[i] + (target[i] - rgb[i]) * t) for i in range(3))  # type: ignore[return-value]


def darken_for_white_text(rgb: RGB, *, min_ratio: float = 4.0) -> RGB:
    """Darken toward black until white text clears ``min_ratio`` contrast.

    The widget header always renders white text on the primary, so a pale brand
    colour (think bright yellow/cyan) would be unreadable. We nudge it darker in
    small steps rather than replacing it, preserving the hue.
    """
    white = (255, 255, 255)
    out = rgb
    for _ in range(20):
        if contrast_ratio(out, white) >= min_ratio:
            break
        out = _mix(out, (0, 0, 0), 0.1)
    return out


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------


def extract_palette(png_bytes: bytes, *, k: int = 6) -> list[tuple[RGB, float]]:
    """Return up to ``k`` dominant colours as ``(rgb, weight)``, weight-sorted."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    # Shrink for speed; aspect-preserving thumbnail caps both dims.
    img.thumbnail((200, 200))
    arr = np.asarray(img, dtype=np.float64).reshape(-1, 3)
    if arr.shape[0] == 0:
        return [((79, 70, 229), 1.0)]

    from sklearn.cluster import KMeans

    n = int(min(k, max(1, len(np.unique(arr, axis=0)))))
    km = KMeans(n_clusters=n, n_init=4, random_state=0)
    labels = km.fit_predict(arr)
    centers = km.cluster_centers_
    total = len(labels)
    out: list[tuple[RGB, float]] = []
    for i, c in enumerate(centers):
        weight = float(np.count_nonzero(labels == i)) / total
        out.append(((_clamp8(c[0]), _clamp8(c[1]), _clamp8(c[2])), weight))
    out.sort(key=lambda t: t[1], reverse=True)
    return out


def _is_brandish(rgb: RGB) -> bool:
    """A colour that could plausibly be a brand colour (vivid, mid-toned)."""
    lum = relative_luminance(rgb)
    return saturation(rgb) >= 0.22 and 0.04 <= lum <= 0.8


def pick_brand_color(palette: list[tuple[RGB, float]], hint: Optional[RGB]) -> RGB:
    # The site's declared theme-color wins if it is an actual colour (not near
    # white/black), since it is the brand's own choice.
    if hint is not None and saturation(hint) >= 0.12 and 0.02 <= relative_luminance(hint) <= 0.9:
        return hint
    candidates = [(rgb, w) for rgb, w in palette if _is_brandish(rgb)]
    if candidates:
        # Favour vivid + well-represented colours.
        candidates.sort(key=lambda t: saturation(t[0]) * (t[1] ** 0.5), reverse=True)
        return candidates[0][0]
    # Nothing vivid: take the most saturated palette colour, else the default.
    if palette:
        best = max(palette, key=lambda t: saturation(t[0]))
        if saturation(best[0]) > 0.05:
            return best[0]
    return parse_color(_DEFAULT_PRIMARY)  # type: ignore[return-value]


def _pick_accent(palette: list[tuple[RGB, float]], primary: RGB) -> RGB:
    """A second vivid colour with a different hue from the primary, else a
    lighter sibling of the primary."""
    ph = _hue(primary)
    best: Optional[RGB] = None
    best_score = 0.0
    for rgb, w in palette:
        if not _is_brandish(rgb):
            continue
        hue_gap = abs(_hue(rgb) - ph)
        hue_gap = min(hue_gap, 1.0 - hue_gap)  # circular
        if hue_gap < 0.06:  # too close to primary
            continue
        score = saturation(rgb) * (0.5 + hue_gap) * (w ** 0.3)
        if score > best_score:
            best_score, best = score, rgb
    if best is not None:
        return best
    # Derive a brighter accent from the primary so links/chips pop on white.
    return _mix(primary, (255, 255, 255), 0.18)


def _is_dark_site(palette: list[tuple[RGB, float]]) -> bool:
    """Treat the site as dark when its dominant (most-area) colour is dark."""
    if not palette:
        return False
    dominant = max(palette, key=lambda t: t[1])[0]
    return relative_luminance(dominant) < 0.2


def derive_bot_theme(png_bytes: bytes, *, theme_color_meta: str = "") -> dict:
    """Turn a screenshot (+ optional theme-color meta) into BotTheme kwargs."""
    palette = extract_palette(png_bytes)
    hint = parse_color(theme_color_meta) if theme_color_meta else None

    primary = darken_for_white_text(pick_brand_color(palette, hint))
    accent = _pick_accent(palette, primary)
    dark = _is_dark_site(palette)

    return {
        "primary_color": to_hex(primary),
        "accent_color": to_hex(accent),
        "surface_color": "#0f172a" if dark else "#ffffff",
        "text_color": "#e5e7eb" if dark else "#1f2937",
        "user_bubble_color": to_hex(primary),
        "bot_bubble_color": None,  # keep the adaptive light/dark default
        "corner_radius_px": 18,
        "dark_mode": dark,
        # Surfaced for the UI / debugging; not a BotTheme field.
        "_palette": [to_hex(rgb) for rgb, _ in palette],
    }
