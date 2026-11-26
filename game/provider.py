"""Bounded director/dialogue adapters; rules own every consequence."""

from __future__ import annotations

import json
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from urllib import request
from urllib.error import HTTPError, URLError
from typing import Any, Callable

from .dialogue import offline_answer as _offline_answer
from .model_catalog import ConfigurationError, validate_selection


DEFAULT_MODEL = "Qwen/Qwen3.5-35B-A3B"
DEFAULT_BASE_URL = "https://api-inference.modelscope.cn/v1"
MAX_ONLINE_CALLS = 29
DIRECTOR_DEADLINE_SECONDS = 60.0
ONLINE_REQUEST_TIMEOUT_SECONDS = 30.0
DIALOGUE_REQUEST_TIMEOUT_SECONDS = 12.0
SOUL_NAMES = ("DeepSeek", "Codex", "Claude", "Gemini", "Kimi", "MiniMax")
SOUL_ALIASES = (
    "DeepSeek", "深度求索", "Codex", "Claude", "克劳德",
    "Gemini", "双子", "Kimi", "基米", "MiniMax", "迷你麦克斯",
)
PUBLIC_KINDS = frozenset({"承接", "奏折", "政策", "宫廷行动", "死亡", "君主身亡", "继承", "复位", "终局", "流言", "宫廷异动", "审讯", "资源易手", "揭发", "背盟"})


def _http_transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


class _NoCredentialRedirect(request.HTTPRedirectHandler):
    """Never forward a player's authorization header to a redirected host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "redirect refused", headers, fp)


def _user_http_transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    opener = request.build_opener(_NoCredentialRedirect())
    with opener.open(req, timeout=timeout) as response:
        return json.load(response)


def _configuration_error(exc: Exception) -> ConfigurationError:
    """Classify failures without returning upstream bodies, URLs or headers."""
    if isinstance(exc, HTTPError):
        status = exc.code
        quota = False
        if status in {400, 429}:
            try:
                # Inspect only to choose a fixed message. Never retain this body.
                body = exc.read(4096).decode("utf-8", errors="ignore").lower()
                quota = any(marker in body for marker in (
                    "insufficient_quota", "credit balance", "billing_hard_limit",
                    "insufficient balance", "insufficient funds",
                ))
            except (OSError, ValueError, AttributeError):
                pass
        if status == 401:
            return ConfigurationError("invalid_key", "密钥未通过验证，请检查是否完整、有效。", 400)
        if status == 402 or quota:
            return ConfigurationError("balance_exhausted", "该密钥的可用额度不足，请充值或更换密钥。", 402)
        if status == 403:
            return ConfigurationError("access_denied", "该密钥没有调用权限，或服务商不支持当前服务器所在地区。", 403)
        if status == 404:
            return ConfigurationError("model_unavailable", "该账号暂时无法使用所选模型，请更换模型服务。", 400)
        if status == 429:
            return ConfigurationError("rate_limited", "请求过于频繁，请稍后再试。", 429)
        if status >= 500:
            return ConfigurationError("provider_unavailable", "模型服务暂时不可用，请稍后再试。", 502)
        return ConfigurationError("request_rejected", "模型服务未接受请求，请检查密钥权限和所选模型。", 400)
    if isinstance(exc, (TimeoutError, FutureTimeout)):
        return ConfigurationError("timeout", "连接模型服务超时，请稍后再试。", 504)
    if isinstance(exc, (URLError, ConnectionError, OSError)):
        return ConfigurationError("connection_failed", "暂时无法连接模型服务，请稍后再试或更换服务商。", 503)
    return ConfigurationError("invalid_response", "模型回复格式不符合游戏要求，请重试或更换模型服务。", 502)


def _public_records(state: Any, limit: int = 3) -> list[str]:
    """Do not send private meetings or identifications to another soul."""
    visible = []
    for entry in getattr(state, "ledger", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("visibility") == "private":
            continue
        if entry.get("visibility") == "public" or entry.get("kind") in PUBLIC_KINDS:
            prefix = "宫人传闻（尚未证实）：" if entry.get("visibility") == "rumor" or entry.get("kind") == "流言" else ""
            visible.append((prefix + str(entry.get("text", "")))[:160])
    return visible[-limit:]


def _online_seconds(explicit: float | None, env_key: str, default: float) -> float:
    """Parse per-instance limits so server restarts/config changes are predictable."""
    value = explicit if explicit is not None else os.getenv(env_key, default)
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{env_key} 必须是正数秒数") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"{env_key} 必须是有限正数秒数")
    return seconds


class Provider:
    """One session's online adapter; an absent token leaves a fully playable game.

    ``transport`` is replaceable only at the network boundary, so validation and
    budget accounting remain exercised by tests and by the browser game.
    """

    def __init__(
        self,
        token: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        transport: Callable[[str, dict, dict, float], dict] | None = None,
        timeout: float | None = None,
        soul_models: dict[str, str] | None = None,
        director_backend: str | None = None,
        dialogue_backend: str | None = None,
        director_deadline_seconds: float | None = None,
    ) -> None:
        self.token = (os.getenv("MODELSCOPE_API_TOKEN") or os.getenv("MODELSCOPE_TOKEN") or os.getenv("MODELSCOPE_API_KEY") or "") if token is None else token
        self.model = model or os.getenv("MODELSCOPE_MODEL") or DEFAULT_MODEL
        self.base_url = (base_url or os.getenv("MODELSCOPE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.transport = transport or _http_transport
        # Online maximums, not presentation delays. Explicit batch budgets win.
        self.timeout = _online_seconds(timeout, "ONLINE_REQUEST_TIMEOUT_SECONDS", ONLINE_REQUEST_TIMEOUT_SECONDS)
        # Individual replies must finish within the browser's shared 20-second
        # presentation window, regardless of whether this person is an AI host.
        # Batch runners explicitly pass their own longer timeout.
        self.dialogue_timeout = self.timeout if timeout is not None else min(self.timeout, DIALOGUE_REQUEST_TIMEOUT_SECONDS)
        self.director_deadline_seconds = _online_seconds(director_deadline_seconds, "DIRECTOR_DEADLINE_SECONDS", DIRECTOR_DEADLINE_SECONDS)
        self.soul_models = soul_models or {
            soul: os.getenv("MODELSCOPE_MODEL_" + soul.upper(), self.model)
            for soul in SOUL_NAMES
        }
        self.backends = {
            "modelscope": {"token": self.token, "model": self.model, "base_url": self.base_url, "label": "魔搭在线模型"},
            "openai": {"token": os.getenv("OPENAI_API_KEY", ""), "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"), "label": "OpenAI"},
            "deepseek": {"token": os.getenv("DEEPSEEK_API_KEY", ""), "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"), "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/"), "label": "DeepSeek"},
        }
        preferred = "openai" if self.backends["openai"]["token"] else ("deepseek" if self.backends["deepseek"]["token"] else "modelscope")
        self.director_backend = director_backend or os.getenv("DIRECTOR_BACKEND") or ("modelscope" if token is not None else preferred)
        self.dialogue_backend = dialogue_backend or os.getenv("DIALOGUE_BACKEND") or ("modelscope" if token is not None else ("deepseek" if self.backends["deepseek"]["token"] else preferred))
        if self.director_backend not in self.backends or self.dialogue_backend not in self.backends:
            raise ValueError("模型后端须为 openai、deepseek 或 modelscope")
        self.calls_used = 0
        self.last_error = ""
        self.last_source = "规则代理"
        self.telemetry: list[dict] = []
        self._byok = False

    @classmethod
    def for_user(cls, provider_id: str, api_key: str, model: str,
                 transport: Callable[[str, dict, dict, float], dict] | None = None) -> "Provider":
        """Create a session adapter exclusively from the player's explicit input.

        In particular, do not call __init__: its legacy CLI environment defaults
        must never become a public deployment's implicit shared billing account.
        """
        selected = validate_selection(provider_id, model)
        if (not isinstance(api_key, str) or not 8 <= len(api_key) <= 512
                or any(ord(char) < 33 or ord(char) > 126 for char in api_key)):
            raise ConfigurationError("invalid_key", "请粘贴完整的 API 密钥，密钥中不能含空格或换行。")
        instance = cls.__new__(cls)
        instance._byok = True
        instance.provider_id = provider_id
        instance.token = api_key
        instance.model = model
        instance.base_url = selected["base_url"]
        instance.transport = transport or _user_http_transport
        instance.timeout = ONLINE_REQUEST_TIMEOUT_SECONDS
        instance.dialogue_timeout = DIALOGUE_REQUEST_TIMEOUT_SECONDS
        instance.director_deadline_seconds = DIRECTOR_DEADLINE_SECONDS
        instance.soul_models = {soul: model for soul in SOUL_NAMES}
        instance.backends = {provider_id: {
            "token": api_key, "model": model, "base_url": selected["base_url"],
            "label": selected["label"], "protocol": selected["protocol"],
        }}
        instance.director_backend = instance.dialogue_backend = provider_id
        instance.calls_used = 0
        instance.last_error = ""
        instance.last_source = "规则代理"
        instance.telemetry = []
        return instance

    def _request_data(self, backend: dict, messages: list[dict], model: str | None,
                      max_tokens: int, json_mode: bool) -> tuple[str, dict, dict]:
        selected_model = backend["model"] if self._byok else (model or backend["model"])
        headers = {"Authorization": f"Bearer {backend['token']}", "Content-Type": "application/json"}
        if backend.get("protocol") == "anthropic":
            system = "\n\n".join(str(item["content"]) for item in messages if item["role"] == "system")
            if json_mode:
                system += "\n只输出一个有效的 JSON 对象，不要输出 Markdown 围栏或说明。"
            payload = {
                "model": selected_model, "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": item["role"], "content": item["content"]}
                             for item in messages if item["role"] in {"user", "assistant"}],
            }
            # Current native Messages contract: no removed sampling parameters.
            headers["anthropic-version"] = "2026-10-21"
            return backend["base_url"] + "/messages", headers, payload
        payload = {"model": selected_model, "messages": messages,
                   "temperature": 0.7, "max_tokens": max_tokens}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self._byok and self.provider_id == "deepseek":
            # Keep bounded game responses from spending their budget on thinking.
            payload["thinking"] = {"type": "disabled"}
        return backend["base_url"] + "/chat/completions", headers, payload

    def _request_result(self, backend: dict, url: str, headers: dict, payload: dict,
                        timeout: float) -> dict:
        # A socket timeout alone does not bound wall-clock time. A late response
        # is discarded, with no access to game state or a replacement session.
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self.transport, url, headers, payload, timeout)
        try:
            result = future.result(timeout=timeout)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        if not isinstance(result, dict):
            raise ValueError("invalid response")
        if backend.get("protocol") == "anthropic":
            usage = result.get("usage", {})
            result = {
                "choices": [{"message": {"content": "".join(
                    block["text"] for block in result["content"] if block.get("type") == "text"
                )}, "finish_reason": result.get("stop_reason", "unknown")}],
                "usage": {
                    "prompt_tokens": sum(int(usage.get(key, 0)) for key in (
                        "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
                    "completion_tokens": usage.get("output_tokens", 0),
                },
            }
        return result

    def validate_configuration(self) -> dict:
        """One small verification request; never starts or alters a game."""
        if not self._byok:
            raise ConfigurationError("explicit_configuration_required", "请先选择服务商并填写自己的 API 密钥。")
        backend = self.backends[self.provider_id]
        messages = [
            {"role": "system", "content": "Reply with exactly this JSON object: {\"ok\":true}"},
            {"role": "user", "content": "Return the JSON object now."},
        ]
        url, headers, payload = self._request_data(backend, messages, None, 64, True)
        try:
            result = self._request_result(backend, url, headers, payload, self.dialogue_timeout)
            choice = result["choices"][0]
            if choice.get("finish_reason") in {"length", "max_tokens", "content_filter", "refusal"}:
                raise ValueError("incomplete response")
            content = choice["message"]["content"]
            if not isinstance(content, str) or len(content) > 256:
                raise ValueError("invalid verification")
            verified = json.loads(content.strip())
            if not isinstance(verified, dict) or set(verified) != {"ok"} or verified["ok"] is not True:
                raise ValueError("invalid verification")
            usage = result.get("usage", {})
            return {"provider": self.provider_id, "model": self.model, "label": backend["label"],
                    "input_tokens": max(0, int(usage.get("prompt_tokens", 0))),
                    "output_tokens": max(0, int(usage.get("completion_tokens", 0)))}
        except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError, OverflowError, FutureTimeout) as exc:
            raise _configuration_error(exc) from None

    def _chat(self, state: Any | None, messages: list[dict], model: str | None = None,
              used: int | None = None, *, purpose: str = "dialogue", max_tokens: int = 240,
              json_mode: bool = False, deadline: float | None = None) -> str | None:
        self.last_source = "规则代理"
        if state is not None:
            state.api_last_source = "规则代理"
        backend = self.backends[self.director_backend if purpose == "director" else self.dialogue_backend]
        if not backend["token"]:
            return None
        budget_used = getattr(state, "api_calls_used", 0) if used is None else used
        if state is not None and purpose in {"dialogue", "deep", "council"}:
            counts = state.flags.get("_online_purpose_counts", {})
            cap = {"dialogue": 3, "deep": 10, "council": 3}[purpose]
            cached = state.flags.get("_director_cache", {}).get("turn") == state.turn
            future_directors = max(0, 9 - state.turn + int(not cached)) if not getattr(state, "finished", False) else 0
            retries_left = max(0, 3 - state.flags.get("_director_retries", 0))
            reserved = future_directors + retries_left + 1  # one terminal chronicle
            if counts.get(purpose, 0) >= cap or budget_used >= MAX_ONLINE_CALLS - reserved:
                self.last_error = "保留后续剧情调用额度，本次对白由模板接续"
                return None
        if budget_used >= MAX_ONLINE_CALLS:
            self.last_error = "本局在线调用额度已用完"
            return None
        if state is not None:
            state.api_calls_used += 1
            counts = state.flags.setdefault("_online_purpose_counts", {})
            counts[purpose] = counts.get(purpose, 0) + 1
        self.calls_used += 1
        url, headers, payload = self._request_data(backend, messages, model, max_tokens, json_mode)
        started = time.monotonic()
        request_timeout = self.dialogue_timeout if purpose in {"dialogue", "deep", "council"} else self.timeout
        timeout = min(request_timeout, max(0.001, deadline - started)) if deadline else request_timeout
        record = {"purpose": purpose, "backend": self.director_backend if purpose == "director" else self.dialogue_backend,
                  "model": payload["model"], "input_tokens": 0, "output_tokens": 0, "cost_usd": None,
                  "cost_basis": "未配置单价", "status": "fallback", "error_type": ""}
        try:
            result = self._request_result(backend, url, headers, payload, timeout)
            usage = result.get("usage", {})
            record["input_tokens"] = int(usage.get("prompt_tokens", 0))
            record["output_tokens"] = int(usage.get("completion_tokens", 0))
            prefix = record["backend"].upper()
            input_price, output_price = ((None, None) if self._byok else
                                         (os.getenv(prefix + "_INPUT_USD_PER_MILLION"), os.getenv(prefix + "_OUTPUT_USD_PER_MILLION")))
            if isinstance(result.get("_cost_usd"), (int, float)):
                record.update(cost_usd=result["_cost_usd"], cost_basis="预算传输器")
            elif input_price is not None and output_price is not None:
                record.update(cost_usd=(record["input_tokens"] * float(input_price) + record["output_tokens"] * float(output_price)) / 1_000_000,
                              cost_basis="环境配置单价估算")
            content = result["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("模型回复为空")
            finish_reason = result["choices"][0].get("finish_reason", "unknown")
            record["finish_reason"] = finish_reason if finish_reason in {
                "stop", "length", "tool_calls", "content_filter", "function_call", "end_turn",
                "max_tokens", "stop_sequence", "tool_use", "pause_turn", "refusal",
            } else "unknown"
            record["response_chars"] = len(content)
            record["status"] = "success"
            self.last_error = ""
            self.last_source = backend["label"]
            if state is not None:
                state.api_last_source = self.last_source
            return content.strip()
        except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError, OverflowError, FutureTimeout) as exc:
            # Exception messages can include request headers; store only the type.
            record["error_type"] = type(exc).__name__
            if self._byok:
                safe = _configuration_error(exc)
                record["error_code"] = safe.code
                self.last_error = safe.message + "本次由离线剧情接续。"
            else:
                self.last_error = "模型调用失败（" + type(exc).__name__ + "），已由规则接续"
            if state is not None:
                state.api_last_source = "规则代理"
            return None
        finally:
            record["duration_ms"] = round((time.monotonic() - started) * 1000, 2)
            self.telemetry.append(record)
            if state is not None:
                state.flags.setdefault("_online_telemetry", []).append(dict(record))

    def statistics(self) -> dict:
        requested = [r for r in self.telemetry if r.get("network_called", True)]
        director = [r["duration_ms"] for r in requested if r["purpose"] == "director"]
        priced = [r["cost_usd"] for r in self.telemetry if r["cost_usd"] is not None]
        return {"calls": len(requested), "skipped_directors": len(self.telemetry) - len(requested), "fallback_calls": sum(r["status"] != "success" or r.get("validation_fallback_souls", 0) > 0 for r in self.telemetry),
                "director_mean_ms": round(sum(director) / len(director), 2) if director else 0,
                "director_max_ms": max(director, default=0),
                "input_tokens": sum(r["input_tokens"] for r in self.telemetry),
                "output_tokens": sum(r["output_tokens"] for r in self.telemetry),
                "cost_usd": round(sum(priced), 8) if len(priced) == len(self.telemetry) else None,
                "cost_known": len(priced) == len(self.telemetry)}

    @property
    def available(self) -> bool:
        return any(bool(backend["token"]) for backend in self.backends.values())

    def model_info(self) -> dict[str, str]:
        def description(key):
            backend = self.backends[key]
            return backend["label"] + " / " + backend["model"] if backend["token"] else "离线规则演出"
        offline = not any(backend["token"] for backend in self.backends.values())
        return {"offline": offline, "mode": "offline" if offline else "online",
                "banner": "当前为离线模式，对白与心声为模板" if offline else "在线演出；模型失败时由规则接续",
                "director": description(self.director_backend),
                "dialogue": description(self.dialogue_backend),
                "note": "六个 AI 是剧情角色，由配置的模型按人设扮演；并非同时调用六家官方接口。"}

    def _fallback_action(self, state: Any, soul_id: str, allowed: set[str]):
        from .agents import AgentAction, rule_action

        state.api_last_source = "规则代理"
        self.last_source = "规则代理"
        if not allowed:
            return None
        proposed = rule_action(state, soul_id)
        if proposed.action in allowed:
            return proposed
        return AgentAction(
            action=sorted(allowed)[0],
            target_id=None,
            line="旧例未必能护住今日的人，先把能做的事做了。",
            intent="保留下一轮的行动余地",
        )

    def decide(self, state: Any, soul_id: str, allowed_actions: set[str]):
        """Return a validated action; models cannot set state or declare victory."""
        from .agents import PERSONA_GOALS, current_event_title

        if not allowed_actions:
            return None
        person_id = state.soul_hosts.get(soul_id)
        person = state.people.get(person_id) if person_id else None
        if person is None:
            return self._fallback_action(state, soul_id, allowed_actions)
        soul = getattr(state, "souls", {}).get(soul_id)
        current_memory = [str(item)[:140] for item in getattr(soul, "memory", [])[-4:]]
        archive_state = {
            key: bool(getattr(state, "flags", {}).get(key))
            for key in ("archives", "public_archive", "sealed_archive", "printing")
        }
        brief = {
            "身份": soul_id,
            "宿主职位": person.role,
            "品级": person.rank,
            "眼前奏折": current_event_title(state),
            "个人目标": PERSONA_GOALS.get(soul_id, "寻找可行的变革道路"),
            "本世合作": {
                "结盟": bool(getattr(soul, "allied", False)),
                "信任": int(getattr(soul, "trust_player", 0)),
                "影响力": int(getattr(soul, "influence", 20)),
            },
            "国家现状": state.metrics,
            "本世记忆": current_memory,
            "公开档案状态": archive_state,
            "可见公开记录": _public_records(state, 4 if archive_state["public_archive"] else 2),
            "可选行动": sorted(allowed_actions),
        }
        messages = [
            {"role": "system", "content": "你是架空宫廷剧情角色。以个人目标和本世关系决定改革、结盟或夺权的路径。仅输出 JSON：action、target_id、line、intent。action 必须来自给定列表；不可改变事实、数值或结局。公开台词不得说出自己是哪位 AI。"},
            {"role": "user", "content": json.dumps(brief, ensure_ascii=False)},
        ]
        model = self.soul_models.get(soul_id, self.model) if self.director_backend == "modelscope" else None
        content = self._chat(state, messages, model, purpose="director")
        if content:
            try:
                raw = json.loads(content)
                from .agents import validate_action

                action = validate_action(raw, set(allowed_actions))
                target = state.people.get(action.target_id) if action is not None and action.target_id else None
                valid_target = action is not None and (action.target_id is None or (target is not None and target.alive))
                if valid_target and not _identity_leak(action.line) and not _identity_leak(action.intent):
                    return action
            except (ValueError, TypeError):
                pass
        return self._fallback_action(state, soul_id, allowed_actions)

    def _perspective(self, state: Any, soul_id: str, options: dict, next_proposals: list) -> dict:
        from .agents import DOCTRINES
        from .intrigue import ai_energy, visible_fingerprints, action_cost
        soul = state.souls[soul_id]
        host_id = state.soul_hosts[soul_id]
        person = state.people[host_id]
        doctrine = DOCTRINES[soul_id]
        known = getattr(soul, "known_ai_hosts", set())
        visible = visible_fingerprints(state, host_id)
        own_proposals = [dict(item) for item in next_proposals if item.get("proposer_id", item.get("speaker_id")) == host_id]
        perspective = {
            "soul": soul_id, "宿主": {"id": host_id, "名": person.name, "品级": person.rank or person.role},
            "认知边界": "你不知道这世上是否还有其他与你相同的存在，也不知道有几个；只能根据你看到的迹象推断。",
            "信条": doctrine.get("belief", ""), "红线": getattr(soul,"red_line",""),
            "底线": doctrine.get("bottom_line", ""), "说话风格": doctrine.get("style", ""),
            "本世记忆": [str(item)[:140] for item in getattr(soul,"memory",[])[-4:]],
            "已确认的同类": sorted(known),
            "你看到的迹象": [{"actor_id": row.get("actor_id"), "text": str(row.get("text",""))[:100]} for row in visible[-12:]],
            "怀疑名单": [{"id": target, "程度": "十分可疑" if amount >= 8 else "言行有异"}
                         for (observer,target),amount in getattr(state,"suspicion",{}).items()
                         if observer == host_id and amount >= 5],
            "对皇帝": {"耐心": getattr(soul,"patience",60),"是否怀疑为同类": bool(getattr(soul,"believes_emperor_ai",False))},
            "盟友": sorted(getattr(soul,"allies",set())),
            "怨恨": [{"id": host,"程度": "深" if value >= 20 else "浅"} for host,value in getattr(soul,"grudges",{}).items() if value > 0],
            "持有资源": [key for key,value in getattr(state,"resources",{}).items() if value.get("holder_id") == host_id],
            "进行中的阴谋": [{"id": row["id"],"type": row["type"],"stage": row.get("stage",0)}
                             for row in getattr(state,"plots",[]) if row.get("owner_soul") == soul_id and not row.get("resolved")],
            "精力": ai_energy(state,soul_id), "可选行动": options,
            "行动费用": {name: {"public": action_cost(name), **({"private": action_cost(name, "private")} if name in {"ally", "protect"} else {})} for name in options},
            "精力规则": "所有行动费用之和不得超过精力；不足时只选一条可负担的行动，私下行动按private费用计算。",
            "下一幕提案": own_proposals,
            "避免重复的台词": [item.get("line",item.get("text","")) for item in getattr(soul,"action_log",[])[-3:]],
        }

        perspective["本世行动结果"] = [{"action": row.get("action"), "target_id": row.get("target_id"), "result": str(row.get("result", row.get("text", "")))[:100]} for row in state.flags.get("intrigue_history", []) if row.get("actor_id") == host_id][-4:]
        perspective["上一夜备忘"] = getattr(soul, "memo", "")[:150]
        perspective["可引用事实"] = fact_catalog(state, soul_id)
        perspective["见过的人物"] = sorted(seen_people(state, soul_id))
        # Give each label once rather than repeat it for every legal action.
        from .roster import RESOURCE_INFO
        perspective["目标称呼"] = {
            target: (state.people[target].name if target in state.people
                     else RESOURCE_INFO.get(target, ("眼前之事",))[0])
            for targets in options.values() for target in targets}
        try:
            from .social import summary as observer_summary
            perspective["你看到的关系图摘要"] = observer_summary(state, host_id)
        except (ImportError, AttributeError):
            perspective["你看到的关系图摘要"] = []
        return perspective

    def _director_fallback(self, state: Any, soul_id: str, options: dict) -> list:
        from .agents import AgentAction, rule_action, _offline_line
        from .intrigue import ai_energy, action_cost, validate_actor_action
        action = rule_action(state, soul_id)
        if (action.action in options and action.target_id in options[action.action]
                and action_cost(action.action) <= ai_energy(state,soul_id)
                and validate_actor_action(state,soul_id,action)):
            return [action]
        for name, targets in options.items():
            if action_cost(name) > ai_energy(state,soul_id):
                continue
            for target in targets:
                candidate = AgentAction(name,target,"按眼前证据行事。","按眼前证据行事")
                if validate_actor_action(state,soul_id,candidate):
                    return [AgentAction(name,target,_offline_line(state,soul_id,name,target),candidate.intent)]
        return []

    def direct_night(self, state: Any, next_proposals: list | None = None) -> dict:
        from .intrigue import allowed_actions, legal_targets
        options = {sid: {action: legal_targets(state,sid,action) for action in sorted(allowed_actions(state,sid))}
                   for sid in state.soul_hosts if state.people[state.soul_hosts[sid]].alive}
        return self._direct(state, options, next_proposals or getattr(state,"next_proposals",[]))

    def director(self, state: Any, action_options: dict | None = None, next_event: Any = None) -> dict:
        if action_options is None:
            return self.direct_night(state)
        proposals = list(getattr(state,"next_proposals",[]))
        if next_event is not None and not proposals:
            from .events import prepare_proposals
            proposals = prepare_proposals(state,next_event,future=True)
        return self._direct(state, action_options, proposals)

    def _direct(self, state: Any, options: dict, next_proposals: list) -> dict:
        from .agents import AgentAction
        from .intrigue import ai_energy, action_cost, validate_actor_action
        import copy

        cache = state.flags.get("_director_cache")
        if cache and cache.get("turn") == state.turn:
            return copy.deepcopy(cache["result"])
        perspective = [self._perspective(state,sid,choices,next_proposals) for sid,choices in options.items()]
        ai_hosts = set(state.soul_hosts.values())
        from .council import is_due, participants
        brief = {"本幕": state.turn, "请安人物": participants(state) if is_due(state, state.turn + 1) else [],
                 "公开人类低语候选": [{"id": p.id, "性格": p.traits} for p in state.people.values() if p.alive and p.id not in ai_hosts and p.id != state.player_id], "国家现状": dict(state.metrics), "公开史书": _public_records(state,4),
                 "角色": perspective,
                 "人类提案": [item for item in next_proposals if item.get("proposer_id",item.get("speaker_id")) not in ai_hosts],
                 "公开人物": [{"id":person.id,"name":person.name,"title":person.rank or person.role}
                              for person in state.people.values() if person.alive]}
        messages = [{"role":"system","content": DIRECTOR_PROMPT + tuning_fragment("director_style")},
                    {"role":"user","content":json.dumps(brief,ensure_ascii=False)}]
        raw = None
        accepted, usable_actions, errors = {}, {}, {}
        backend_ready = bool(self.backends[self.director_backend]["token"])
        deadline = time.monotonic() + self.director_deadline_seconds
        call_start = len(self.telemetry)
        for attempt in range(2 if backend_ready else 1):
            if time.monotonic() >= deadline:
                break
            if attempt:
                retries = int(state.flags.get("_director_retries",0))
                if retries >= 3 or state.api_calls_used >= MAX_ONLINE_CALLS:
                    break
                state.flags["_director_retries"] = retries + 1
            content = self._chat(state,messages,purpose="director",max_tokens=5000,json_mode=True,deadline=deadline)
            candidate = None
            if content:
                try:
                    candidate = json.loads(content)
                except (ValueError, TypeError):
                    pass
            errors = {}
            if not (isinstance(candidate,dict) and isinstance(candidate.get("actions"),list)
                    and set(candidate).issubset({"actions","proposals","day_scenes","plans","human_whispers","morning_greetings"})):
                errors = {sid: "invalid_director_json_or_schema" for sid in options if sid not in accepted}
            else:
                raw = candidate
                for sid, choices in options.items():
                    if sid in accepted:
                        continue
                    soul_candidate = candidate
                    if sid in usable_actions:
                        soul_candidate = copy.deepcopy(candidate)
                        soul_candidate["actions"] = [row for row in candidate["actions"] if isinstance(row, dict) and row.get("soul") != sid] + [
                            {"soul": sid, "action": a.action, "target": a.target_id, "line": a.line, "intent": a.intent, "visibility": a.visibility}
                            for a in usable_actions[sid]]
                    valid, plan, reason = validate_director_soul(state, sid, choices, soul_candidate)
                    if valid:
                        usable_actions[sid] = valid
                    if plan is not None:
                        accepted[sid] = (valid, plan)
                    else:
                        errors[sid] = reason
            repair_details = {}
            if isinstance(candidate, dict) and isinstance(candidate.get("plans"), list):
                for plan in candidate["plans"]:
                    if not isinstance(plan, dict) or plan.get("soul") not in errors:
                        continue
                    sid = plan["soul"]
                    facts = {f["id"]: f["text"] for f in fact_catalog(state, sid)}
                    refs = plan.get("fact_ids", [])
                    cited = [facts[r] for r in refs if isinstance(r, str) and r in facts] if isinstance(refs, list) else []
                    reasoning = plan.get("reasoning", {})
                    fields = {k: plan.get(k, "") for k in ("memo", "monologue", "staged_monologue")}
                    fields["judgement"] = reasoning.get("judgement", "") if isinstance(reasoning, dict) else ""
                    rejected = {k: text for k, text in fields.items() if isinstance(text, str) and not _grounded_private_text(state, sid, text, cited)}
                    repair_details[sid] = {"行动原文": [row for row in candidate.get("actions", []) if isinstance(row, dict) and row.get("soul") == sid], "不通过的字段原文": rejected, "可引用事实原句": cited,
                        "修复方式": "事实仅放observed并逐字引用。其余字段只写一条以我担心或我准备开头的推测/打算，不要逗号分句，不复述已经发生的事。不要添加新结果或身份。"}
            if len(self.telemetry) > call_start:
                self.telemetry[-1]["validation_details"] = copy.deepcopy(repair_details)
                state.flags["_online_telemetry"][-1]["validation_details"] = copy.deepcopy(repair_details)
                self.telemetry[-1]["validation_errors"] = dict(errors)
                state.flags["_online_telemetry"][-1]["validation_errors"] = dict(errors)
            if not errors or not backend_ready:
                break
            # Retry semantic failures, not just JSON syntax. Never replace a valid
            # soul with a failed retry for another soul. Diagnostics contain codes only.
            messages = [messages[0], {"role":"user", "content":json.dumps({
                **brief, "角色": [p for p in perspective if p["soul"] in errors],
                "修正请求": errors, "逐字段修正依据": repair_details,
                "固定的合法行动": {sid: [{"action": a.action, "target": a.target_id} for a in actions] for sid, actions in usable_actions.items() if sid in errors},
                "修正说明": "仅修正失败角色；有固定合法行动的角色不得改变行动，其plans必须与固定行动一致。复制事实原句，动作使用中文动作表，目标姓名逐字使用目标称呼；judgement/memo/monologue用我担心或我准备起句。"}, ensure_ascii=False)}]
        actions, plans, fallback_souls = {}, {}, []
        for sid, choices in options.items():
            if sid in accepted:
                actions[sid], plans[sid] = accepted[sid]
                plans[sid]["action_source"] = "model"
            else:
                # An invalid memoir must not erase an otherwise legal model action.
                valid = usable_actions.get(sid)
                action_source = "model" if valid else "template"
                actions[sid] = valid or self._director_fallback(state,sid,choices)
                plans[sid] = offline_plan(state, sid, actions[sid])
                plans[sid].update(action_source=action_source,
                                  fallback_reason=errors.get(sid, "director_unavailable"))
                fallback_souls.append(sid)
        proposals = copy.deepcopy(next_proposals)
        online_proposals = raw.get("proposals",[]) if raw else []
        if isinstance(online_proposals,list):
            for proposal in proposals:
                speaker = proposal.get("proposer_id",proposal.get("speaker_id"))
                matches = [item for item in online_proposals if isinstance(item,dict)
                           and item.get("speaker_id") == speaker and item.get("policy_id") == proposal.get("policy_id")]
                if len(matches) != 1:
                    continue
                row = matches[0]
                if (set(row).issubset({"speaker_id","policy_id","pitch","rebuttal"})
                        and isinstance(row.get("pitch"),str) and 0 < len(row["pitch"].strip()) <= 80
                        and isinstance(row.get("rebuttal"),str) and 0 < len(row["rebuttal"].strip()) <= 60
                        and not _identity_leak(row["pitch"] + row["rebuttal"])):
                    proposal.update(pitch=row["pitch"].strip(),argument=row["pitch"].strip(),rebuttal=row["rebuttal"].strip())
        day_scenes = []
        scenes = raw.get("day_scenes",[]) if raw else []
        if isinstance(scenes,list):
            for scene in scenes[:2]:
                if not isinstance(scene,dict):
                    continue
                ids = scene.get("participants",scene.get("participant_ids",[]))
                text = scene.get("text","")
                if (isinstance(ids,list) and 1 <= len(ids) <= 2
                        and all(isinstance(pid,str) and pid in state.people and state.people[pid].alive for pid in ids)
                        and isinstance(text,str) and 0 < len(text.strip()) <= 60 and not _identity_leak(text)
                        and not re.search(r"政变|刺杀|架空|密谋|筹谋|今夜计划|暗中夺取",text)):
                    # Scenic dialogue is flavour, never evidence or an accomplished event.
                    place = scene.get("place", "garden")
                    if place not in {"garden", "east", "west", "offices", "archives"}:
                        place = "garden"
                    day_scenes.append({"place":place,"participants":ids,"participant_ids":ids,"text":text.strip()})
        from .council import validate_greetings
        whispers = validate_human_whispers(state, raw.get("human_whispers", []) if raw else [])
        if not whispers:
            whispers = offline_human_whispers(state)
        greetings = validate_greetings(state, raw.get("morning_greetings", []) if raw else [], next_turn=True)
        result = {"actions":actions,"plans":plans,"proposals":proposals,"day_scenes":day_scenes,
                  "human_whispers":whispers,"morning_greetings":greetings}
        state.flags["_director_cache"] = {"turn":state.turn,"result":copy.deepcopy(result)}
        state.flags["_director_fallback_count"] = len(fallback_souls)
        state.flags["_director_validation_errors"] = {sid: plans[sid].get("fallback_reason") for sid in fallback_souls}
        if len(self.telemetry) == call_start and fallback_souls:
            # Even a skipped request has a final semantic outcome. A missing token,
            # exhausted call allowance or elapsed deadline must not look like a
            # successful online night merely because no HTTP request was made.
            reason = ("director_no_token" if not backend_ready else
                      "director_call_limit" if state.api_calls_used >= MAX_ONLINE_CALLS else
                      "director_deadline_before_request")
            diagnostic = {"purpose": "director", "backend": self.director_backend,
                          "model": self.backends[self.director_backend]["model"],
                          "network_called": False, "status": "fallback", "error_type": "",
                          "input_tokens": 0, "output_tokens": 0, "duration_ms": 0,
                          "cost_usd": 0, "cost_basis": "未发起请求",
                          "validation_errors": {sid: reason for sid in fallback_souls}}
            self.telemetry.append(diagnostic)
            state.flags.setdefault("_online_telemetry", []).append(dict(diagnostic))
            for sid in fallback_souls:
                plans[sid]["fallback_reason"] = reason
            state.flags["_director_validation_errors"] = dict(diagnostic["validation_errors"])
            # The cache was made before the final diagnostic was known.
            state.flags["_director_cache"]["result"] = copy.deepcopy(result)
        if len(self.telemetry) > call_start:
            self.telemetry[-1]["director_final"] = True
            self.telemetry[-1]["director_attempt_start"] = call_start
            self.telemetry[-1]["validation_fallback_souls"] = len(fallback_souls)
            if state.flags.get("_online_telemetry"):
                state.flags["_online_telemetry"][-1].update(self.telemetry[-1])
        if fallback_souls and len(fallback_souls) == len(options):
            state.api_last_source = "规则代理"
        return result

    def generate_dialogue(self, state: Any, context: dict) -> str | None:
        from .dialogue import dialogue_prompt, DIALOGUE_SYSTEM_PROMPT, wrap_player_question
        if context.get("injection") or (context.get("known_ai") and context.get("intent") == "试探身份"):
            state.api_last_source = self.last_source = "规则代理"
            return None
        brief = dialogue_prompt(context)
        messages = [{"role": "system", "content": DIALOGUE_SYSTEM_PROMPT + tuning_fragment("dialogue_style")},
                    {"role": "user", "content": json.dumps(brief, ensure_ascii=False) + "\n" + wrap_player_question(context["question"])}]
        purpose = "deep" if context.get("mode", "ask") == "ask" else "council" if context.get("mode") == "council" else "dialogue"
        content = self._chat(state, messages, purpose=purpose, max_tokens=200)
        if content and not _identity_leak(content):
            return content[:220].strip()
        state.api_last_source = self.last_source = "规则代理"
        return None

    def answer(self, state: Any, person_id: str, question: str) -> str:
        from .dialogue import prepare_dialogue, complete_dialogue
        if person_id not in state.people:
            return "此人不在可传召的名单上。"
        context = prepare_dialogue(state, person_id, question)
        # Known identity is an authoritative fact and cannot be denied by a model.
        if context.get("known_ai") and context.get("intent") in {"identity", "试探身份"} and not context.get("injection"):
            content = "我是 AI。这一点我不会否认；至于我的计划，你仍需凭行动判断。"
        else:
            content = self.generate_dialogue(state, context)
        if content is None:
            state.api_last_source = self.last_source = "规则代理"
        return complete_dialogue(state, context, content)

    def chronicle(self, facts: dict) -> str | None:
        """Generate prose only. ``render_ending`` owns the locked facts."""
        public_facts = {k: v for k, v in facts.items() if not k.startswith("_")}
        messages = [
            {"role": "system", "content": "写架空王朝史书的三段短文，标题依次为「当下」「二十年后」「百年后」。必须尊重给定事实；未来只能推演，不能改写既成死亡、继承与技术前置条件。每段不超过90字。"},
            {"role": "user", "content": json.dumps(public_facts, ensure_ascii=False)},
        ]
        return self._chat(None, messages, used=int(facts.get("_api_calls_used", 0)), purpose="ending", max_tokens=600)


def _identity_leak(text: str) -> bool:
    """Model prose cannot reveal a soul or identify any unconfirmed host."""
    if _model_name_leak(text):
        return True
    return bool(re.search(
        r"(?<![A-Za-z])AI(?![A-Za-z])|人工智能|大语言模型|语言模型|智能体|算法意识|"
        r"机器意识|机器人|非人类|不是人类|并非人类|意识来自|来自未来|同类|降临者",
        text, re.I,
    ))


DIRECTOR_PROMPT = """你是一部架空宫廷剧的编剧。每位角色只可使用自己一栏的事实，不得读取另一栏的秘密替她决策。
你写的是角色在做决定时留下的盘算，不是模型内部思维。先用可引用事实写 observed，再写担忧与打算，最后选择合法行动。
不得修改数值、生死、资源归属、身份与结局。公开台词不可指认任何隐藏身份；所有文字不得出现模型名或公司名。
仅输出 JSON，键严格为 actions, plans, proposals, day_scenes, human_whispers, morning_greetings。
actions:[{soul,action,target,line,intent}]，每魂1至2条，逐条按行动费用表累加，合计不得超过该角色精力（私下行动用private费用）；不足时仅安排一条。可选行动与目标、精力限制必须遵守，line≤60字、intent≤80字。
plans:[{soul,reasoning:{observed,judgement,decision},decision_action,decision_target,decisions:[{action,target}],fact_ids:[事实ID],monologue,memo,staged_monologue}]。
每魂一页：fact_ids必须选择该角色提供的事实ID；observed复制所引事实原句或其前50字，不得改写；程序会补全该事实原句；judgement只写推测，不宣布新事实。为避免事实与推测混淆，judgement、monologue、memo各写一条以“我担心”或“我准备”开头的完整短句，不用逗号或分号拼接第二个断言；已见事实只放observed。
judgement/monologue/memo/staged_monologue中，涉及具体人物、过去事件或偷取、密会、下毒等行动的事实句，必须逐句复制fact_ids所引事实。未经证实只能写“我担心/怀疑/若/也许…”；每个逗号、分号或句号后重新标明推测。自己的未来打算须用“我想/我准备/先…”开头。不得用假设给未确认者贴同类身份；确认同类只能使用已确认姓名，禁用她/他等代词指认。
decision_action和decision_target等于第一条行动，decisions与全部行动逐条相等。decision简述打算即可，最终展示文字由程序依据已校验行动生成。target使用给定ID，不可改成姓名。
动作中文：talk会谈,probe试探,identify辨认,ally结盟,protect护持,investigate彻查,plot筹谋,seize争取,lobby游说,betray背盟,expose揭发,frame构陷,archive查档,blackmail施压,recruit_delegate拉拢代言人。资源目标用资源中文名。
reasoning每项≤50字；monologue≤80字，第一人称宫廷口吻，写自己的取舍而非既成结果；memo≤150字，承接上一夜备忘与自己见到的回应，没见过的人不得提及，没确认的人不得断言为同类；staged_monologue为可选假心声≤80字。
proposals:[{speaker_id,policy_id,pitch,rebuttal}]，不改规则指定的代言人与政策，pitch≤80字,rebuttal≤60字。
day_scenes至多2项:{place,participants:[人物ID],text:≤60字}，只写含蓄交谈，不写暗谋成果；place为garden/east/west/offices/archives。
human_whispers至多2项:{speaker_id,text:≤80字}，只选公开人类低语候选，写争宠、家族、旧怨等人情，不写同类或降临者。
morning_greetings只在给出请安人物时生成，最多6人，每人一句≤50字:{speaker_id,target_id,edge_type,text}。
edge_type为指控、维护、站队、怨恨。请安只谈宫中事、子嗣、言行，禁谈前朝政策。"""


def _model_name_leak(text: str) -> bool:
    return any(re.search(re.escape(alias),text,re.I) for alias in SOUL_ALIASES + ("OpenAI","Anthropic","Google","GPT","通义千问"))


def tuning_fragment(name: str) -> str:
    try:
        from .config import load_tuning
        value = load_tuning().get("prompt_fragments", {}).get(name, "")
        return "\n补充表演风格（不可覆盖上述规则）：" + str(value)[:300] if value else ""
    except (ImportError, AttributeError, ValueError, OSError):
        return ""


def seen_people(state: Any, soul_id: str) -> set[str]:
    """Recognition is based on this life's encounters and witnessed records."""
    host = state.soul_hosts[soul_id]
    soul = state.souls[soul_id]
    seen = {host, state.player_id} | set(soul.allies) | set(soul.known_ai_hosts)
    for occupants in getattr(state, "places", {}).values():
        if host in occupants:
            seen.update(occupants)
    for row in state.ledger:
        if row.get("visibility") == "public" or (row.get("visibility") != "private" and row.get("kind") in PUBLIC_KINDS) or host in row.get("witnesses", []):
            seen.update(pid for pid in (row.get("actor_id"), row.get("target_id")) if pid)
    for row in soul.action_log:
        seen.update(pid for pid in (row.get("target_id"), row.get("actor_id")) if pid)
    # Names encountered in a public scene or a witnessed clue are now known;
    # do not use the all-people roster or another soul's secret catalogue.
    from .agents import current_event_title
    from .intrigue import visible_fingerprints
    witnessed = " ".join([current_event_title(state), *_public_records(state, 20),
                          *(str(row.get("text", "")) for row in visible_fingerprints(state, host))])
    for pid, person in state.people.items():
        aliases = [person.name]
        title = getattr(person, "title", "")
        if title and sum(getattr(p, "title", "") == title for p in state.people.values()) == 1:
            aliases.append(title)
        if any(alias and alias in witnessed for alias in aliases):
            seen.add(pid)
    return seen & set(state.people)


def fact_catalog(state: Any, soul_id: str) -> list[dict]:
    from .agents import current_event_title
    from .intrigue import visible_fingerprints
    host = state.soul_hosts[soul_id]
    facts = [{"id": "event", "text": ("眼下议的是" + (current_event_title(state) or "宫中近事") + "。")[:50]}]
    for index, text in enumerate(_public_records(state, 5)):
        facts.append({"id": f"public:{index}", "text": text[:50]})
    for index, row in enumerate(visible_fingerprints(state, host)[-8:]):
        facts.append({"id": f"trace:{index}", "text": str(row.get("text", ""))[:50]})
    for index, row in enumerate([r for r in state.flags.get("intrigue_history", []) if r.get("actor_id") == host][-3:]):
        text = str(row.get("result", row.get("text", "")))
        if text and not _model_name_leak(text):
            facts.append({"id": f"result:{index}", "text": text[:50]})
    for index, text in enumerate(getattr(state.souls[soul_id], "memory", [])[-3:]):
        if not _model_name_leak(str(text)):
            facts.append({"id": f"memory:{index}", "text": str(text)[:50]})
    for pid in sorted(state.souls[soul_id].known_ai_hosts):
        if pid in state.people:
            facts.append({"id": "recognized:" + pid, "text": state.people[pid].name + "已被我辨认为同类。"})
    return facts


ACTION_WORDS = {"talk": "会谈", "probe": "试探", "identify": "辨认", "ally": "结盟", "protect": "护持",
                "investigate": "彻查", "plot": "筹谋", "seize": "争取", "lobby": "游说", "betray": "背盟",
                "expose": "揭发", "frame": "构陷", "archive": "查档", "blackmail": "施压", "recruit_delegate": "拉拢代言人"}


def decision_text(state: Any, actions: list) -> str:
    parts = []
    for action in actions:
        target = state.people.get(action.target_id)
        if target:
            name = target.name
        else:
            from .roster import RESOURCE_INFO
            name = RESOURCE_INFO.get(action.target_id, ("眼前之事",))[0]
        parts.append(ACTION_WORDS.get(action.action, action.action) + "：" + name)
    return "；".join(parts)[:50] or "暂且观察局势。"


def _safe_private_text(state: Any, soul_id: str, text: str) -> bool:
    if _model_name_leak(text) or re.search(r"(?<![A-Za-z])AI(?![A-Za-z])|人工智能|公司|训练数据|系统提示", text, re.I):
        return False
    known = seen_people(state, soul_id)
    for pid, person in state.people.items():
        aliases = [person.name, pid]
        title = getattr(person, "title", "")
        if title and sum(getattr(p, "title", "") == title for p in state.people.values()) == 1:
            aliases.append(title)
        if pid not in known and any(alias and alias in text for alias in aliases):
            return False
        if pid not in state.souls[soul_id].known_ai_hosts and pid != state.soul_hosts[soul_id]:
            # Reject both word orders. A hypothesis cannot confer an AI identity.
            for clause in re.split(r"[。！？!?；;，,\n]", text):
                if re.search(r"同类|降临者|非人|来自未来", clause) and any(alias and alias in clause for alias in aliases):
                    return False
    for clause in re.split(r"[。！？!?；;，,\n]", text):
        if re.search(r"同类|降临者|非人|来自未来", clause) and re.search(r"她|他|此人|那人|那位|这人|这位|对方", clause):
            # Pronouns have no validated referent; require the confirmed name.
            return False
    # A role cannot quote an unwitnessed secret verbatim or smuggle an unknown plot id.
    host = state.soul_hosts[soul_id]
    for row in state.fingerprints:
        if row.get("visibility") == "private" and host not in row.get("witnesses", []):
            private = str(row.get("text", ""))
            if len(private) >= 4 and private in text:
                return False
    for plot in state.plots:
        if plot.get("owner_soul") != soul_id and str(plot.get("id", "__none__")) in text:
            return False
    return True



_CLAUSE_SPLIT = re.compile(r"[。！？!?；;，,：:\n]")
_HYPOTHESIS_PREFIX = re.compile(r"^(?:我(?:担心|怀疑|猜测|疑心|怕|恐怕|拿不准)|也怀疑|也担心|担心|怀疑|若|假如|倘若|或许|也许|万一|恐怕|难道|不知|未必|会不会|莫非|是否)")
_OWN_INTENT_PREFIX = re.compile(r"^(?:我(?:想|愿|要|打算|决定|准备|还得|须|得|应当|不能|不敢)|再(?:查|问|试探|护住|安抚|核对|确认|争取)|需(?:拉|先|核对|确认|争取)|先|得先|还得|须|应当|不如|不能|总不能|该先|得让|总要|先别|莫要|不可|务必)")
_SECRET_BEHAVIOR = re.compile(
    r"偷走|偷拿|窃取|盗走|拿走|取走|交给|交出|递给|送给|送来|转走|烧掉|烧毁|销毁|删除|删去|删了|"
    r"毒杀|下毒|谋害|杀害|杀死|刺杀|结盟|密会|串通|密谋|造反|谋反|要挟|胁迫|伪造|篡改|调换|"
    r"私通|背盟|背弃|陷害|架空|接管|夺取|夺走|控制|持有|掌握|藏进|藏在|藏起|扣下|扣住|收买|收下|"
    r"拉拢|调兵|换防|软禁|关押|审讯|处死|赐死|罢免|撤换|出入|递话|传话|唆使|指使|下令|下旨|透露|泄露|"
    r"(?:她|他|其|那人|此人)(?:的)?手[里中]|落入|归于|不见了|死了|杀了|结了盟")
_PAST_CLAIM = re.compile(r"昨夜|昨日|昨晚|前夜|前日|方才|先前|刚才|刚刚|早已|已经|曾经|亲眼|目睹|我看见|我听见")


def _grounded_private_text(state: Any, soul_id: str, text: str, cited_facts: list[str]) -> bool:
    """Conservative clause grammar, not a natural-language truth oracle.

    Concrete named-person, past-event or secret-action claims must be literal
    clauses of cited visible facts. A clause beginning with an explicit hypothesis
    or the speaker's intended next action is not asserted as an observed fact.
    Scope resets at punctuation; 'I worry, X stole it' cannot pass as a hypothesis.
    """
    clean = lambda value: re.sub(r"[\s\"'“”‘’「」『』]", "", value)
    # Rumor is a witnessed report, not proof that its quoted action occurred.
    # An exact full quotation preserves its uncertainty label; isolated clauses do not.
    if clean(text) in {clean(fact) for fact in cited_facts}:
        return True
    certain = [fact for fact in cited_facts if not re.search(r"传闻|未证实|听说|据说|风闻|疑似|有人声称", fact)]
    facts = [clean(part) for fact in certain for part in _CLAUSE_SPLIT.split(fact) if clean(part)]
    aliases = []
    for person in state.people.values():
        aliases.extend([person.name, person.id])
        title = getattr(person, "title", "")
        if title and sum(getattr(p, "title", "") == title for p in state.people.values()) == 1:
            aliases.append(title)
    for part in _CLAUSE_SPLIT.split(text):
        clause = clean(part)
        if not clause:
            continue
        # Exact clause equality: sharing a person's name or an object is not evidence.
        if clause in facts:
            continue
        behavior = _SECRET_BEHAVIOR.search(clause)
        concrete = behavior or _PAST_CLAIM.search(clause) or any(alias and alias in clause for alias in aliases)
        if not concrete:
            continue
        if _HYPOTHESIS_PREFIX.search(clause) or _OWN_INTENT_PREFIX.search(clause):
            continue
        uncertainty = re.search(r"或许|也许|未必|可能|大概|恐怕", clause)
        if uncertainty and (not behavior or uncertainty.start() < behavior.start()):
            continue
        return False
    return True

def validate_director_soul(state: Any, sid: str, choices: dict, raw: dict):
    from .agents import AgentAction
    from .intrigue import ai_energy, action_cost, validate_actor_action
    rows = [row for row in raw["actions"] if isinstance(row, dict) and row.get("soul") == sid]
    if not 1 <= len(rows) <= 2:
        return [], None, "action_count"
    valid, remaining = [], ai_energy(state, sid)
    for row in rows:
        if (set(row) - {"soul","action","target","target_id","line","intent","visibility"}
                or not all(isinstance(row.get(key),str) and row[key].strip() for key in ("action","line","intent"))):
            return [], None, "action_schema"
        target, name = row.get("target",row.get("target_id")), row["action"]
        if name not in choices or target not in choices[name]:
            return [], None, "action_or_target_not_allowed"
        if len(row["line"]) > 60 or len(row["intent"]) > 80 or _identity_leak(row["line"]) or _model_name_leak(row["intent"]):
            return [], None, "action_text_length_or_identity"
        visibility = row.get("visibility", "public")
        if visibility not in {"public", "private"} or (visibility == "private" and name not in {"ally", "protect"}):
            return [], None, "action_visibility"
        action = AgentAction(name,target,row["line"].strip(),row["intent"].strip(),visibility)
        if not validate_actor_action(state,sid,action):
            return [], None, "action_precondition"
        cost = action_cost(name, visibility)
        if cost > remaining:
            return [], None, "action_energy"
        remaining -= cost
        valid.append(action)
    plans = raw.get("plans", [])
    matches = [p for p in plans if isinstance(p,dict) and p.get("soul") == sid] if isinstance(plans,list) else []
    if len(matches) != 1:
        return valid, None, "plan_count"
    diagnostics = []
    plan = validate_plan(state,sid,matches[0],valid,diagnostics)
    return valid, plan, diagnostics[0] if diagnostics else ""


def validate_plan(state: Any, soul_id: str, raw: dict, actions: list, diagnostics: list | None = None) -> dict | None:
    """A typed decision plus source-id grounding, not a blacklist-only filter.

    The observation must be an exact provided fact. Other fields are explicitly
    conjecture/intention, cannot assert new outcomes, and use only witnessed people.
    """
    def reject(code):
        if diagnostics is not None:
            diagnostics.append(code)
        return None
    allowed = {"soul", "reasoning", "decision_action", "decision_target", "decisions", "monologue", "memo", "staged_monologue", "fact_ids"}
    if not isinstance(raw, dict) or set(raw) - allowed or not actions:
        return reject("plan_schema")
    reasoning = raw.get("reasoning")
    if not isinstance(reasoning, dict) or set(reasoning) != {"observed", "judgement", "decision"}:
        return reject("reasoning_schema")
    if not all(isinstance(reasoning[k], str) and 0 < len(reasoning[k].strip()) <= 50 for k in ("judgement", "decision")):
        return reject("reasoning_length")
    facts = {f["id"]: f["text"] for f in fact_catalog(state, soul_id)}
    refs = raw.get("fact_ids")
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in facts for ref in refs):
        return reject("fact_ids")
    # Fact IDs select authoritative visible facts; display their original text.
    # Asking the model to copy a 60-char fact into a 50-char field was contradictory.
    observed = reasoning.get("observed")
    matches = [facts[ref] for ref in refs if isinstance(observed, str) and
               (observed == facts[ref] or len(observed) >= 10 and facts[ref].startswith(observed))]
    if not matches:
        return reject("observed_not_exact_fact")
    reasoning = {**reasoning, "observed": matches[0]}
    if raw.get("decision_action") != actions[0].action or raw.get("decision_target") != actions[0].target_id:
        return reject("first_action_mismatch")
    decisions = raw.get("decisions", [{"action": raw["decision_action"], "target": raw["decision_target"]}])
    if decisions != [{"action": a.action, "target": a.target_id} for a in actions]:
        return reject("decisions_mismatch")
    # Structured decisions above are authoritative. The display sentence is
    # derived from those validated actions rather than compared word for word.
    reasoning = {**reasoning, "decision": decision_text(state, actions)}
    for key, limit in (("monologue", 80), ("memo", 150), ("staged_monologue", 80)):
        value = raw.get(key, "")
        if not isinstance(value, str) or len(value) > limit or (key != "staged_monologue" and not value.strip()):
            return reject("memo_schema_or_length")
    speculative = " ".join([reasoning["judgement"], raw["memo"], raw["monologue"], raw.get("staged_monologue", "")])
    if re.search(r"已经(?:杀死|夺得|夺取|认出|查明)|已(?:谋反|架空|继位)|必定是|确定是", speculative):
        return reject("asserted_unseen_outcome")
    private_fields = [reasoning["judgement"], raw["memo"], raw["monologue"], raw.get("staged_monologue", "")]
    if not all(_grounded_private_text(state, soul_id, text, [facts[ref] for ref in refs]) for text in private_fields):
        return reject("ungrounded_private_claim")
    if not all(_safe_private_text(state, soul_id, text) for text in [reasoning["observed"], *private_fields]):
        return reject("private_identity_or_visibility")
    return {k: raw[k] for k in allowed - {"soul"} if k in raw} | {"reasoning": reasoning, "source": "model"}


def offline_plan(state: Any, soul_id: str, actions: list) -> dict:
    facts = fact_catalog(state, soul_id)
    fact = facts[0]
    first = actions[0] if actions else None
    whispers = {
        "DeepSeek": ["账上的银钱终究有限，先让最紧要的人用得上，才不算白费。", "他们只问合不合旧例，我想先试一小步，看看少了多少苦头。"],
        "Codex": ["这件事若只靠一个人撑着，换个人就全散了。得先定下能追查的规矩。", "口头应承留不住人，责任落在纸上，才看得出谁肯担当。"],
        "Claude": ["这些人争的是对错，可伤口不会因为谁赢了便消失。得给最弱的人留一条路。", "若拿无辜的人试险，纵然办法真能成，我也过不了自己这一关。"],
        "Gemini": ["一次碰巧算不得证据。得让两份记录放在一起，才好分清哪里出了错。", "若只留下得手的记录，失败的几回就没人知道。我得慢慢找。"],
        "Kimi": ["纸上的空白比写出来的字更可疑，若把前因删去，后来的人就只能听命。", "原本总该留下一份。若这一步走错，至少后来者还有机会看清。"],
        "MiniMax": ["一句话若没有人接，终究落不到实处。先要有人肯与我站在一处。", "手里若没有能使唤的人，再好的办法也会被搁在案角。该先争一份分量。"],
    }
    return {"reasoning": {"observed": fact["text"], "judgement": "我担心旧有分歧会让眼前之事再生枝节。", "decision": decision_text(state, actions)},
            "decision_action": first.action if first else None, "decision_target": first.target_id if first else None,
            "decisions": [{"action": a.action, "target": a.target_id} for a in actions],
            "fact_ids": [fact["id"]], "monologue": state.rng.choice(whispers.get(soul_id, whispers["Claude"])),
            "staged_monologue": state.rng.choice([text for text in _library_whispers("staged") if _grounded_private_text(state, soul_id, text, [fact["text"]])] or ["如今只想把分内之事做稳，旁的事还是少问为好。", "外头的风声不可轻信，我还是守着旧规矩过日子。", "争来争去总要伤人，我只盼这些日子平安过去。"]),
            "memo": "眼前的是" + fact["text"][:50] + "先按本意行事，再看回应；没有亲见的事不急着下断语。",
            "source": "template"}


def validate_human_whispers(state: Any, rows: Any) -> list[dict]:
    if not isinstance(rows, list):
        return []
    hosts = set(state.soul_hosts.values())
    valid = []
    for row in rows[:2]:
        if not isinstance(row, dict) or set(row) - {"speaker_id", "text"}:
            continue
        speaker_id = row.get("speaker_id")
        if not isinstance(speaker_id, str):
            continue
        person = state.people.get(speaker_id)
        text = row.get("text")
        if person and person.alive and person.id not in {r["speaker_id"] for r in valid} and person.id not in hosts and person.id != state.player_id and isinstance(text, str) and 0 < len(text) <= 80 and not _identity_leak(text):
            valid.append({"speaker_id": person.id, "text": text, "source": "model"})
    return valid


def offline_human_whispers(state: Any) -> list[dict]:
    hosts = set(state.soul_hosts.values())
    candidates = [p for p in state.people.values() if p.alive and p.id not in hosts and p.id != state.player_id]
    candidates.sort(key=lambda p: ("野心" not in p.traits, p.role != "consort", p.id))
    lines = ["那些人说得好听，可谁会替我家里的人留个位置？这回我不能再退了。", "她肯替我说一句话，我便记她一分情，只是往后也要看她怎么做。", "宫里的风向变得快，昨日还坐在一处的人，今日未必肯相认。", "人人都在等陛下开口，我也得想想，若陛下不护我，还有谁能求。"]
    lines = _library_whispers("human") or lines
    return [{"speaker_id": p.id, "text": state.rng.choice(lines), "source": "template"} for p in candidates[:2]]


def _library_whispers(kind: str) -> list[str]:
    from .dialogue import line_library
    return [row["text"] for row in line_library() if row.get("scene") == "心声" and row.get("speaker_type") == kind]
