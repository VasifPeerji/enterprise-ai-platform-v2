"""Security-critical tests for the per-company bot registry."""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.layer4_platform.bot_registry import (  # noqa: E402
    BotConfigInvalidError,
    BotConfigService,
    BotNotFoundError,
    PublicBotConfig,
    normalize_origin,
)


@pytest.fixture
def svc(tmp_path):
    return BotConfigService(store_dir=tmp_path / "bot_configs")


def _make(svc, **kw):
    params = dict(tenant_id="acme", collection_id="acme-kb", allowed_origins=["https://acme.com"])
    params.update(kw)
    return svc.create_bot(**params)


def test_public_config_omits_internal_ids(svc):
    bot = _make(svc)
    data = svc.get_public_config(bot.bot_id).model_dump()
    for leaked in ("tenant_id", "collection_id", "allowed_origins"):
        assert leaked not in data
        # the model itself must not even declare these fields
        assert leaked not in PublicBotConfig.model_fields


def test_enabled_bot_requires_an_origin(svc):
    with pytest.raises(BotConfigInvalidError):
        svc.create_bot(tenant_id="a", collection_id="c", allowed_origins=[], enabled=True)


def test_disabled_bot_may_have_no_origins(svc):
    bot = svc.create_bot(tenant_id="a", collection_id="c", allowed_origins=[], enabled=False)
    assert bot.enabled is False


def test_origin_matching(svc):
    bot = _make(svc, allowed_origins=["https://acme.com", "http://localhost:5500"])
    assert svc.is_origin_allowed(bot.bot_id, "https://acme.com") is True
    # a Referer carries a path; it must still match on origin
    assert svc.is_origin_allowed(bot.bot_id, "https://acme.com/pricing?x=1") is True
    assert svc.is_origin_allowed(bot.bot_id, "https://evil.com") is False
    assert svc.is_origin_allowed(bot.bot_id, "") is False
    assert svc.is_origin_allowed(bot.bot_id, "not-a-url") is False


def test_origins_are_normalized_and_deduped(svc):
    bot = _make(svc, allowed_origins=["https://acme.com/", "HTTPS://ACME.COM", "https://acme.com"])
    assert bot.allowed_origins == ["https://acme.com"]


def test_normalize_origin_drops_path_and_garbage():
    assert normalize_origin("https://A.com:8080/x?y#z") == "https://a.com:8080"
    assert normalize_origin("garbage") == ""
    assert normalize_origin("") == ""


def test_persistence_roundtrip(svc, tmp_path):
    bot = _make(svc, display_name="Lumi")
    reopened = BotConfigService(store_dir=tmp_path / "bot_configs")
    assert reopened.get_bot(bot.bot_id).display_name == "Lumi"


def test_disabled_bot_is_public_404(svc):
    bot = _make(svc)
    svc.update_bot(bot.bot_id, {"enabled": False})
    with pytest.raises(BotNotFoundError):
        svc.get_public_config(bot.bot_id)


def test_update_cannot_change_identity(svc):
    bot = _make(svc)
    updated = svc.update_bot(bot.bot_id, {"tenant_id": "hacker", "display_name": "X"})
    assert updated.tenant_id == "acme"  # identity preserved
    assert updated.display_name == "X"


def test_missing_bot_raises(svc):
    with pytest.raises(BotNotFoundError):
        svc.get_bot("bot_does_not_exist")
