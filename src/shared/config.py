"""
📁 File: src/shared/config.py
Layer: Shared (Cross-cutting)
Purpose: Centralized configuration management with validation
Depends on: pydantic-settings, python-dotenv
Used by: All layers

Configuration principles:
- Single source of truth
- Environment-based overrides
- Validation at startup
- Type-safe access
- No hardcoded values
"""

import os
from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

OS_ENV_ONLY_SECRET_FIELDS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "HUGGINGFACE_API_KEY",
    "COHERE_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "QDRANT_API_KEY",
)


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    All settings have sensible defaults for development.
    Production deployments must override via environment variables.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra env vars
    )
    
    # ==========================================
    # APPLICATION
    # ==========================================
    APP_NAME: str = "enterprise-ai-platform"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    
    # ==========================================
    # API SERVER
    # ==========================================
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_WORKERS: int = 4
    API_RELOAD: bool = True
    
    # ==========================================
    # SECURITY
    # ==========================================
    SECRET_KEY: str = Field(
        default="dev-secret-key-change-in-production",
        description="Secret key for JWT signing",
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 30
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8000"
    
    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str, info: any) -> str:
        """Ensure secret key is changed in production."""
        environment = info.data.get("ENVIRONMENT", "development")
        if environment == "production" and v == "dev-secret-key-change-in-production":
            raise ValueError("SECRET_KEY must be changed in production")
        return v

    @field_validator(*OS_ENV_ONLY_SECRET_FIELDS, mode="before")
    @classmethod
    def load_os_env_only_secrets(cls, v: Optional[str], info: any) -> Optional[str]:
        """
        Force sensitive credentials to be read only from OS environment variables.

        This deliberately ignores values coming from `.env` to avoid accidental
        persistence of real secrets in project files.
        """
        env_name = info.field_name
        os_value = os.getenv(env_name)
        if os_value is None:
            return None
        os_value = os_value.strip()
        return os_value or None
    
    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins into a list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    # ==========================================
    # EXTERNAL CHATBOT WIDGET
    # ==========================================
    # Public, cross-origin surface (/widget/*). Deliberately separate from the
    # authenticated CORS policy above: it is credential-less and rate-limited.
    WIDGET_PUBLIC_ENABLED: bool = True
    WIDGET_RATE_PER_IP_PER_MIN: int = 20          # per visitor IP, per bot, per minute
    WIDGET_RATE_PER_BOT_PER_MIN: int = 120        # aggregate across all visitors of one bot
    WIDGET_BOT_DAILY_CAP: int = 2000              # per-bot requests per UTC day
    WIDGET_CRAWLER_MAX_PAGES: int = 50            # hard ceiling on pages fetched per crawl
    WIDGET_CRAWLER_MAX_DEPTH: int = 3             # hard ceiling on crawl BFS depth

    # AutoPilot onboarding: paste a URL -> headless-render the site, screenshot it,
    # extract a brand palette, and AI-fill the bot's copy. Admin-only; needs the
    # optional `playwright` browser engine installed (degrades with a clear error).
    WIDGET_AUTOPILOT_ENABLED: bool = True
    WIDGET_AUTOPILOT_VIEWPORT_WIDTH: int = 1366    # render viewport width (desktop layout)
    WIDGET_AUTOPILOT_TIMEOUT_S: float = 25.0       # per-page render/navigation budget
    WIDGET_AUTOPILOT_SCREENSHOT_WIDTH: int = 1280  # stored screenshot is downscaled to this width
    WIDGET_AUTOPILOT_MAX_TEXT_CHARS: int = 6000    # page text fed to the autofill LLM
    WIDGET_AUTOPILOT_ALLOW_PRIVATE_HOSTS: bool = False  # SSRF guard: block private/loopback IPs

    # ==========================================
    # LAYER 0 - MODEL INFRASTRUCTURE
    # ==========================================
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_SITE_URL: str = "http://localhost:8000"
    OPENROUTER_APP_NAME: str = "enterprise-ai-platform"
    HUGGINGFACE_API_KEY: Optional[str] = None
    HUGGINGFACE_API_BASE: Optional[str] = None
    COHERE_API_KEY: Optional[str] = None
    AZURE_OPENAI_API_KEY: Optional[str] = None
    AZURE_OPENAI_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_API_VERSION: str = "2024-02-01"
    
    # LiteLLM Configuration
    LITELLM_LOG_LEVEL: str = "INFO"
    LITELLM_DROP_PARAMS: bool = True
    LITELLM_TELEMETRY: bool = False
    
    # Default Models
    DEFAULT_TEXT_MODEL: str = "ollama-qwen3-8b"
    DEFAULT_VISION_MODEL: str = "ollama-gemma3-4b"
    DEFAULT_EMBEDDING_MODEL: str = "qwen3-embedding-0.6b"
    
    # Ollama (Local Models)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_ENABLED: bool = True
    PREFER_FREE_API_PROVIDERS: bool = True
    ENABLE_FREE_API_FALLBACK: bool = True
    FREE_API_FALLBACK_MODEL_ID: str = "ollama-llama3.1-8b"

    # Layer 3 — Benchmark-driven kNN router (env-overridable surface only;
    # internal numeric thresholds live in routing_config.Layer3Config).
    # The kNN router is the production router. LAYER3_ENABLED is a kill switch /
    # demo toggle (off => routing degrades to a safe-default model). The old
    # canary-fraction + shadow-mode migration flags were retired once the legacy
    # L3-L5 pipeline was decommissioned (archived under routing/legacy/).
    LAYER3_ENABLED: bool = True
    LAYER3_QUALITY_FLOOR_DEFAULT: Optional[float] = None  # None = use config default
    LAYER3_QUALITY_FLOOR_HIGH_RISK: Optional[float] = None
    LAYER3_ENCODER_DEVICE: Literal["cuda", "cpu", "auto"] = "auto"
    
    # ==========================================
    # LAYER 1 - COGNITIVE (EMBEDDINGS & RAG)
    # ==========================================
    
    # Vector Database (Qdrant)
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_COLLECTION_NAME: str = "enterprise_knowledge"
    
    # Embedding Configuration
    EMBEDDING_DIMENSION: int = 1024  # ollama/qwen3-embedding:0.6b
    EMBEDDING_BATCH_SIZE: int = 100

    # Grounded RAG retrieval
    # The local cross-encoder reranker (cross-encoder/ms-marco-MiniLM-L-6-v2)
    # sharpens result ordering but loads a model onto the GPU on first use,
    # competing with the Layer 3 encoder. Default on; set false for a pure
    # lexical+vector path with lower first-query latency and no GPU load.
    RAG_CROSS_ENCODER_ENABLED: bool = True

    # Vector store backing grounded RAG collections: "memory" (in-process, the
    # default — simplest, rebuilt on restart) or "qdrant" (persists across
    # restarts and scales past one process). Qdrant falls back to memory if the
    # server is unreachable at service construction.
    RAG_VECTOR_BACKEND: str = "memory"
    
    @property
    def qdrant_url(self) -> str:
        """Construct Qdrant URL."""
        return f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"
    
    # ==========================================
    # DATABASE (PostgreSQL)
    # ==========================================
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "enterprise_ai_platform"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    
    # SQLAlchemy
    DATABASE_URL: Optional[str] = None
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_ECHO: bool = False
    
    @property
    def database_url_computed(self) -> str:
        """
        Construct database URL if not explicitly provided.
        
        Returns:
            PostgreSQL connection string
        """
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )
    
    # ==========================================
    # CACHE & MEMORY (Redis)
    # ==========================================
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    REDIS_MAX_CONNECTIONS: int = 50
    
    # Session Configuration
    SESSION_TTL_SECONDS: int = 3600  # 1 hour
    CONVERSATION_MEMORY_TTL_SECONDS: int = 86400  # 24 hours
    
    @property
    def redis_url(self) -> str:
        """Construct Redis URL."""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
    
    # ==========================================
    # LAYER 5 - OBSERVABILITY
    # ==========================================
    
    # Arize Phoenix
    PHOENIX_HOST: str = "localhost"
    PHOENIX_PORT: int = 6006
    PHOENIX_COLLECTOR_ENDPOINT: Optional[str] = None
    
    @property
    def phoenix_collector_endpoint_computed(self) -> str:
        """Construct Phoenix collector endpoint."""
        if self.PHOENIX_COLLECTOR_ENDPOINT:
            return self.PHOENIX_COLLECTOR_ENDPOINT
        return f"http://{self.PHOENIX_HOST}:{self.PHOENIX_PORT}/v1/traces"
    
    # Logging
    LOG_FORMAT: Literal["json", "text"] = "json"
    LOG_OUTPUT: Literal["stdout", "file"] = "stdout"
    LOG_FILE_PATH: str = "logs/app.log"
    
    # ==========================================
    # LAYER 6 - AI OPS & EVALUATION
    # ==========================================
    GOLDEN_DATASET_PATH: str = "tests/golden_datasets"
    EVALUATION_MODEL: str = "ollama/deepseek-r1:7b"
    HALLUCINATION_THRESHOLD: float = 0.7
    
    # ==========================================
    # MULTI-TENANCY (LAYER 4)
    # ==========================================
    DEFAULT_TENANT_ID: str = "default"
    TENANT_ISOLATION_ENABLED: bool = True
    
    # ==========================================
    # RATE LIMITING
    # ==========================================
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_PER_HOUR: int = 1000
    
    # ==========================================
    # FEATURE FLAGS
    # ==========================================
    ENABLE_WEB_SEARCH: bool = False
    ENABLE_CODE_EXECUTION: bool = False
    ENABLE_MULTIMODAL: bool = True
    ENABLE_STREAMING: bool = True
    ENABLE_HUMAN_IN_LOOP: bool = True
    
    # ==========================================
    # COST MANAGEMENT
    # ==========================================
    MAX_TOKENS_PER_REQUEST: int = 4000
    MAX_COST_PER_REQUEST_USD: float = 0.50
    BUDGET_ALERT_THRESHOLD_USD: float = 100.00
    
    # ==========================================
    # EXTERNAL SERVICES (Optional)
    # ==========================================
    
    # Email
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None
    
    # Slack
    SLACK_WEBHOOK_URL: Optional[str] = None
    
    # ==========================================
    # DEVELOPMENT & DEBUGGING
    # ==========================================
    ENABLE_API_DOCS: bool = True
    ENABLE_PROFILING: bool = False
    ENABLE_QUERY_LOGGING: bool = False
    DEMO_SIMULATION_DEFAULT_WALLET_USD: float = 25.0
    
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.ENVIRONMENT == "production"
    
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.ENVIRONMENT == "development"
    
    def validate_required_for_production(self) -> None:
        """
        Validate that all required settings are configured for production.
        
        Raises:
            ValueError: If required production settings are missing
        """
        if not self.is_production():
            return
        
        required_settings = [
            ("OPENAI_API_KEY", self.OPENAI_API_KEY),
            ("ANTHROPIC_API_KEY", self.ANTHROPIC_API_KEY),
            ("SECRET_KEY", self.SECRET_KEY),
            ("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD),
        ]
        
        missing = [name for name, value in required_settings if not value]
        
        if missing:
            raise ValueError(
                f"Production deployment requires these settings: {', '.join(missing)}"
            )


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    
    This function is cached to ensure settings are loaded only once.
    Use this function throughout the application.
    
    Returns:
        Settings instance
        
    Example:
        >>> from src.shared.config import get_settings
        >>> settings = get_settings()
        >>> print(settings.API_PORT)
    """
    settings = Settings()
    
    # Validate production requirements
    if settings.is_production():
        settings.validate_required_for_production()
    
    return settings
