"""Small, reviewed BYOK allowlist. This is not a live service-availability claim.

Official references checked 2026-11-26:
https://api-docs.deepseek.com/
https://developers.openai.com/api/docs/models/gpt-4.1-mini
https://platform.claude.com/docs/en/models/haiku-4-5/overview
https://platform.claude.com/docs/en/api/migration-2026-10-21
Deployment policy controls which entries are offered; arbitrary hosts are not accepted.
"""

from copy import deepcopy


class ConfigurationError(ValueError):
    """A deliberately public error: never construct it from upstream exception text."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


MODEL_CATALOG = {
    "deepseek": {
        "label": "DeepSeek", "base_url": "https://api.deepseek.com",
        "protocol": "openai", "default_model": "deepseek-flash",
        "models": [{"id": "deepseek-flash", "label": "DeepSeek Flash"}],
    },
    "openai": {
        "label": "OpenAI · GPT", "base_url": "https://api.openai.com/v1",
        "protocol": "openai", "default_model": "gpt-4.1-mini",
        "models": [{"id": "gpt-4.1-mini", "label": "GPT-4.1 mini"}],
    },
    "anthropic": {
        "label": "Claude", "base_url": "https://api.anthropic.com/v1",
        "protocol": "anthropic", "default_model": "claude-haiku-4-5-20251001",
        "models": [{"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5"}],
    },
}


def validate_selection(provider_id: str, model: str) -> dict:
    entry = MODEL_CATALOG.get(provider_id) if isinstance(provider_id, str) else None
    if entry is None:
        raise ConfigurationError("unsupported_provider", "请选择列表中的模型服务商。")
    if not isinstance(model, str) or model not in {item["id"] for item in entry["models"]}:
        raise ConfigurationError("unsupported_model", "请选择该服务商支持的模型。")
    return deepcopy(entry)


def public_catalog(enabled=None) -> list[dict]:
    """Only public UI fields; no endpoint override or credential data."""
    enabled = set(MODEL_CATALOG) if enabled is None else set(enabled)
    return [{"id": key, "label": entry["label"], "default_model": entry["default_model"],
             "models": deepcopy(entry["models"]), "enabled": key in enabled,
             "unavailable_reason": "" if key in enabled else "此部署暂未开放该服务商。"}
            for key, entry in MODEL_CATALOG.items()]
