"""Sequencing and rule engine for gravity-fed furrow irrigation changeovers.

The planner turns a field layout (tank, pipes, valves, outlets, furrows,
no-step zones, portable fittings) plus the current session state into an
ordered step list:

    预充主管 -> (关旧口 -> 移管 -> 开新口 -> 确认水头到尾)* -> 收尾

and enforces the safety rules:
  R1  same-branch changeover must close the old outlet before opening a new one
  R2  a furrow can only be completed after tail-end wetting is confirmed
  R3  opening a low outlet must not back-siphon an empty upstream pipe
  R4  the pipe-carrying route must not cross furrows still carrying water
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

STEP_TEXT = {
    "PREFILL_MAIN": "预充主管",
    "PREFILL_BRANCH": "预充分支管",
    "OPEN_OUTLET": "开畦口",
    "AWAIT_TAIL": "确认水头到尾",
    "CLOSE_OUTLET": "关畦口",
    "MOVE_PIPE": "移管",
    "FIX_ISSUE": "排除异常",
    "END_SESSION": "收尾",
}

ISSUE_TEXT = {
    "blocked": "堵沟",
    "leak": "漏接",
    "no_tail": "水未到尾",
}

FURROW_BUFFER_M = 0.5          # half-width of a furrow when treated as obstacle
ACCESS_OFFSET_M = 1.2          # operator stand point offset from a valve
UPHILL_TOLERANCE_M = 0.05      # allowed rise along a gravity pipe run


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# graph helpers
# ---------------------------------------------------------------------------

def build_graph(nodes: list[dict], pipes: list[dict]):
    """Return (by_id, adjacency, tank, parent) where parent maps each node to
    its upstream neighbour on the BFS tree rooted at the tank."""
    by_id = {n["id"]: n for n in nodes}
    adj: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for p in pipes:
        if p["from_node"] in by_id and p["to_node"] in by_id:
            adj[p["from_node"]].append(p["to_node"])
            adj[p["to_node"]].append(p["from_node"])
    tanks = [n for n in nodes if n["type"] == "tank"]
    tank = tanks[0] if tanks else None
    parent: dict[str, Optional[str]] = {}
    if tank:
        parent[tank["id"]] = None
        queue = [tank["id"]]
        while queue:
            cur = queue.pop(0)
            for nb in adj[cur]:
                if nb not in parent:
                    parent[nb] = cur
                    queue.append(nb)
    return by_id, adj, tank, parent


def path_to_tank(node_id: str, parent: dict[str, Optional[str]]) -> list[str]:
    """Node ids from the tank down to node_id (empty if unreachable)."""
    if node_id not in parent:
        return []
    path = [node_id]
    while parent[path[-1]] is not None:
        path.append(parent[path[-1]])
    return list(reversed(path))


def branch_of(node_id: str, by_id: dict, parent: dict[str, Optional[str]]) -> str:
    """The branch valve feeding a node: nearest upstream valve, else 'main'."""
    cur = parent.get(node_id)
    while cur is not None:
        if by_id[cur]["type"] == "valve":
            return cur
        cur = parent.get(cur)
    return "main"


def branch_valve_of(branch: str) -> Optional[str]:
    return None if branch == "main" else branch


def pipe_between(pipes: list[dict], a: str, b: str) -> Optional[dict]:
    for p in pipes:
        if {p["from_node"], p["to_node"]} == {a, b}:
            return p
    return None


def path_capacity_l(pipes: list[dict], path: list[str]) -> float:
    total = 0.0
    for a, b in zip(path, path[1:]):
        p = pipe_between(pipes, a, b)
        if p:
            total += p["capacity_l"]
    return total


def path_max_rise(by_id: dict, path: list[str]) -> float:
    rise = 0.0
    for a, b in zip(path, path[1:]):
        rise = max(rise, by_id[b]["elevation"] - by_id[a]["elevation"])
    return rise


def order_furrows(furrows: list[dict], by_id: dict, parent) -> list[dict]:
    """Upstream-first ordering: branches by distance from tank, then outlets
    by descending elevation inside each branch."""

    def key(f):
        out = f["outlet_id"]
        hops = len(path_to_tank(out, parent))
        branch = branch_of(out, by_id, parent)
        branch_hops = hops if branch == "main" else len(path_to_tank(branch, parent))
        elev = by_id[out]["elevation"] if out in by_id else 0
        return (branch_hops, -elev, f["name"])

    return sorted(furrows, key=key)


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _seg_seg_dist(p1, p2, p3, p4) -> float:
    """Minimum distance between segments p1p2 and p3p4."""

    def pt_seg(p, a, b):
        ab = _sub(b, a)
        denom = _dot(ab, ab)
        t = 0.0 if denom == 0 else max(0.0, min(1.0, _dot(_sub(p, a), ab) / denom))
        c = (a[0] + ab[0] * t, a[1] + ab[1] * t)
        return math.hypot(p[0] - c[0], p[1] - c[1])

    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = orient(p3, p4, p1), orient(p3, p4, p2)
    d3, d4 = orient(p1, p2, p3), orient(p1, p2, p4)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 0.0
    return min(
        pt_seg(p1, p3, p4), pt_seg(p2, p3, p4),
        pt_seg(p3, p1, p2), pt_seg(p4, p1, p2),
    )


def _seg_rect_intersect(p1, p2, rect) -> bool:
    x, y, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    # either endpoint inside
    for p in (p1, p2):
        if x <= p[0] <= x + w and y <= p[1] <= y + h:
            return True
    edges = list(zip(corners, corners[1:] + corners[:1]))
    return any(_seg_seg_dist(p1, p2, a, b) == 0.0 for a, b in edges)


def access_point(node: dict) -> tuple[float, float]:
    d = ACCESS_OFFSET_M
    return {
        "N": (node["x"], node["y"] - d),
        "S": (node["x"], node["y"] + d),
        "E": (node["x"] + d, node["y"]),
        "W": (node["x"] - d, node["y"]),
    }[node.get("accessible_side", "S")]


def route_length(route: list[list[float]]) -> float:
    return sum(
        math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(route, route[1:])
    )


def check_route(route, furrow_segs, zones) -> list[str]:
    """Names of obstacles the route crosses."""
    hits = []
    for a, b in zip(route, route[1:]):
        for name, (p, q) in furrow_segs:
            if _seg_seg_dist(tuple(a), tuple(b), p, q) < FURROW_BUFFER_M:
                if name not in hits:
                    hits.append(name)
        for z in zones:
            if _seg_rect_intersect(tuple(a), tuple(b), z):
                label = z["label"] or "禁踩区"
                if label not in hits:
                    hits.append(label)
    return hits


def plan_route(a: tuple[float, float], b: tuple[float, float],
               furrow_segs, zones) -> tuple[list[list[float]], list[str]]:
    """Pick the first obstacle-free route among straight / L-shapes; fall back
    to the straight line and report what it crosses."""
    ax, ay = a
    bx, by = b
    candidates = [
        [[ax, ay], [bx, by]],
        [[ax, ay], [ax, by], [bx, by]],
        [[ax, ay], [bx, ay], [bx, by]],
    ]
    for cand in candidates:
        hits = check_route(cand, furrow_segs, zones)
        if not hits:
            return cand, []
    return candidates[0], check_route(candidates[0], furrow_segs, zones)


# ---------------------------------------------------------------------------
# session-state helpers
# ---------------------------------------------------------------------------

def empty_state() -> dict:
    return {
        "main_charged": False,
        "charged_branches": [],
        "open_outlet": None,   # outlet id currently discharging
        "hose_at": None,       # outlet id the portable hose is connected to
    }


def wet_furrow_segments(furrows: list[dict], by_id: dict,
                        exclude_outlets: set[str], now: datetime) -> list:
    """Furrows that still carry water and therefore block a carrying route."""
    segs = []
    for f in furrows:
        if f["outlet_id"] in exclude_outlets:
            continue
        wet = f["state"] in ("flowing", "tail_ok")
        if not wet and f["state"] == "done" and f.get("closed_at"):
            try:
                closed = datetime.fromisoformat(f["closed_at"])
                wet = (now - closed).total_seconds() < f["wet_max_min"] * 60
            except Exception:
                wet = False
        if wet and f["outlet_id"] in by_id:
            o = by_id[f["outlet_id"]]
            segs.append((f["name"], ((o["x"], o["y"]), (f["tail_x"], f["tail_y"]))))
    return segs


# ---------------------------------------------------------------------------
# step construction
# ---------------------------------------------------------------------------

def _step(seq: int, stype: str, payload: dict, warning: Optional[str] = None) -> dict:
    return {
        "id": new_id("st"),
        "seq": seq,
        "type": stype,
        "payload": payload,
        "status": "pending",
        "warning": warning,
        "activated_at": None,
    }


def build_steps(state: dict, furrows_todo: list[dict], nodes: list[dict],
                pipes: list[dict], furrows_all: list[dict], zones: list[dict],
                fittings: list[dict], flow_lpm: float,
                seq_start: int = 0) -> list[dict]:
    by_id, _, tank, parent = build_graph(nodes, pipes)
    now = datetime.now(timezone.utc)
    steps: list[dict] = []
    seq = seq_start

    def add(stype, payload, warning=None):
        nonlocal seq
        steps.append(_step(seq, stype, payload, warning))
        seq += 1

    if not state["main_charged"] and tank:
        cap = sum(p["capacity_l"] for p in pipes)
        add("PREFILL_MAIN", {
            "tank_id": tank["id"],
            "duration_min": round(cap / flow_lpm, 1) if flow_lpm else None,
        })

    hose_at = state.get("hose_at")
    open_outlet = state.get("open_outlet")
    charged = set(state.get("charged_branches", []))
    if state["main_charged"]:
        charged.add("main")

    for f in order_furrows(furrows_todo, by_id, parent):
        out_id = f["outlet_id"]
        out = by_id.get(out_id)
        branch = branch_of(out_id, by_id, parent)

        # R1: never open a new outlet while the old one is discharging.
        if open_outlet and open_outlet != out_id:
            prev = next((x for x in furrows_all if x["outlet_id"] == open_outlet), None)
            add("CLOSE_OUTLET", {"outlet_id": open_outlet,
                                 "furrow_id": prev["id"] if prev else None})
            open_outlet = None

        # 移管: carry the hose, R4 route check.
        if hose_at and hose_at != out_id:
            a = access_point(by_id[hose_at])
            b = access_point(out)
            segs = wet_furrow_segments(furrows_all, by_id, {hose_at, out_id}, now)
            route, hits = plan_route(a, b, segs, zones)
            total_hose = sum(ft["hose_length_m"] * ft["count"] for ft in fittings)
            warn = None
            if hits:
                warn = "携管路线跨越：" + "、".join(hits)
            if total_hose and route_length(route) > total_hose:
                warn = (warn + "；" if warn else "") + \
                    f"路线 {route_length(route):.1f}m 超出可携管件 {total_hose:.0f}m"
            add("MOVE_PIPE", {"from_outlet": hose_at, "to_outlet": out_id,
                              "route": route}, warn)
            hose_at = out_id
        elif not hose_at:
            hose_at = out_id

        # R3: a downhill branch must be charged before its low outlet opens.
        valve_id = branch_valve_of(branch)
        if branch not in charged and valve_id and out and \
                out["elevation"] < by_id[valve_id]["elevation"] - UPHILL_TOLERANCE_M:
            path = path_to_tank(out_id, parent)
            cap = path_capacity_l(pipes, path)
            add("PREFILL_BRANCH", {
                "valve_id": valve_id, "branch": branch,
                "duration_min": round(cap / flow_lpm, 1) if flow_lpm else None,
            })
            charged.add(branch)

        add("OPEN_OUTLET", {"outlet_id": out_id, "furrow_id": f["id"],
                            "branch": branch})
        add("AWAIT_TAIL", {"furrow_id": f["id"], "outlet_id": out_id,
                           "wet_min_min": f["wet_min_min"],
                           "wet_max_min": f["wet_max_min"]})
        open_outlet = out_id

    if open_outlet:
        last = next((x for x in furrows_all if x["outlet_id"] == open_outlet), None)
        add("CLOSE_OUTLET", {"outlet_id": open_outlet,
                             "furrow_id": last["id"] if last else None})
    if tank:
        add("END_SESSION", {"tank_id": tank["id"]})
    return steps


# ---------------------------------------------------------------------------
# human-readable step text (rendered at GET time so names stay fresh)
# ---------------------------------------------------------------------------

def step_text(step: dict, nodes_by_id: dict, furrows_by_id: dict) -> str:
    p = step["payload"]
    t = step["type"]

    def node_name(nid):
        n = nodes_by_id.get(nid or "")
        return (n["label"] or n["type"]) if n else "?"

    def furrow_name(fid):
        f = furrows_by_id.get(fid or "")
        return f["name"] if f else "?"

    if t == "PREFILL_MAIN":
        d = p.get("duration_min")
        return f"关闭全部畦口，开水池阀预充主管" + (f"约 {d} 分钟" if d else "")
    if t == "PREFILL_BRANCH":
        d = p.get("duration_min")
        return f"微开 {node_name(p.get('valve_id'))} 预充分支管，防低位倒吸" + \
            (f"约 {d} 分钟" if d else "")
    if t == "OPEN_OUTLET":
        return f"开畦口 {node_name(p.get('outlet_id'))}，供水 {furrow_name(p.get('furrow_id'))}"
    if t == "AWAIT_TAIL":
        return (f"观察 {furrow_name(p.get('furrow_id'))} 沟尾，"
                f"水头到尾后确认（{p.get('wet_min_min')}–{p.get('wet_max_min')} 分钟）")
    if t == "CLOSE_OUTLET":
        return f"关畦口 {node_name(p.get('outlet_id'))}"
    if t == "MOVE_PIPE":
        ln = route_length(p.get("route") or [])
        return (f"移管：{node_name(p.get('from_outlet'))} → "
                f"{node_name(p.get('to_outlet'))}（约 {ln:.1f}m）")
    if t == "FIX_ISSUE":
        return p.get("instruction") or "排除异常"
    if t == "END_SESSION":
        return "关水池阀，放空主管，收回软管"
    return t


# ---------------------------------------------------------------------------
# layout validation
# ---------------------------------------------------------------------------

def validate_layout(nodes: list[dict], pipes: list[dict],
                    furrows: list[dict]) -> list[str]:
    warnings: list[str] = []
    by_id, _, tank, parent = build_graph(nodes, pipes)
    if not tank:
        warnings.append("缺少水池：请放置一个水池节点")
    if len([n for n in nodes if n["type"] == "tank"]) > 1:
        warnings.append("水池只能有一个")
    for f in furrows:
        out = by_id.get(f["outlet_id"])
        if not out:
            warnings.append(f"畦沟 {f['name']} 的畦口不存在")
            continue
        if out["type"] != "outlet":
            warnings.append(f"畦沟 {f['name']} 必须挂在畦口节点上")
        if tank and f["outlet_id"] not in parent:
            warnings.append(f"畦沟 {f['name']} 的畦口与水池不连通")
        elif tank:
            rise = path_max_rise(by_id, path_to_tank(f["outlet_id"], parent))
            if rise > UPHILL_TOLERANCE_M:
                warnings.append(f"畦沟 {f['name']} 上游管段逆坡 {rise:.2f}m，重力无法送达")
            if out["elevation"] >= tank["elevation"]:
                warnings.append(f"畦沟 {f['name']} 的畦口不低于水池，无法自流")
        if f["tail_elevation"] > (out["elevation"] if out else 0):
            warnings.append(f"畦沟 {f['name']} 沟尾高于沟首，水无法到尾")
        if f["wet_min_min"] > f["wet_max_min"]:
            warnings.append(f"畦沟 {f['name']} 润湿时长下限大于上限")
    for n in nodes:
        if n["type"] == "outlet" and not any(f["outlet_id"] == n["id"] for f in furrows):
            warnings.append(f"畦口 {n['label'] or n['id']} 没有挂畦沟")
    return warnings
