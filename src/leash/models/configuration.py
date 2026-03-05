"""Configuration models for Leash."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic.alias_generators import to_camel

from leash.models.handler_config import HandlerConfig


class GenericRestConfig(BaseModel):
    """Configuration for a generic REST LLM provider."""

    model_config = {"alias_generator": to_camel, "populate_by_name": True}

    url: str = ""
    headers: dict[str, str] = {}
    body_template: str = ""
    response_path: str = ""


class LlmConfig(BaseModel):
    """LLM provider configuration."""

    model_config = {"alias_generator": to_camel, "populate_by_name": True}

    provider: str = "claude-persistent"
    model: str = "opus"
    timeout: int = 15000
    command: str | None = None
    prompt_prefix: str | None = None
    prompt_suffix: str | None = None
    system_prompt: str | None = (
        "You are a security analyzer that evaluates the safety of operations. "
        "Always respond ONLY with valid JSON containing safetyScore (0-100), "
        "reasoning (string), and category (safe|cautious|risky|dangerous). "
        "Never include any text outside the JSON object."
    )
    api_key: str | None = None
    api_base_url: str | None = None
    generic_rest: GenericRestConfig | None = None


class ServerConfig(BaseModel):
    """Web server configuration."""

    model_config = {"alias_generator": to_camel, "populate_by_name": True}

    port: int = 5050
    host: str = "localhost"


class HookEventConfig(BaseModel):
    """Configuration for handlers under a specific hook event type."""

    model_config = {"alias_generator": to_camel, "populate_by_name": True}

    enabled: bool = True
    handlers: list[HandlerConfig] = []


class SessionConfig(BaseModel):
    """Session storage configuration."""

    model_config = {"alias_generator": to_camel, "populate_by_name": True}

    max_history_per_session: int = 50
    storage_dir: str = "~/.leash/sessions"


class SecurityConfig(BaseModel):
    """Security configuration."""

    model_config = {"alias_generator": to_camel, "populate_by_name": True}

    api_key: str | None = None
    rate_limit_per_minute: int = 600


class TriggerRule(BaseModel):
    """A webhook trigger rule."""

    model_config = {"alias_generator": to_camel, "populate_by_name": True}

    name: str = ""
    event: str = "*"
    url: str = ""
    method: str = "POST"


class TriggerConfig(BaseModel):
    """Webhook trigger configuration."""

    model_config = {"alias_generator": to_camel, "populate_by_name": True}

    enabled: bool = False
    rules: list[TriggerRule] = []


class ProfileConfig(BaseModel):
    """Profile configuration."""

    model_config = {"alias_generator": to_camel, "populate_by_name": True}

    active_profile: str = "moderate"
    custom_profiles: dict[str, Any] = {}


class TrayConfig(BaseModel):
    """System tray and notification configuration."""

    model_config = {"alias_generator": to_camel, "populate_by_name": True}

    enabled: bool = True
    show_in_observe: bool = False
    show_in_approve_only: bool = True
    interactive_timeout_seconds: int = 10
    sound: bool = False


class CopilotConfig(BaseModel):
    """Copilot integration configuration."""

    model_config = {"alias_generator": to_camel, "populate_by_name": True}

    enabled: bool = True
    hook_handlers: dict[str, HookEventConfig] = {}


class Configuration(BaseModel):
    """Root configuration for Leash."""

    model_config = {"alias_generator": to_camel, "populate_by_name": True}

    llm: LlmConfig = LlmConfig()
    server: ServerConfig = ServerConfig()
    hook_handlers: dict[str, HookEventConfig] = {}
    session: SessionConfig = SessionConfig()
    security: SecurityConfig = SecurityConfig()
    profiles: ProfileConfig = ProfileConfig()
    enforcement_enabled: bool = False
    enforcement_mode: str | None = None
    analyze_in_observe_mode: bool = True
    copilot: CopilotConfig = CopilotConfig()
    triggers: TriggerConfig = TriggerConfig()
    tray: TrayConfig = TrayConfig()
