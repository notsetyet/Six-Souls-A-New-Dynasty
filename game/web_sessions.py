"""Anonymous browser sessions and BYOK credentials, separate from game/audit state."""
from __future__ import annotations

import copy
import os
import re
import secrets
import threading
import time
from collections import deque
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from .credential_vault import CredentialVault
from .model_catalog import ConfigurationError, public_catalog, validate_selection
from .provider import Provider
from .roster import new_game
from .engine import start_turn

SESSION_COOKIE = "six_souls_scene"
VISITOR_COOKIE = "six_souls_visitor"
CREDENTIAL_COOKIE = "six_souls_credential"
MODE_COOKIE = "six_souls_mode"
SESSION_HEADER = "X-Game-Session"
REMEMBER_SECONDS = 90 * 24 * 3600


@dataclass
class BrowserSession:
    id: str
    visitor_id: str
    state: Any
    provider: Any = None
    credential: dict | None = field(default=None, repr=False)
    paused: bool = False
    touched: float = field(default_factory=time.monotonic)
    notice: str = ""
    lock: Any = field(default_factory=threading.RLock, repr=False)
    checks: Any = field(default_factory=deque, repr=False)


class BrowserSessions:
    def __init__(self, *, provider=None, provider_factory=None, vault_secret=None,
                 enabled_providers=None, secure_cookies=None, ttl_seconds=86400,
                 max_sessions=512, max_online=4):
        self.items: dict[str, BrowserSession] = {}
        self.lock = threading.RLock()
        # Tombstones contain only anonymous visitor IDs, never credentials.
        # They also reject a late response replaying a cookie after deletion.
        self.revoked_visitors: dict[str, float] = {}
        self.capacity = threading.BoundedSemaphore(max_online)
        self.factory = provider_factory or Provider.for_user
        self.legacy_provider = provider  # explicit test/local injection only
        self.vault = CredentialVault(vault_secret)
        self.enabled = set(enabled_providers if enabled_providers is not None else
                           os.getenv("BYOK_ENABLED_PROVIDERS", "deepseek").split(","))
        self.enabled = {s.strip() for s in self.enabled if s.strip()}
        self.secure_cookies = secure_cookies
        self.ttl = ttl_seconds
        self.max_sessions = max_sessions

    def get(self, request: Request, *, create=False):
        token = request.headers.get(SESSION_HEADER)
        if token is None:
            token = request.cookies.get(SESSION_COOKIE, "")
        with self.lock:
            now = time.monotonic()
            for visitor, expires in list(self.revoked_visitors.items()):
                if expires <= now:
                    self.revoked_visitors.pop(visitor, None)
            for sid, item in list(self.items.items()):
                if now - item.touched > self.ttl and item.lock.acquire(blocking=False):
                    try:
                        if now - item.touched > self.ttl:
                            self.items.pop(sid, None)
                    finally:
                        item.lock.release()
            item = self.items.get(token)
            if item:
                item.touched = now
                return item
            if not create:
                return None
            if len(self.items) >= self.max_sessions:
                raise ConfigurationError("busy", "当前游玩人数较多，请稍后再试。", 503)
            visitor = request.cookies.get(VISITOR_COOKIE, "")
            if (not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", visitor)
                    or visitor in self.revoked_visitors):
                visitor = secrets.token_urlsafe(32)
            state = new_game()
            start_turn(state)
            item = BrowserSession(secrets.token_urlsafe(32), visitor, state,
                                  copy.deepcopy(self.legacy_provider),
                                  paused=request.cookies.get(MODE_COOKIE) == "offline")
            self.items[item.id] = item
            return item

    def saved(self, item, request):
        with self.lock:
            if self.revoked_visitors.get(item.visitor_id, 0) > time.monotonic():
                return None
        return self.vault.unseal(request.cookies.get(CREDENTIAL_COOKIE, ""), item.visitor_id)

    def config(self, item, request):
        saved = self.saved(item, request)
        configured = item.credential or saved or {}
        online = bool(item.provider and item.provider.available)
        meta = next((p for p in public_catalog(self.enabled) if p["id"] == configured.get("provider")), {})
        telemetry = item.state.flags.get("_online_telemetry", [])
        notice = item.notice
        if not notice and online and getattr(item.provider, "_byok", False):
            # BYOK providers expose fixed, safe messages, including skipped
            # requests at the per-game cap (which have no network telemetry).
            notice = getattr(item.provider, "last_error", "")
        if not notice and online and telemetry and any(r.get("status") != "success" or r.get("validation_fallback_souls", 0) for r in telemetry[-1:]):
            notice = "部分内容暂由预设对白接续。"
        if not notice and request.cookies.get(CREDENTIAL_COOKIE) and not saved:
            notice = "已保存的配置已失效，请重新输入密钥；当前进度不受影响。"
        return {
            "online": online,
            "provider": configured.get("provider", ""),
            "provider_label": meta.get("label", ""),
            "model": configured.get("model", ""),
            "key_hint": ("•••• " + configured["api_key"][-4:]) if configured else "",
            "remembered": bool(saved and (not item.credential or saved == item.credential)),
            "remember_available": self.vault.available,
            "restore_pending": bool(saved and not online and not item.paused and not item.credential),
            "can_resume": bool(not online and configured),
            "notice": notice,
            "providers": public_catalog(self.enabled),
            "usage": {"calls": item.state.api_calls_used,
                      "input_tokens": sum(r.get("input_tokens", 0) for r in telemetry),
                      "output_tokens": sum(r.get("output_tokens", 0) for r in telemetry)},
        }

    def set_mode(self, item):
        online = bool(item.provider and item.provider.available)
        item.state.flags["_mode"] = {
            "online": online,
            "label": "AI 模式 · 已开启 AI 自主对话" if online else
                     "离线模式：可以完整游玩；角色使用预设对白，尚未开启 AI 自主对话。",
        }

    def cookie(self, response, request, key, value, *, persistent=False, delete=False):
        secure = self.secure_cookies
        if secure is None:
            secure = request.url.scheme == "https" or os.getenv("APP_PUBLIC_ORIGIN", "").startswith("https://")
        response.set_cookie(key, value, max_age=0 if delete else REMEMBER_SECONDS if persistent else None,
                            path="/", secure=secure, httponly=True,
                            samesite="none" if secure else "lax")
        if secure:
            # Python <3.14 has no partitioned= argument. Scope this cookie to
            # the embedding top-level site without making it JavaScript-readable.
            headers = list(response.raw_headers)
            for n in range(len(headers) - 1, -1, -1):
                if headers[n][0] == b"set-cookie":
                    headers[n] = (headers[n][0], headers[n][1] + b"; Partitioned")
                    break
            response.raw_headers = headers

    def response(self, item, request, data, *, status=200):
        response = JSONResponse(data, status_code=status, headers={
            "Cache-Control": "no-store", SESSION_HEADER: item.id})
        self.cookie(response, request, SESSION_COOKIE, item.id)
        saved = self.saved(item, request)
        if (request.method == "GET" or not request.url.path.startswith("/api/model-config")) and saved and item.provider and item.credential == saved:
            # Sliding expiry only while a validated saved profile is in use.
            self.cookie(response, request, CREDENTIAL_COOKIE,
                        self.vault.seal(saved, item.visitor_id), persistent=True)
            self.cookie(response, request, VISITOR_COOKIE, item.visitor_id, persistent=True)
        return response

    def validate(self, item, config):
        validate_selection(config["provider"], config["model"])
        if config["provider"] not in self.enabled:
            raise ConfigurationError("provider_disabled", "此服务商尚未在当前部署环境开放，请选择其他服务商。", 400)
        now = time.monotonic()
        while item.checks and now - item.checks[0] > 60:
            item.checks.popleft()
        if len(item.checks) >= 5:
            raise ConfigurationError("rate_limited", "连接测试过于频繁，请一分钟后再试。", 429)
        if not self.capacity.acquire(blocking=False):
            raise ConfigurationError("busy", "当前连接较多，请稍后重试。", 503)
        item.checks.append(now)
        try:
            candidate = self.factory(config["provider"], config["api_key"], config["model"])
            candidate.validate_configuration()
            return candidate
        finally:
            self.capacity.release()

    def configure(self, item, request, config, remember):
        candidate = self.validate(item, config)
        # Prepare encryption before committing; failures must preserve the old configuration.
        sealed = self.vault.seal(config, item.visitor_id) if remember and self.vault.available else None
        item.provider, item.credential, item.paused = candidate, dict(config), False
        item.notice = "" if not remember or sealed else "当前环境暂不支持记住密钥，本次仍可使用 AI 模式。"
        self.set_mode(item)
        data = self.config(item, request)
        if not sealed:
            # The incoming cookie can still match the same key even though
            # this response is deleting it at the player's explicit choice.
            data["remembered"] = False
        response = self.response(item, request, data)
        self.cookie(response, request, MODE_COOKIE, "online", persistent=bool(sealed))
        if sealed:
            self.cookie(response, request, VISITOR_COOKIE, item.visitor_id, persistent=True)
            self.cookie(response, request, CREDENTIAL_COOKIE, sealed, persistent=True)
        else:
            self.cookie(response, request, CREDENTIAL_COOKIE, "", delete=True)
        return response

    def restore(self, item, request):
        config = item.credential or self.saved(item, request)
        if not config:
            raise ConfigurationError("missing_configuration", "没有可恢复的配置，请输入 API Key。", 400)
        candidate = self.validate(item, config)
        item.provider, item.credential, item.paused = candidate, dict(config), False
        item.notice = ""
        self.set_mode(item)
        response = self.response(item, request, self.config(item, request))
        saved = self.saved(item, request)
        remembered = bool(saved and saved == config)
        self.cookie(response, request, MODE_COOKIE, "online", persistent=remembered)
        if remembered:
            self.cookie(response, request, CREDENTIAL_COOKIE, self.vault.seal(config, item.visitor_id), persistent=True)
            self.cookie(response, request, VISITOR_COOKIE, item.visitor_id, persistent=True)
        return response

    def pause(self, item, request):
        item.provider, item.paused, item.notice = None, True, ""
        self.set_mode(item)
        data = self.config(item, request)
        response = self.response(item, request, data)
        self.cookie(response, request, MODE_COOKIE, "offline", persistent=bool(self.saved(item, request)))
        return response

    def forget(self, item, request):
        """Forget every active tab for this visitor without discarding games.

        Call without holding an item lock. Snapshot/revoke under the registry
        lock, then take item locks in one stable order outside the registry.
        Existing calls finish before deletion returns; no further use of their
        old provider or remembered cookie is possible afterward.
        """
        with self.lock:
            visitor = item.visitor_id
            self.revoked_visitors[visitor] = time.monotonic() + REMEMBER_SECONDS
            affected = {other.id: other for other in self.items.values()
                        if other.visitor_id == visitor}
            affected[item.id] = item
        with ExitStack() as locks:
            for other in sorted(affected.values(), key=lambda entry: entry.id):
                locks.enter_context(other.lock)
            with self.lock:
                # A concurrent deletion may already have rotated this group.
                # Do not erase a newly entered configuration with an old request.
                if item.visitor_id != visitor:
                    raise ConfigurationError("configuration_changed", "配置已经更新，请重新确认后再删除。", 409)
                # Cover cookies produced by a connection test that was already
                # in progress when this deletion first acquired the registry.
                self.revoked_visitors[visitor] = time.monotonic() + REMEMBER_SECONDS
                replacement = secrets.token_urlsafe(32)
                for other in affected.values():
                    if other.visitor_id != visitor:
                        continue
                    other.provider, other.credential = None, None
                    other.paused, other.notice = True, ""
                    other.visitor_id = replacement
                    self.set_mode(other)
            data = self.config(item, request)
            data["notice"] = ""
            response = self.response(item, request, data)
            self.cookie(response, request, MODE_COOKIE, "offline")
            self.cookie(response, request, CREDENTIAL_COOKIE, "", delete=True)
            self.cookie(response, request, VISITOR_COOKIE, "", delete=True)
            return response
