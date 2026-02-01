```python
"""
src/config.py

Centralised configuration management for the PulseStream Nexus platform.
The module is the single source-of-truth for all runtime settings and is
explicitly designed to be framework-agnostic so that the domain layer can
remain independent from any I/O or infrastructure concerns.

A thin wrapper around pydantic’s `BaseSettings` is used to parse
environment variables and/or YAML/JSON config files.  In addition to type
checking, the settings objects expose helper utilities for:

    * Building standardised logging configurations (dictConfig-ready)
    * Generating connection strings for external services
    * Detecting the current execution environment (dev / staging / prod)
    * Rendering the config as an immutable, serialisable mapping

The settings are loaded exactly once using an LRU-cached factory to avoid
the “Globals Problem” while still affording convenient import-level access
through `get_settings()`.

Example
-------
>>> from src.config import get_settings
>>> settings = get_settings()
>>> settings.kafka.bootstrap_servers
'kafka-1:9092,kafka-2:9092'

Notes
-----
Only the code in this file should import `dotenv`.  All other packages
should interact with configuration exclusively through the strongly-typed
objects defined here.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import sys
from functools import lru_cache
from typing import Dict, List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    BaseSettings,
    Field,
    PostgresDsn,
    SecretStr,
    validator,
)

# --------------------------------------------------------------------------- #
# Misc. constants                                                             #
# --------------------------------------------------------------------------- #
ROOT_DIR: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_DOTENV: pathlib.Path = ROOT_DIR / ".env"
DEFAULT_CONFIG_FILE: pathlib.Path = ROOT_DIR / "config.yml"

# Pre-load dotenv if it exists to populate os.environ before pydantic kicks in
load_dotenv(DEFAULT_DOTENV, override=False)


# --------------------------------------------------------------------------- #
# Settings                                                                    #
# --------------------------------------------------------------------------- #
class KafkaSettings(BaseModel):
    """Kafka-specific configuration."""

    bootstrap_servers: str = Field(..., env="KAFKA_BOOTSTRAP_SERVERS")
    consumer_group: str = Field("pulse_stream_consumer", env="KAFKA_CONSUMER_GROUP")
    security_protocol: str = Field("PLAINTEXT", env="KAFKA_SECURITY_PROTOCOL")
    schema_registry_url: str = Field(..., env="SCHEMA_REGISTRY_URL")
    ssl_cafile: Optional[pathlib.Path] = Field(None, env="KAFKA_SSL_CAFILE")
    ssl_certfile: Optional[pathlib.Path] = Field(None, env="KAFKA_SSL_CERTFILE")
    ssl_keyfile: Optional[pathlib.Path] = Field(None, env="KAFKA_SSL_KEYFILE")
    enable_auto_offset_store: bool = Field(True, env="KAFKA_ENABLE_OFFSET_STORE")
    input_topics: List[str] = Field(
        default_factory=lambda: [
            "twitter_raw",
            "reddit_raw",
            "mastodon_raw",
            "discord_raw",
        ],
        env="KAFKA_INPUT_TOPICS",
    )
    output_topic_enriched: str = Field("social_events_enriched", env="KAFKA_OUT_ENRICHED")

    @validator("input_topics", pre=True)
    def _coerce_topics(cls, v):  # noqa: N805
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        return v

    def build_consumer_config(self) -> Dict[str, str]:
        """Return kwargs suitable for confluent-kafka Consumer() initialisation."""
        config = {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": self.consumer_group,
            "enable.auto.offset.store": self.enable_auto_offset_store,
            "security.protocol": self.security_protocol,
        }
        if self.security_protocol.upper().startswith("SSL"):
            config.update(
                {
                    "ssl.ca.location": str(self.ssl_cafile) if self.ssl_cafile else None,
                    "ssl.certificate.location": str(self.ssl_certfile) if self.ssl_certfile else None,
                    "ssl.key.location": str(self.ssl_keyfile) if self.ssl_keyfile else None,
                }
            )
        return {k: v for k, v in config.items() if v is not None}


class DatabaseSettings(BaseModel):
    """PostgreSQL settings."""

    host: str = Field("localhost", env="POSTGRES_HOST")
    port: int = Field(5432, env="POSTGRES_PORT")
    user: str = Field(..., env="POSTGRES_USER")
    password: SecretStr = Field(..., env="POSTGRES_PASSWORD")
    database: str = Field("pulse_stream", env="POSTGRES_DB")
    pool_size: int = Field(10, env="POSTGRES_POOL_SIZE")

    def dsn(self) -> PostgresDsn:
        """Return a RFC-3986 compliant DSN string suitable for SQLAlchemy."""
        return PostgresDsn.build(
            scheme="postgresql+psycopg2",
            user=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=str(self.port),
            path=f"/{self.database}",
        )


class RedisSettings(BaseModel):
    """Redis cache / pub-sub settings."""

    host: str = Field("localhost", env="REDIS_HOST")
    port: int = Field(6379, env="REDIS_PORT")
    db: int = Field(0, env="REDIS_DB")
    password: Optional[SecretStr] = Field(None, env="REDIS_PASSWORD")

    def url(self) -> str:
        """Return redis:// URL."""
        pwd = f":{self.password.get_secret_value()}@" if self.password else ""
        return f"redis://{pwd}{self.host}:{self.port}/{self.db}"


class MonitoringSettings(BaseModel):
    """Prometheus & Sentry configuration."""

    prometheus_enabled: bool = Field(True, env="PROMETHEUS_ENABLED")
    prometheus_port: int = Field(8000, env="PROMETHEUS_PORT")

    sentry_dsn: Optional[AnyHttpUrl] = Field(None, env="SENTRY_DSN")
    sentry_sample_rate: float = Field(0.1, env="SENTRY_SAMPLE_RATE")


class SparkSettings(BaseModel):
    """Spark / Beam job configuration."""

    master_url: str = Field("local[*]", env="SPARK_MASTER")
    app_name: str = Field("PulseStreamBatchJob", env="SPARK_APP_NAME")
    executor_memory: str = Field("4g", env="SPARK_EXECUTOR_MEMORY")
    runtime_profile: str = Field("batch", env="SPARK_RUNTIME_PROFILE")


class AppSettings(BaseSettings):
    """
    Root settings object composed of all individual sub-settings.

    Environment variables are automatically parsed thanks to pydantic.  Values
    can also be overridden by a YAML or JSON config file at `config_path`.
    """

    # Generic
    env: str = Field("development", env="PULSENEX_ENV")
    debug: bool = Field(True, env="DEBUG")
    timezone: str = Field("UTC", env="TIMEZONE")
    app_version: str = Field("0.1.0", env="APP_VERSION")

    # Composite sub-settings
    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)
    spark: SparkSettings = Field(default_factory=SparkSettings)

    # I/O
    config_path: pathlib.Path = Field(DEFAULT_CONFIG_FILE, env="PULSENEX_CONFIG_FILE")

    # --------------------------------------------------------------------- #
    # pydantic config                                                       #
    # --------------------------------------------------------------------- #
    class Config:
        env_nested_delimiter = "__"  # e.g., KAFKA__BOOTSTRAP_SERVERS
        case_sensitive = False
        validate_assignment = True

    # ------------------------------------------------------------------ #
    # Validators / root-level helpers                                    #
    # ------------------------------------------------------------------ #
    @validator("env")
    def _validate_env(cls, value: str):  # noqa: N805
        allowed = {"development", "staging", "production", "test"}
        if value not in allowed:
            raise ValueError(f"env must be one of {allowed!r}")
        return value

    @validator("config_path", pre=True)
    def _coerce_config_path(cls, v):  # noqa: N805
        return pathlib.Path(v) if v is not None else DEFAULT_CONFIG_FILE

    @classmethod
    def from_yaml(cls, file_path: pathlib.Path) -> "AppSettings":
        """
        Alternative constructor loading values from YAML/JSON and falling back
        to environment variables for missing keys.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Config file '{file_path}' missing.")

        with file_path.open() as fp:
            try:
                data = yaml.safe_load(fp.read()) or {}
            except yaml.YAMLError as exc:
                raise RuntimeError(f"Unable to parse config file: {exc}") from exc

        # pydantic allows env var precedence if Config.env_prefix etc.
        return cls(**data)

    # ------------------------------------------------------------------ #
    # Convenience properties                                             #
    # ------------------------------------------------------------------ #
    @property
    def is_dev(self) -> bool:
        return self.env == "development"

    @property
    def is_prod(self) -> bool:
        return self.env == "production"

    # ------------------------------------------------------------------ #
    # Logging                                                             #
    # ------------------------------------------------------------------ #
    def logging_dict(self) -> Dict:
        """
        Return a `logging.config.dictConfig`-compatible dict implementing the
        following logging contract:
            * JSON logs to stdout when in production
            * Human-readable colour logs when in development / test
            * Optional Sentry handler when configured
        """
        common_format = (
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s "
            "(context=%(request_id)s)"
        )
        if self.is_prod:
            handler_fmt = {
                "format": "%(message)s",
                "class": "pythonjsonlogger.jsonlogger.JsonFormatter",
            }
        else:
            handler_fmt = {"format": common_format}

        handlers: Dict[str, Dict] = {
            "console": {
                "class": "logging.StreamHandler",
                "level": "DEBUG" if self.debug else "INFO",
                "formatter": "json" if self.is_prod else "plain",
                "stream": "ext://sys.stdout",
            }
        }

        # Add Sentry handler only if DSN is set
        if self.monitoring.sentry_dsn:
            handlers["sentry"] = {
                "level": "WARNING",
                "class": "sentry_sdk.integrations.logging.EventHandler",
            }

        formatters = {
            "plain": {
                "format": common_format,
            },
            "json": handler_fmt,
        }

        return {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": formatters,
            "handlers": handlers,
            "root": {
                "handlers": list(handlers.keys()),
                "level": "DEBUG" if self.debug else "INFO",
            },
        }

    # ------------------------------------------------------------------ #
    # Serialisation                                                      #
    # ------------------------------------------------------------------ #
    def as_dict(self, redact_secrets: bool = True) -> Dict:
        """
        Serialise the settings as a dict, optionally redacting secret values
        such as passwords or DSNs for safe logging.
        """
        def _filter(value):
            if redact_secrets and isinstance(value, SecretStr):
                return "***"
            if isinstance(value, BaseModel):
                return value.dict()
            return value

        return {k: _filter(v) for k, v in self.__dict__.items()}


# --------------------------------------------------------------------------- #
# Factory                                                                     #
# --------------------------------------------------------------------------- #
@lru_cache()
def get_settings() -> AppSettings:
    """
    Lazily instantiate and cache the global settings object.

    Cache is keyed by function arguments; calling `get_settings()` with no
    args will always return the same instance.
    """
    try:
        # If a config file exists, merge it.  If not, rely solely on env vars.
        if DEFAULT_CONFIG_FILE.exists():
            return AppSettings.from_yaml(DEFAULT_CONFIG_FILE)
        return AppSettings()
    except Exception as exc:  # pragma: no cover
        # Fail fast: configuration errors are unrecoverable at runtime
        print(f"[FATAL] Unable to load configuration: {exc}", file=sys.stderr)
        logging.exception("Configuration loading failed")
        raise


# --------------------------------------------------------------------------- #
# Convenience: instantiate module-level `settings` for easy imports           #
# --------------------------------------------------------------------------- #
settings: AppSettings = get_settings()


# --------------------------------------------------------------------------- #
# CLI entrypoint (optional)                                                   #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":  # pragma: no cover
    # Pretty-print current config for sanity checking
    import argparse
    import pprint

    parser = argparse.ArgumentParser(description="PulseStream Nexus configuration inspector.")
    parser.add_argument(
        "--show-secrets",
        action="store_true",
        help="Display secret values such as passwords (USE WITH CAUTION).",
    )

    args = parser.parse_args()
    pprint.pprint(settings.as_dict(redact_secrets=not args.show_secrets))
```