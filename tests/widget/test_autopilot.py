"""
Torch-free unit tests for AutoPilot's pure pieces: brand-palette → theme
derivation and the orchestrator's URL/SSRF/parse helpers.

The Playwright renderer and the router→LLM autofill are intentionally NOT
exercised here (they need a browser / a model); they are validated live. These
tests guard the deterministic logic that turns a screenshot + page text into a
coherent, readable bot draft.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from src.layer4_platform import autopilot as ap
from src.layer4_platform import theme_extractor as tx


def _png(color, size=(80, 80)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _png_brand_on_white(brand, size=(80, 80)) -> bytes:
    """A mostly-white canvas with a brand-colored band (a realistic 'light site')."""
    img = Image.new("RGB", size, (255, 255, 255))
    img.paste(Image.new("RGB", (size[0], size[1] // 4), brand), (0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class TestColorMath:
    def test_parse_color_variants(self):
        assert tx.parse_color("#abc") == (170, 187, 204)
        assert tx.parse_color("#4f46e5") == (79, 70, 229)
        assert tx.parse_color("rgb(10, 20, 30)") == (10, 20, 30)
        assert tx.parse_color("rgba(10,20,30,0.5)") == (10, 20, 30)
        assert tx.parse_color("not-a-color") is None
        assert tx.parse_color("") is None

    def test_darken_for_white_text_improves_contrast(self):
        white = (255, 255, 255)
        yellow = (255, 221, 0)  # poor contrast against white
        assert tx.contrast_ratio(yellow, white) < 4.0
        fixed = tx.darken_for_white_text(yellow, min_ratio=4.0)
        assert tx.contrast_ratio(fixed, white) >= 4.0


class TestThemeDerivation:
    def test_brand_on_white_is_light_and_readable(self):
        theme = tx.derive_bot_theme(_png_brand_on_white((45, 88, 123)))
        assert theme["dark_mode"] is False
        assert theme["surface_color"] == "#ffffff"
        assert theme["bot_bubble_color"] is None  # stays adaptive
        # header uses white text on the primary -> must clear AA-ish contrast
        primary = tx.parse_color(theme["primary_color"])
        assert tx.contrast_ratio(primary, (255, 255, 255)) >= 3.0

    def test_theme_color_meta_is_honored(self):
        # A flat gray screenshot, but the site declares a green brand color.
        theme = tx.derive_bot_theme(_png((200, 200, 200)), theme_color_meta="#0a7d55")
        primary = tx.parse_color(theme["primary_color"])
        assert primary is not None
        assert primary[1] >= primary[0] and primary[1] >= primary[2]  # greenish

    def test_dark_site_detection(self):
        theme = tx.derive_bot_theme(_png((12, 14, 20)))
        assert theme["dark_mode"] is True
        assert theme["surface_color"] == "#0f172a"
        assert theme["text_color"] == "#e5e7eb"


class TestUrlAndSsrf:
    def test_normalize_url_adds_scheme(self):
        assert ap.normalize_url("acme.com") == "https://acme.com"
        assert ap.normalize_url("  http://x.io/a  ") == "http://x.io/a"

    def test_normalize_url_rejects_garbage(self):
        with pytest.raises(ap.AutopilotError):
            ap.normalize_url("")
        with pytest.raises(ap.AutopilotError):
            ap.normalize_url("https://")  # no host

    def test_registrable_slug(self):
        assert ap._registrable_slug("https://www.Acme-Corp.com") == "acme-corp"
        assert ap._registrable_slug("https://shop.example.co.uk") == "shop"

    def test_guard_blocks_private_hosts(self):
        with pytest.raises(ap.AutopilotError):
            ap.guard_public_url("http://localhost")
        with pytest.raises(ap.AutopilotError):
            ap.guard_public_url("http://127.0.0.1:8000")


class TestAutofillParsing:
    def test_parse_autofill_json_extracts_and_validates(self):
        good = (
            '{"display_name":"Acme Assistant","greeting":"Hi!","subtitle":"Ask us",'
            '"suggested_prompts":[{"label":"P","prompt":"price?"}]}'
        )
        out = ap._parse_autofill_json("noise before " + good + " trailing")
        assert out is not None
        assert out["display_name"] == "Acme Assistant"
        assert out["suggested_prompts"][0] == {"label": "P", "prompt": "price?"}

    def test_parse_autofill_json_rejects_bad(self):
        assert ap._parse_autofill_json("not json at all") is None
        assert ap._parse_autofill_json('{"greeting":"hi"}') is None  # missing display_name

    def test_coerce_prompts_handles_mixed_shapes(self):
        out = ap._coerce_prompts([{"label": "A", "prompt": "qa"}, "plain", {"prompt": "only"}])
        assert out[0] == {"label": "A", "prompt": "qa"}
        assert out[1] == {"label": "plain", "prompt": "plain"}
        assert out[2] == {"label": "only", "prompt": "only"}

    def test_heuristic_copy_is_complete(self):
        copy = ap._heuristic_copy("Acme")
        assert copy["display_name"] == "Acme Assistant"
        assert copy["greeting"] and copy["subtitle"]
        assert len(copy["suggested_prompts"]) == 4
