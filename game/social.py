"""Observer-scoped social evidence. Truth labels are server-only."""
from __future__ import annotations
from .config import feature_enabled


def add_edge(state, source: str, target: str, edge_type: str, weight: int,
             *, visibility: str = "public", witnesses=None, genuine: bool = True):
    if not feature_enabled(state, "social_graph") or source not in state.people or target not in state.people:
        return None
    if edge_type not in {"accuse", "protect", "side", "grudge", "delegate", "alliance"}:
        raise ValueError("未知关系类型")
    if visibility not in {"public", "private", "rumor"}:
        raise ValueError("未知关系可见性")
    if not hasattr(state, "social_graph"):
        state.social_graph = []
    edge = {"source": source, "target": target, "type": edge_type,
            "weight": int(weight), "turn": state.turn, "visibility": visibility,
            "genuine": bool(genuine), "witnesses": list(dict.fromkeys(witnesses or [source, target]))}
    state.social_graph.append(edge)
    return edge


def visible_edges(state, observer_id: str) -> list[dict]:
    # A narrator may see allegations; it never gets the truth bit of an edge.
    if not feature_enabled(state, "social_graph"):
        return []
    result = []
    floor = state.flags.get("social_observer_since", {}).get(observer_id, 0)
    for edge in getattr(state, "social_graph", [])[floor:]:
        if edge.get("visibility") in {"public", "rumor"} or observer_id in edge.get("witnesses", []):
            result.append({key: edge[key] for key in ("source", "target", "type", "weight", "turn", "visibility")})
    return result


def summary(state, observer_id: str, limit: int = 12) -> list[str]:
    labels = {"accuse": "指控", "protect": "维护", "side": "站队支持", "grudge": "生怨",
              "delegate": "请其代言", "alliance": "约定相助"}
    rows = []
    for edge in visible_edges(state, observer_id)[-limit:]:
        source, target = state.people[edge["source"]], state.people[edge["target"]]
        prefix = "传闻：" if edge["visibility"] == "rumor" else "所见："
        rows.append(f"{prefix}{source.name}{labels[edge['type']]}{target.name}。")
    return rows
