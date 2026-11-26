"""Authenticated, expiring browser credentials; no plaintext persistence.

The server supplies a stable Fernet key from its deployment secrets. Browser
credentials are bound to a separate anonymous visitor ID so that creating a new
game or restarting the server does not itself invalidate remembered credentials.
Cookie attributes and visitor-ID creation belong to the HTTP layer.
"""

from __future__ import annotations

import hmac
import json
import re
from typing import Any


DEFAULT_TTL_SECONDS = 90 * 24 * 60 * 60
MAX_COOKIE_BYTES = 3000
_PROVIDERS = frozenset({"deepseek", "openai", "anthropic"})
_CONFIG_KEYS = frozenset({"provider", "model", "api_key"})
_VISITOR = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


def _config(value: Any) -> dict[str, str]:
    """Keep only the deliberately small credential schema, rejecting extras."""
    if not isinstance(value, dict) or set(value) != _CONFIG_KEYS:
        raise ValueError("密钥配置格式不正确。")
    provider, model, key = (value[k] for k in ("provider", "model", "api_key"))
    if not isinstance(provider, str) or provider not in _PROVIDERS:
        raise ValueError("模型服务商不受支持。")
    if not isinstance(model, str) or not _MODEL.fullmatch(model):
        raise ValueError("模型名称格式不正确。")
    # Keys are HTTP credentials. Reject whitespace/control characters rather
    # than allowing them to be replayed into outbound headers after restoration.
    if not isinstance(key, str) or not 8 <= len(key) <= 1800 or not all(
        33 <= ord(character) <= 126 for character in key
    ):
        raise ValueError("密钥格式不正确。")
    return {"provider": provider, "model": model, "api_key": key}


class CredentialVault:
    """Fernet-backed optional storage, disabled safely when not configured.

    No environment variables are read here. The caller must explicitly supply
    its deployment secret. Raw user keys and encrypted cookies must never be
    included in logs; this class only raises fixed, credential-free messages.
    """

    def __init__(self, secret: str | None = None,
                 ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ValueError("密钥保存期限必须为正整数秒。")
        self.ttl_seconds = ttl_seconds
        self._fernet = None
        self._invalid_token = ()
        if not isinstance(secret, str) or not secret:
            return
        try:
            from cryptography.fernet import Fernet, InvalidToken
        except ImportError:
            return
        try:
            self._fernet = Fernet(secret.encode("ascii"))
            self._invalid_token = (InvalidToken,)
        except (ValueError, TypeError, UnicodeError):
            # A bad server setting disables persistence; do not reflect it.
            self._fernet = None

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def seal(self, config: dict, visitor_id: str) -> str:
        if not self.available:
            raise ValueError("当前环境暂不支持保存密钥，请选择仅本次使用。")
        if not isinstance(visitor_id, str) or not _VISITOR.fullmatch(visitor_id):
            raise ValueError("浏览器凭证无效，请刷新页面后重试。")
        payload = {"version": 1, "visitor": visitor_id, "config": _config(config)}
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        token = self._fernet.encrypt(encoded).decode("ascii")
        if len(token) > MAX_COOKIE_BYTES:
            raise ValueError("密钥配置过长，无法记住，请选择仅本次使用。")
        return token

    def unseal(self, token: str, visitor_id: str) -> dict[str, str] | None:
        if not self.available or not isinstance(token, str) or not 1 <= len(token) <= MAX_COOKIE_BYTES:
            return None
        if not isinstance(visitor_id, str) or not _VISITOR.fullmatch(visitor_id):
            return None
        try:
            plaintext = self._fernet.decrypt(token.encode("ascii"), ttl=self.ttl_seconds)
            payload = json.loads(plaintext)
            if not isinstance(payload, dict) or set(payload) != {"version", "visitor", "config"}:
                return None
            if type(payload["version"]) is not int or payload["version"] != 1:
                return None
            if not isinstance(payload["visitor"], str) or not hmac.compare_digest(payload["visitor"], visitor_id):
                return None
            return _config(payload["config"])
        except self._invalid_token + (ValueError, TypeError, UnicodeError):
            return None
