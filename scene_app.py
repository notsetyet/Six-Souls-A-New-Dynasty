"""Local scene-game server. Hidden AI state never leaves the server session."""

from __future__ import annotations

import copy
import os
import re
import secrets
import threading
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr

from game.engine import (
    alliance_report,
    current_event,
    finish_turn,
    interrupt,
    run_day,
    run_night,
    start_turn,
    run_free_action, end_day, mark_person, respond_probe, resolve_tribunal,
    ACTION_COSTS, _validate_player_action, council_followup,
)
from game.provider import Provider
from game.roster import new_game, public_view
from game.state import GameState
from game.web_sessions import BrowserSessions
from game.model_catalog import ConfigurationError


ROOT = Path(__file__).resolve().parent
COOKIE_NAME = "six_souls_scene"


class NewRequest(BaseModel):
    seed: int | None = None
    skip_tutorial: bool = False


class ModelConfigRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=128)
    api_key: SecretStr = Field(min_length=8, max_length=1024)
    remember: bool = False


class DayRequest(BaseModel):
    person_id: str = ""
    policy_id: str
    intel_id: str = "listen"
    question: str | None = None
    identify: bool = False


class NightRequest(BaseModel):
    person_id: str
    action: str = "talk"
    question: str | None = None
    identify: bool = False
    visibility: str = "public"


class InterruptRequest(BaseModel):
    choice_id: str


class ActRequest(BaseModel):
    action: str
    target_id: str | None = None
    person_id: str | None = None
    place_id: str | None = None
    place: str | None = None
    target_ref: str | None = None
    resource_id: str | None = None
    question: str | None = None
    visibility: str = "public"


class CouncilRequest(BaseModel):
    person_id: str
    question: str


class MarkRequest(BaseModel):
    person_id: str
    mark: str = ""
    flag: str | None = None


class TrialRequest(BaseModel):
    target_id: str
    choice: str


class ProbeRequest(BaseModel):
    actor_id: str
    choice: str


def _dialogue_beats(lines: list[str], view: dict[str, Any]) -> list[dict[str, Any]]:
    """Attribute spoken lines using public names, never hidden soul identities."""
    result = []
    people = view["people"]
    for line in lines:
        tagged = re.match(r"^【([^】]+)】\s*(.*)$", line, re.S)
        label, text = (tagged.group(1), tagged.group(2)) if tagged else ("", line)
        speaker = None
        if label in {"皇帝", "你的决定", "御前叫停"}:
            speaker = next((p for p in people if p["id"] == view["player_id"]), None)
        elif label in {"翻牌子", "夜议"}:
            speaker = next((p for p in people if p["name"] == text), None)
        else:
            # Match only the speech introduction, not a person mentioned inside
            # someone else's words. Ordinary status messages remain narration.
            prefix = re.split(r"[：:]", text, maxsplit=1)[0]
            if len(prefix) < len(text) and len(prefix) <= 60:
                candidates = [p for p in people if p["name"] in prefix]
                if candidates and re.search(r"说|答|道|声音|开口|低语|一句|点头|摇头|皱眉|叹|搁下|奏折|摊开|退让|案上|提醒|按住|拦在|脱口|伏在|请安|问安|停在|站在", prefix):
                    speaker = max(candidates, key=lambda p: prefix.rfind(p["name"]))
        result.append({"text": text, "speaker_id": speaker["id"] if speaker else None,
                       "speaker_role": (speaker.get("title") or speaker.get("rank") or "宫中人") if speaker else "旁白",
                       "speaker_name": speaker["name"] if speaker else ""})
    meta = view.get("dialogue_meta") or {}
    for beat in result:
        if beat.get("speaker_id") == meta.get("speaker_id", meta.get("actor_id")):
            beat["tone"] = meta.get("tone", "")
            beat["slip_text"] = meta.get("slip_text", meta.get("slip", ""))
    return result


def _payload(state: GameState) -> dict[str, Any]:
    view = public_view(state)
    event = None
    if not state.finished:
        scene_event = current_event(state)
        policies = []
        for policy in scene_event.policies:
            proposal = next((p for p in state.proposals if p.get("policy_id") == policy.id), {})
            owner_id = proposal.get("proposer_id", proposal.get("speaker_id", ""))
            owner = state.people.get(owner_id)
            policies.append({"id": policy.id, "title": policy.title, "description": policy.description,
                             "proposer_id": owner_id, "proposer_name": owner.name if owner else "御前第三案",
                             "proposer_title": (owner.title or owner.rank) if owner else "皇权第三案",
                             "argument": proposal.get("argument", proposal.get("pitch", policy.description)),
                             "rebuttal": proposal.get("rebuttal", ""), "stance": proposal.get("stance", ""),
                             "consequence": policy.description})
        from game.story import TURN_THREAD, THREAD_NAMES
        thread_id = TURN_THREAD.get(state.turn, "")
        event = {"id": scene_event.id, "title": scene_event.title, "summary": scene_event.summary,
                 "pressure": scene_event.pressure, "policies": policies,
                 "thread_id": thread_id, "thread_label": THREAD_NAMES.get(thread_id, "")}
    availability = {}
    for person in view["people"]:
        if not person["alive"] or person["id"] == state.player_id:
            continue
        options = {}
        for action in state.unlocked_actions:
            if action not in ACTION_COSTS:
                continue
            reason = ""
            try:
                _validate_player_action(state, action, person["id"], night=state.phase == "night")
            except ValueError as error:
                reason = str(error)
            cost = ACTION_COSTS[action]
            available_energy = state.night_energy if state.phase == "night" else state.energy
            if not reason and cost > available_energy:
                reason = f"精力不足，需要 {cost} 点"
            options[action] = {"enabled": not bool(reason), "reason": reason, "cost": cost}
        availability[person["id"]] = options
    view["action_availability"] = availability
    beats = [line.strip() for line in state.last_scene.splitlines() if line.strip()]
    return {"view": view, "mode": view["mode"], "event": event, "beats": beats,
            "dialogue_beats": _dialogue_beats(beats, view),
            **{key: view[key] for key in ("court", "dawn", "probe", "tribunal", "resources", "traces", "energy", "places", "encounters", "unlocked_actions", "tutorial_tip", "player_marks")}}


def _json(body: dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status_code, headers={"Cache-Control": "no-store"})


def create_app(provider: Any = None, audit_observer: Callable[[GameState], None] | None = None,
               *, provider_factory=None, vault_secret=None, enabled_providers=None,
               secure_cookies=None, session_ttl_seconds=86400, max_sessions=512,
               max_online=4) -> FastAPI:
    app = FastAPI(title="六魂新朝 · 场景版", docs_url=None, redoc_url=None, openapi_url=None)
    sessions = BrowserSessions(provider=provider, provider_factory=provider_factory,
                               vault_secret=vault_secret if vault_secret is not None else os.getenv("BYOK_COOKIE_SECRET"),
                               enabled_providers=enabled_providers, secure_cookies=secure_cookies,
                               ttl_seconds=session_ttl_seconds, max_sessions=max_sessions,
                               max_online=max_online)

    @app.exception_handler(ConfigurationError)
    async def configuration_error(request, error):
        return _json({"error": error.message, "code": error.code}, error.status_code)

    @app.exception_handler(RequestValidationError)
    async def request_error(request, error):
        # FastAPI's default errors echo invalid input, potentially including API keys.
        return _json({"error": "输入格式不正确，请检查服务商、模型及密钥。" if
                      request.url.path.startswith("/api/model-config") else "输入格式不正确，请检查后重试。",
                      "code": "invalid_input"}, 422)

    @app.middleware("http")
    async def protect_requests(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            expected = os.getenv("APP_PUBLIC_ORIGIN", str(request.base_url).rstrip("/")).rstrip("/")
            if origin and origin != expected:
                return _json({"error": "请求来源不匹配，请在游戏页面内重试。", "code": "origin_denied"}, 403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return _json({"error": "请在游戏页面内操作。", "code": "origin_denied"}, 403)
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return _json({"error": "请求格式不正确。", "code": "invalid_input"}, 415)
            if len(await request.body()) > 16384:
                return _json({"error": "输入内容过长。", "code": "invalid_input"}, 413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'self' https://modelscope.cn https://www.modelscope.cn "
            "https://modelscope.ai https://www.modelscope.ai")
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def observe(state):
        if audit_observer is not None:
            audit_observer(copy.deepcopy(state))

    def require_session(request):
        item = sessions.get(request)
        if item is None:
            raise ConfigurationError("session_expired", "会话已失效，请刷新页面后重新开始。", 401)
        return item

    def payload(item, request):
        sessions.set_mode(item)
        result = _payload(item.state)
        result["model_config"] = sessions.config(item, request)
        return result

    def change(request, action, *, online=False):
        item = require_session(request)
        with item.lock:
            acquired = False
            if online and item.provider and item.provider.available:
                acquired = sessions.capacity.acquire(blocking=False)
                if not acquired:
                    raise ConfigurationError("busy", "当前在线请求较多，请稍后再试；进度未改变。", 503)
            try:
                candidate = copy.deepcopy(item.state)
                try:
                    action(candidate, item.provider)
                except ValueError as error:
                    return _json({"error": str(error)}, 400)
                item.state = candidate
                sessions.set_mode(item)
                observe(candidate)
                return sessions.response(item, request, payload(item, request))
            finally:
                if acquired:
                    sessions.capacity.release()

    @app.get("/api/state")
    def get_state(request: Request):
        item = sessions.get(request, create=True)
        with item.lock:
            return sessions.response(item, request, payload(item, request))

    @app.post("/api/new")
    def create_game(body: NewRequest, request: Request):
        item = sessions.get(request, create=True)
        with item.lock:
            item.state = new_game(body.seed, skip_tutorial=body.skip_tutorial)
            if item.provider:
                item.provider.last_error = ""
            item.notice = ""
            sessions.set_mode(item)
            start_turn(item.state)
            observe(item.state)
            return sessions.response(item, request, payload(item, request))

    @app.get("/api/model-config")
    def get_model_config(request: Request):
        item = require_session(request)
        with item.lock:
            return sessions.response(item, request, sessions.config(item, request))

    @app.post("/api/model-config")
    def save_model_config(body: ModelConfigRequest, request: Request):
        item = require_session(request)
        with item.lock:
            config = {"provider": body.provider, "model": body.model,
                      "api_key": body.api_key.get_secret_value().strip()}
            return sessions.configure(item, request, config, body.remember)

    @app.post("/api/model-config/restore")
    @app.post("/api/model-config/resume")
    def restore_model_config(request: Request):
        item = require_session(request)
        with item.lock:
            return sessions.restore(item, request)

    @app.post("/api/model-config/offline")
    def pause_model_config(request: Request):
        item = require_session(request)
        with item.lock:
            return sessions.pause(item, request)

    @app.post("/api/model-config/forget")
    def forget_model_config(request: Request):
        item = require_session(request)
        return sessions.forget(item, request)

    @app.post("/api/day")
    def play_day(body: DayRequest, request: Request):
        return change(request, lambda state, provider: run_day(
            state, body.person_id, body.policy_id, body.intel_id,
            body.question, body.identify, provider), online=True)

    @app.post("/api/act")
    def play_action(body: ActRequest, request: Request):
        return change(request, lambda state, provider: run_free_action(
            state, body.action, body.person_id, body.place, body.target_ref, body.question, provider,
            target_id=body.target_id, place_id=body.place_id, resource_id=body.resource_id,
            visibility=body.visibility), online=True)

    @app.post("/api/end_day")
    def finish_day(request: Request):
        return change(request, lambda state, _: end_day(state))

    @app.post("/api/mark")
    def save_mark(body: MarkRequest, request: Request):
        return change(request, lambda state, _: mark_person(state, body.person_id,
                      body.flag if body.flag is not None else body.mark))

    @app.post("/api/trial")
    @app.post("/api/tribunal")
    def trial(body: TrialRequest, request: Request):
        return change(request, lambda state, _: resolve_tribunal(state, body.target_id, body.choice))

    @app.post("/api/probe")
    def probe(body: ProbeRequest, request: Request):
        return change(request, lambda state, _: respond_probe(state, body.actor_id, body.choice))

    @app.post("/api/night")
    def play_night(body: NightRequest, request: Request):
        return change(request, lambda state, provider: run_night(
            state, body.person_id, body.question, body.identify, provider,
            action=body.action, visibility=body.visibility), online=True)

    @app.post("/api/council")
    def followup(body: CouncilRequest, request: Request):
        return change(request, lambda state, provider: council_followup(state, body.person_id,
                      body.question, provider), online=True)

    @app.post("/api/interrupt")
    def play_interrupt(body: InterruptRequest, request: Request):
        return change(request, lambda state, provider: interrupt(state, body.choice_id, provider), online=True)

    @app.post("/api/next")
    def next_turn(request: Request):
        return change(request, lambda state, provider: finish_turn(state, provider), online=True)

    @app.get("/api/report/{person_id}")
    def report(person_id: str, request: Request):
        item = require_session(request)
        with item.lock:
            return sessions.response(item, request, {"report": alliance_report(item.state, person_id)})

    app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")
    app.mount("/", StaticFiles(directory=ROOT / "scene_web", html=True, check_dir=False), name="scene")
    return app


# Public scene mode never discovers the owner's environment API keys.
app = create_app()


if __name__ == "__main__":
    import uvicorn
    print("离线体验可直接开始；在游戏顶部输入自己的 API Key 可开启 AI 模式。")
    uvicorn.run(app, host=os.getenv("SCENE_HOST", "127.0.0.1"),
                port=int(os.getenv("SCENE_PORT", "7864")), access_log=False)
