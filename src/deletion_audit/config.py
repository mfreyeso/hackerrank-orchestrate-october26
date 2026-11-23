"""Application configuration and pricing table via pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelPricing(BaseModel):
    """Token pricing per 1,000,000 tokens in USD."""

    input_per_1m_usd: float = Field(ge=0.0)
    output_per_1m_usd: float = Field(ge=0.0)


DEFAULT_PRICE_TABLE: dict[str, ModelPricing] = {
    "fake-deterministic-v1": ModelPricing(input_per_1m_usd=0.0, output_per_1m_usd=0.0),
    "claude-3-5-haiku-latest": ModelPricing(input_per_1m_usd=0.80, output_per_1m_usd=4.00),
    "claude-3-5-sonnet-latest": ModelPricing(input_per_1m_usd=3.00, output_per_1m_usd=15.00),
    "gpt-4o-mini": ModelPricing(input_per_1m_usd=0.15, output_per_1m_usd=0.60),
    "gpt-4o": ModelPricing(input_per_1m_usd=2.50, output_per_1m_usd=10.00),
}


class AuditSettings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: Literal["fake", "anthropic", "openai"] = Field(
        default="fake",
        validation_alias="AUDIT_LLM_PROVIDER",
    )
    extraction_model: str = Field(
        default="claude-3-5-haiku-latest",
        validation_alias="AUDIT_EXTRACTION_MODEL",
    )
    reasoning_model: str = Field(
        default="claude-3-5-sonnet-latest",
        validation_alias="AUDIT_REASONING_MODEL",
    )
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="ANTHROPIC_API_KEY",
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )

    repo_root: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[2],
    )
    dataset_dir: Path = Field(
        default=Path("dataset"),
        validation_alias="AUDIT_DATASET_DIR",
    )
    prompts_dir: Path = Field(
        default=Path("prompts"),
        validation_alias="AUDIT_PROMPTS_DIR",
    )
    cache_dir: Path = Field(
        default=Path(".audit_cache"),
        validation_alias="AUDIT_CACHE_DIR",
    )
    max_concurrency: int = Field(
        default=8,
        ge=1,
        le=64,
        validation_alias="AUDIT_MAX_CONCURRENCY",
    )
    max_verifier_retries: int = Field(
        default=1,
        ge=0,
        le=3,
        validation_alias="AUDIT_MAX_VERIFIER_RETRIES",
    )
    log_level: str = Field(
        default="INFO",
        validation_alias="AUDIT_LOG_LEVEL",
    )
    price_table: dict[str, ModelPricing] = Field(
        default_factory=lambda: dict(DEFAULT_PRICE_TABLE),
    )

    @property
    def resolved_dataset_dir(self) -> Path:
        if self.dataset_dir.is_absolute():
            return self.dataset_dir.resolve()
        return (self.repo_root / self.dataset_dir).resolve()

    @property
    def resolved_prompts_dir(self) -> Path:
        if self.prompts_dir.is_absolute():
            return self.prompts_dir.resolve()
        return (self.repo_root / self.prompts_dir).resolve()

    @property
    def resolved_cache_dir(self) -> Path:
        if self.cache_dir.is_absolute():
            return self.cache_dir.resolve()
        return (self.repo_root / self.cache_dir).resolve()

    def resolve_dataset_file(self, relative_path: str | Path) -> Path:
        """Resolve a path strictly inside `dataset/` to prevent directory traversal."""
        base = self.resolved_dataset_dir
        candidate = (base / relative_path).resolve()
        if candidate != base and base not in candidate.parents:
            msg = f"Access denied: path '{relative_path}' escapes sandbox '{base}'"
            raise PermissionError(msg)
        return candidate

    def estimate_cost_usd(self, model_name: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate estimated cost in USD using the configured price table."""
        pricing = self.price_table.get(
            model_name,
            ModelPricing(input_per_1m_usd=0.0, output_per_1m_usd=0.0),
        )
        in_cost = (input_tokens / 1_000_000.0) * pricing.input_per_1m_usd
        out_cost = (output_tokens / 1_000_000.0) * pricing.output_per_1m_usd
        return round(in_cost + out_cost, 8)
