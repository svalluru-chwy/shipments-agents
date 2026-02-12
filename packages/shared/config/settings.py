"""
Central configuration for Shipments Agency Platform.

Loads from config.yaml with environment variable overrides.
Provides typed access to all configuration sections.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pydantic config models
# ---------------------------------------------------------------------------


class SnowflakeConfig(BaseModel):
    account: str = ""
    user: str = ""
    warehouse: str = "SC_FORECAST_WH"
    database: str = "EDLDB"
    schema_: str = Field("sc_user_tools_analytics_sandbox", alias="schema")
    role: str = ""
    okta_url: str = ""

    model_config = {"populate_by_name": True}


class S3Config(BaseModel):
    bucket: str = "dev-use1-worker-sc-fp-data"
    base_path: str = "uta/cat_outputs"
    region: str = "us-east-1"

    @property
    def base_url(self) -> str:
        return f"s3://{self.bucket}/{self.base_path}"


class PipelineConfig(BaseModel):
    max_parallel_queries: int = 7
    max_retries: int = 2


class OpenAIConfig(BaseModel):
    default_model: str = "gpt-5-nano-2025-08-07"
    reasoning_effort: str = "high"
    timeout: int = 600


class ShipmentSignalsAgentConfig(BaseModel):
    model: str = "gpt-5-nano-2025-08-07"
    reasoning_effort: str = "high"
    timeout: int = 600
    check_gate_model: str = "gpt-5-nano-2025-08-07"
    signal_generator_model: str = "gpt-4.1-2025-04-14"
    contacts_model: str = "o3-2025-04-16"
    validation_threshold: float = 0.95
    max_retries: int = 2


class ShipmentDecoderAgentConfig(BaseModel):
    model: str = "o3-2025-04-16"
    reasoning_effort: str = "high"
    timeout: int = 600
    densification_model: str = "gpt-5-nano-2025-08-07"
    decoder_model: str = "o3-2025-04-16"
    delay_predictor_model: str = "gpt-5-nano-2025-08-07"
    validation_threshold: float = 0.90
    max_retries: int = 2


class ShipmentActionsAgentConfig(BaseModel):
    model: str = "gpt-5-nano-2025-08-07"
    reasoning_effort: str = "high"
    timeout: int = 600
    planner_model: str = "gpt-5-nano-2025-08-07"
    prioritizer_model: str = "gpt-5-nano-2025-08-07"
    consolidator_model: str = "gpt-5-nano-2025-08-07"
    validation_threshold: float = 0.90
    max_retries: int = 2


class AgentsConfig(BaseModel):
    shipment_signals: ShipmentSignalsAgentConfig = ShipmentSignalsAgentConfig()
    shipment_decoder: ShipmentDecoderAgentConfig = ShipmentDecoderAgentConfig()
    shipment_actions: ShipmentActionsAgentConfig = ShipmentActionsAgentConfig()


class SkillsConfig(BaseModel):
    max_parallel_skills: int = 12
    default_peer_level: str = "SEGMENT"


class GatewayConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:3002"]


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class Settings(BaseModel):
    """Top-level settings container for the entire platform."""

    snowflake: SnowflakeConfig = SnowflakeConfig(schema="sc_user_tools_analytics_sandbox")
    s3: S3Config = S3Config()
    pipeline: PipelineConfig = PipelineConfig()
    openai: OpenAIConfig = OpenAIConfig()
    agents: AgentsConfig = AgentsConfig()
    skills: SkillsConfig = SkillsConfig()
    gateway: GatewayConfig = GatewayConfig()
    logging: LoggingConfig = LoggingConfig()


# ---------------------------------------------------------------------------
# Singleton loader
# ---------------------------------------------------------------------------

_settings: Optional[Settings] = None


def _find_config_file() -> Optional[Path]:
    """Search for config.yaml walking up from CWD and the package root."""
    candidates = [
        Path.cwd() / "config.yaml",
        Path(__file__).resolve().parents[3] / "config.yaml",  # repo root
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def get_settings(config_path: Optional[str] = None, reload: bool = False) -> Settings:
    """
    Load and return the singleton :class:`Settings` instance.

    Resolution order (highest priority first):
      1. Environment variables (``SNOWFLAKE_ACCOUNT``, ``AWS_REGION``, ...)
      2. Explicit *config_path* argument
      3. Auto-discovered ``config.yaml``
      4. Built-in defaults

    Args:
        config_path: Explicit path to a YAML config file.
        reload: Force reload even if already loaded.
    """
    global _settings
    if _settings is not None and not reload:
        return _settings

    load_dotenv()

    # Load YAML
    raw: Dict[str, Any] = {}
    path = Path(config_path) if config_path else _find_config_file()
    if path and path.is_file():
        with open(path) as fh:
            raw = yaml.safe_load(fh) or {}

    # Apply env-var overrides for commonly changed values
    sf = raw.setdefault("snowflake", {})
    sf["account"] = os.getenv("SNOWFLAKE_ACCOUNT", sf.get("account", ""))
    sf["user"] = os.getenv("SNOWFLAKE_USER", sf.get("user", ""))
    sf["warehouse"] = os.getenv("SNOWFLAKE_WAREHOUSE", sf.get("warehouse", "SC_FORECAST_WH"))
    sf["database"] = os.getenv("SNOWFLAKE_DATABASE", sf.get("database", "EDLDB"))
    sf["role"] = os.getenv("SNOWFLAKE_ROLE", sf.get("role", ""))

    s3 = raw.setdefault("s3", {})
    s3["region"] = os.getenv("AWS_REGION", s3.get("region", "us-east-1"))

    gw = raw.setdefault("gateway", {})
    gw["host"] = os.getenv("GATEWAY_HOST", gw.get("host", "0.0.0.0"))
    gw["port"] = int(os.getenv("GATEWAY_PORT", gw.get("port", 8000)))

    _settings = Settings(**raw)
    return _settings
