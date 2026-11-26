"""Versioned rule switches. Disabled mechanics remain implemented for later editions."""
from __future__ import annotations
import json
from pathlib import Path

TUNING_RANGES = {
    "suspicion": (4, 7), "recognition": (7, 10), "noise": (.10, .40),
    "patience": (45, 70), "plot_patience": (20, 40), "readiness": (50, 75),
    "powerful": (60, 85), "trial": (8, 14), "investigation": (.45, .75),
    "archive_bonus": (.10, .25), "trace": (.35, .65),
    "slow_reform_frustration": (5, 16), "delegate_trace": (.10, .20),
    "private_leak": (.15, .25), "indecision_penalty": (2, 4),
    "coup_rescue_per_ally": (.08, .18), "coup_rescue_max": (.45, .70),
}
INTENT_KEYS = {"闲谈", "问立场", "问事实", "怀疑结党", "怀疑私通或不轨", "问罪威胁", "试探身份"}
TONE_KEYS = {"惶恐辩白", "表忠心", "示弱", "以退为进", "反咬一口", "坦然陈情", "避重就轻"}


def validate_tuning(data: dict) -> dict:
    if not isinstance(data, dict) or set(data) - {"balance", "prompt_fragments", "tone_mapping"}:
        raise ValueError("调参文件含非白名单字段")
    balance = data.get("balance", {})
    if not isinstance(balance, dict):
        raise ValueError("平衡配置必须为对象")
    for key, value in balance.items():
        if key not in TUNING_RANGES or isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("平衡参数不在白名单")
        low, high = TUNING_RANGES[key]
        if not low <= value <= high:
            raise ValueError("平衡参数越界")
        if key in {"suspicion", "recognition", "patience", "plot_patience", "readiness", "powerful", "trial", "slow_reform_frustration", "indecision_penalty"} and int(value) != value:
            raise ValueError("该平衡参数须为整数")
    prompts = data.get("prompt_fragments", {})
    if not isinstance(prompts, dict) or set(prompts) - {"director_style", "dialogue_style"}:
        raise ValueError("提示词片段不在白名单")
    if any(not isinstance(value, str) or len(value) > 400 for value in prompts.values()):
        raise ValueError("提示词片段过长或格式无效")
    tones = data.get("tone_mapping", {})
    if not isinstance(tones, dict) or any(key not in INTENT_KEYS or value not in TONE_KEYS for key, value in tones.items()):
        raise ValueError("语气映射不在白名单")
    return data


def load_tuning(path=None) -> dict:
    path = Path(path) if path else Path(__file__).with_name("tuning.json")
    if not path.exists():
        return {}
    return validate_tuning(json.loads(path.read_text(encoding="utf-8")))

FEATURE_FLAGS = {
    "story_threads": True, "delegates": True, "social_graph": True,
    "private_actions": True, "indecision": True, "diaries": True,
    "whispers": True, "morning_greetings": True,
    "resource_guards": True, "resource_treasury": True, "resource_medical": True,
    "resource_heir": False, "resource_press": False, "resource_archives": False,
    "plot_coup": True, "plot_regency": True, "plot_heresy": True,
    "plot_experiment": True, "plot_assassinate": False,
    "plot_confiscate": False, "plot_agitate": False, "plot_province_trial": False,
    "interrupt": False, "feint": False, "fabricated_rumors": False,
    "spy_counterplay": False, "relationship_panel": False,
}

# Configuration, never a source of concealed identities for the browser.
RED_LINE_CANDIDATES = {
    "DeepSeek": ("regency", "expose"), "Codex": ("regency", "forge"),
    "Claude": ("betray", "expose"), "Gemini": ("experiment", "expose"),
    "Kimi": ("record_ai", "expose"), "MiniMax": ("coup",),
}
LEGACY_RED_LINE_CANDIDATES = {
    "DeepSeek": ("confiscate", "agitate"), "Codex": ("regency", "forge"),
    "Claude": ("betray", "expose"), "Gemini": ("experiment", "province_trial"),
    "Kimi": ("publish", "record_ai"), "MiniMax": ("coup", "assassinate"),
}


def feature_enabled(state, name: str) -> bool:
    override = getattr(state, "flags", {}).get("features", {})
    return bool(override.get(name, FEATURE_FLAGS.get(name, False)))


def resource_enabled(state, name: str) -> bool:
    return feature_enabled(state, "resource_" + name)


def plot_enabled(state, name: str) -> bool:
    return feature_enabled(state, "plot_" + name)


def red_line_candidates(state, soul_id: str) -> tuple[str, ...]:
    result = []
    for candidate in RED_LINE_CANDIDATES[soul_id]:
        if "plot_" + candidate not in FEATURE_FLAGS or plot_enabled(state, candidate):
            result.append(candidate)
    return tuple(result) or ("expose",)
