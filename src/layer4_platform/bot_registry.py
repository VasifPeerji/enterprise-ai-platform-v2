"""
Per-company external chatbot configuration registry.

This is the platform-level store that turns the internal Smart-Routing + grounded
RAG stack into a *brandable, embeddable* widget any company can drop onto its
website. A company maps to:

    tenant_id  +  grounded collection_id  +  one ``BotConfig``

The ``BotConfig`` carries everything needed to render and serve that company's
widget — branding (``BotTheme``), greeting, suggested prompts, the knowledge
collection to answer from, and the exact origins allowed to embed it.

Two projections exist on purpose:

* ``BotConfig``        — the full, server-side record (includes ``tenant_id``,
                         ``collection_id`` and ``allowed_origins``).
* ``PublicBotConfig``  — the *safe* projection the browser widget is allowed to
                         see. It deliberately omits every internal identifier so
                         a leaked ``bot_id`` (which sits in the page source) never
                         reveals the tenant, the collection, or the origin policy.

Persistence mirrors ``DocumentCollectionService``: an in-process dict cache plus
a JSON snapshot per bot under ``.runtime/bot_configs/``. Unlike that service we
resolve the store directory from ``__file__`` rather than a hard-coded absolute
path (the hard-coded path in ``document_collections.py`` is pre-existing debt we
do not want to propagate).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from src.shared.errors import DomainError
from src.shared.logger import get_logger

logger = get_logger(__name__)

# Repo root resolved from this file: src/layer4_platform/bot_registry.py -> parents[2].
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BOT_STORE_DIR = _REPO_ROOT / ".runtime" / "bot_configs"

_BOT_ID_PREFIX = "bot_"


class BotNotFoundError(DomainError):
    """Requested bot configuration does not exist (or is disabled)."""

    def __init__(self, bot_id: str) -> None:
        super().__init__(
            message=f"Bot '{bot_id}' not found",
            error_code="BOT_NOT_FOUND",
            details={"bot_id": bot_id},
        )
        self.status_code = 404


class BotConfigInvalidError(DomainError):
    """A bot configuration failed a platform invariant (e.g. open origins)."""

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(
            message=message,
            error_code="BOT_CONFIG_INVALID",
            details=dict(details),
        )
        self.status_code = 400


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class BotTheme(BaseModel):
    """All per-company branding. Re-skinning a company = editing these values.

    Every field is surfaced to the widget as a CSS custom property
    (``--bot-*``), so the widget's stylesheet never changes between companies.
    """

    primary_color: str = Field(default="#4f46e5", description="Primary / brand color (header, send button)")
    accent_color: Optional[str] = Field(default=None, description="Accent (links, chips); falls back to primary")
    surface_color: str = Field(default="#ffffff", description="Panel background")
    text_color: str = Field(default="#1f2937", description="Primary text color")
    user_bubble_color: Optional[str] = Field(
        default=None, description="Visitor bubble background; falls back to primary so partial themes stay coherent"
    )
    bot_bubble_color: Optional[str] = Field(
        default=None,
        description="Assistant bubble background; falls back to an adaptive neutral tint (light/dark) when unset",
    )
    font_family: str = Field(
        default="system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
        description="CSS font-family stack",
    )
    font_url: Optional[str] = Field(default=None, description="Optional web-font stylesheet URL to load")
    logo_url: Optional[str] = Field(default=None, description="Logo shown in the panel header")
    launcher_icon_url: Optional[str] = Field(default=None, description="Icon for the floating launcher bubble")
    launcher_position: str = Field(default="bottom-right", description="bottom-right or bottom-left")
    corner_radius_px: int = Field(default=16, ge=0, le=40, description="Panel/border corner radius")
    dark_mode: bool = Field(default=False, description="Force a dark surface regardless of visitor preference")
    auto_dark: bool = Field(
        default=True, description="Adapt to the visitor's prefers-color-scheme (dark) automatically"
    )
    auto_brand: bool = Field(
        default=False, description="Use the host page's theme-color as the primary, so it matches the site"
    )


class SuggestedPrompt(BaseModel):
    """A use-case / FAQ quick-reply chip shown under the greeting."""

    label: str = Field(..., min_length=1, description="Chip text the visitor sees")
    prompt: str = Field(..., min_length=1, description="The query actually sent when the chip is clicked")


class BotConfig(BaseModel):
    """Full, server-side bot record. NEVER returned to the browser as-is."""

    bot_id: str = Field(..., description="Public, unguessable handle embedded in the page")
    tenant_id: str = Field(..., description="Company tenant key (also scopes the grounded collection)")
    collection_id: str = Field(..., description="Grounded collection answers are drawn from")
    display_name: str = Field(default="Assistant", description="Bot name shown in the header")
    greeting: str = Field(default="Hi! How can I help you today?", description="Opening message")
    subtitle: str = Field(default="Typically replies instantly", description="Header status line under the name")
    teaser: str = Field(
        default="Hi there 👋 Have a question? I'm here to help.",
        description="Proactive nudge bubble text shown near the launcher",
    )
    show_teaser: bool = Field(default=True, description="Show the proactive teaser bubble")
    branding: str = Field(default="Powered by Smart Routing", description="Footer text; empty string hides it")
    suggested_prompts: list[SuggestedPrompt] = Field(default_factory=list)
    theme: BotTheme = Field(default_factory=BotTheme)
    allowed_origins: list[str] = Field(
        default_factory=list,
        description="Exact origins (scheme://host[:port]) permitted to embed this bot",
    )
    grounded_domain: Optional[str] = Field(default=None, description="Optional retrieval domain override")
    grounded_top_k: int = Field(default=6, ge=1, le=20)
    enabled: bool = Field(default=True)
    created_at: Optional[str] = Field(default=None)
    updated_at: Optional[str] = Field(default=None)

    def to_public(self) -> "PublicBotConfig":
        """Project to the browser-safe view (drops every internal identifier)."""
        return PublicBotConfig(
            bot_id=self.bot_id,
            display_name=self.display_name,
            greeting=self.greeting,
            subtitle=self.subtitle,
            teaser=self.teaser,
            show_teaser=self.show_teaser,
            branding=self.branding,
            suggested_prompts=self.suggested_prompts,
            theme=self.theme,
        )


class PublicBotConfig(BaseModel):
    """The only shape the embeddable widget is allowed to receive.

    Carries no ``tenant_id``, ``collection_id`` or ``allowed_origins`` — a
    leaked ``bot_id`` yields branding only, never the knowledge base or origin
    policy behind it.
    """

    bot_id: str
    display_name: str
    greeting: str
    subtitle: str = "Typically replies instantly"
    teaser: str = ""
    show_teaser: bool = True
    branding: str = ""
    suggested_prompts: list[SuggestedPrompt]
    theme: BotTheme


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize_origin(origin: str) -> str:
    """Reduce an Origin/Referer to a canonical ``scheme://host[:port]`` form.

    Accepts either a bare origin or a full URL (a ``Referer`` carries a path);
    lower-cases scheme and host; drops any path/query/fragment. Returns ``""``
    for input that has no scheme+host (which can never match an allow entry).
    """
    if not origin:
        return ""
    parts = urlsplit(origin.strip())
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class BotConfigService:
    """In-process + JSON-snapshot store for per-company bot configurations."""

    def __init__(self, *, store_dir: Optional[Path] = None) -> None:
        self._store_dir = store_dir or _BOT_STORE_DIR
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._bots: dict[str, BotConfig] = {}
        self._lock = RLock()
        self._load_all()

    # -- persistence -------------------------------------------------------

    def _json_path(self, bot_id: str) -> Path:
        safe = bot_id.replace("/", "_").replace("\\", "_")
        return self._store_dir / f"{safe}.json"

    def _load_all(self) -> None:
        for path in self._store_dir.glob("*.json"):
            try:
                config = BotConfig.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception as exc:  # pragma: no cover - corrupt snapshot
                logger.warning("bot_config_load_failed", path=str(path), error=str(exc), layer="layer4_platform")
                continue
            self._bots[config.bot_id] = config

    def _persist(self, config: BotConfig) -> None:
        path = self._json_path(config.bot_id)
        path.write_text(config.model_dump_json(indent=2), encoding="utf-8")

    # -- validation --------------------------------------------------------

    @staticmethod
    def _normalize_origins(origins: list[str]) -> list[str]:
        seen: list[str] = []
        for raw in origins:
            normalized = normalize_origin(raw)
            if normalized and normalized not in seen:
                seen.append(normalized)
        return seen

    def _validate(self, config: BotConfig) -> None:
        # Default-deny: an enabled bot must name at least one explicit origin.
        # An open public chat endpoint is a budget-drain / scraping hazard.
        if config.enabled and not config.allowed_origins:
            raise BotConfigInvalidError(
                "An enabled bot must declare at least one allowed origin "
                "(default-deny). Provide allowed_origins or set enabled=false.",
                bot_id=config.bot_id,
            )
        if config.theme.launcher_position not in {"bottom-right", "bottom-left"}:
            raise BotConfigInvalidError(
                "theme.launcher_position must be 'bottom-right' or 'bottom-left'.",
                bot_id=config.bot_id,
            )

    # -- public API --------------------------------------------------------

    def create_bot(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        display_name: str = "Assistant",
        greeting: str = "Hi! How can I help you today?",
        subtitle: Optional[str] = None,
        teaser: Optional[str] = None,
        show_teaser: Optional[bool] = None,
        branding: Optional[str] = None,
        suggested_prompts: Optional[list[SuggestedPrompt]] = None,
        theme: Optional[BotTheme] = None,
        allowed_origins: Optional[list[str]] = None,
        grounded_domain: Optional[str] = None,
        grounded_top_k: int = 6,
        enabled: bool = True,
    ) -> BotConfig:
        bot_id = f"{_BOT_ID_PREFIX}{secrets.token_urlsafe(12)}"
        now = _now_iso()
        # Only override BotConfig's defaults for content fields that were given.
        extra = {
            k: v
            for k, v in {"subtitle": subtitle, "teaser": teaser, "show_teaser": show_teaser, "branding": branding}.items()
            if v is not None
        }
        config = BotConfig(
            bot_id=bot_id,
            tenant_id=tenant_id,
            collection_id=collection_id,
            display_name=display_name,
            greeting=greeting,
            suggested_prompts=suggested_prompts or [],
            theme=theme or BotTheme(),
            **extra,
            allowed_origins=self._normalize_origins(allowed_origins or []),
            grounded_domain=grounded_domain,
            grounded_top_k=grounded_top_k,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        self._validate(config)
        with self._lock:
            self._bots[bot_id] = config
            self._persist(config)
        logger.info(
            "bot_created",
            bot_id=bot_id,
            tenant_id=tenant_id,
            collection_id=collection_id,
            origins=len(config.allowed_origins),
            layer="layer4_platform",
        )
        return config

    def get_bot(self, bot_id: str) -> BotConfig:
        with self._lock:
            config = self._bots.get(bot_id)
        if config is None:
            raise BotNotFoundError(bot_id)
        return config

    def get_public_config(self, bot_id: str) -> PublicBotConfig:
        config = self.get_bot(bot_id)
        if not config.enabled:
            raise BotNotFoundError(bot_id)
        return config.to_public()

    def update_bot(self, bot_id: str, patch: dict) -> BotConfig:
        with self._lock:
            current = self.get_bot(bot_id)
            data = current.model_dump()
            # Only overwrite keys explicitly provided; ignore identity fields.
            for key in ("bot_id", "tenant_id", "created_at"):
                patch.pop(key, None)
            if "allowed_origins" in patch and patch["allowed_origins"] is not None:
                patch["allowed_origins"] = self._normalize_origins(patch["allowed_origins"])
            data.update({k: v for k, v in patch.items() if v is not None})
            data["updated_at"] = _now_iso()
            updated = BotConfig.model_validate(data)
            self._validate(updated)
            self._bots[bot_id] = updated
            self._persist(updated)
        logger.info("bot_updated", bot_id=bot_id, layer="layer4_platform")
        return updated

    def list_bots(self, tenant_id: Optional[str] = None) -> list[BotConfig]:
        with self._lock:
            bots = list(self._bots.values())
        if tenant_id is not None:
            bots = [b for b in bots if b.tenant_id == tenant_id]
        return sorted(bots, key=lambda b: b.created_at or "")

    def delete_bot(self, bot_id: str) -> None:
        with self._lock:
            self._bots.pop(bot_id, None)
            path = self._json_path(bot_id)
            if path.exists():
                path.unlink()
        logger.info("bot_deleted", bot_id=bot_id, layer="layer4_platform")

    def is_origin_allowed(self, bot_id: str, origin: str) -> bool:
        """Authoritative per-bot origin check (the real gate; CORS is advisory).

        An empty/garbage origin never matches. An enabled bot always has at
        least one origin (enforced at write time), so a missing Origin header is
        denied rather than silently allowed.
        """
        config = self.get_bot(bot_id)
        candidate = normalize_origin(origin)
        if not candidate:
            return False
        return candidate in set(config.allowed_origins)

    def all_allowed_origins(self) -> set[str]:
        with self._lock:
            origins: set[str] = set()
            for bot in self._bots.values():
                origins.update(bot.allowed_origins)
        return origins

    @staticmethod
    def embed_snippet(bot_id: str, api_base: str) -> str:
        base = api_base.rstrip("/")
        return (
            f'<script src="{base}/widget/loader.js" '
            f'data-bot-id="{bot_id}" data-api-base="{base}" async></script>'
        )


_bot_config_service: Optional[BotConfigService] = None


def get_bot_config_service() -> BotConfigService:
    """Return the process-wide bot configuration service singleton."""
    global _bot_config_service
    if _bot_config_service is None:
        _bot_config_service = BotConfigService()
    return _bot_config_service
