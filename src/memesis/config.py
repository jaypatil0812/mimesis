"""Environment-backed application configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://memesis:memesis@localhost:5432/memesis"
    log_level: str = "INFO"
    environment: str = "development"
    ingestion_user_agent: str = "Memesis/0.1 (+https://github.com/memesis)"
    ingestion_request_timeout_seconds: float = 20.0
    ingestion_max_retries: int = 2
    ingestion_retry_backoff_seconds: float = 0.5
    ingestion_cache_ttl_seconds: int = 300
    openalex_api_key: str | None = None
    extract_small_model: str | None = None
    resolve_small_model: str | None = None
    reason_strong_model: str | None = None
    verify_claim_support: bool = False
    model_api_base_url: str = "https://api.openai.com/v1"
    model_api_key: str | None = None

    # Pipeline optimization flags — set to False to disable specific optimizations
    # and measure their impact with the profiler.
    cache_scores_per_day: bool = True  # skip recomputing scores when same as_of day exists
    dedupe_list_calls: bool = True  # cache list_nodes/list_edges within a single answer_query call
    skip_extraction_on_cache_hit: bool = True  # skip LLM extraction if cached projection exists

    model_config = SettingsConfigDict(
        env_prefix="MEMESIS_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
