"""End-to-end smoke test of the changeover console rules and replanning."""
import os
import tempfile

os.environ["IRRIGATION_DB"] = tempfile.mktemp(suffix=".db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
SID = None

LAYOUT = {
    "nodes": [
        {"id": "T", "type": "tank", "label": "水池", "x": 5, "y": 30,
         "elevation": 8, "accessible_side": "S"},
        {"id": "V", "type": "valve", "label": "总阀", "x": 20, "y": 30,
         "elevation": 7.8, "accessible_side": "S"},
        {"id": "J1", "type": "junction", "label": "", "x": 10, "y": 14,
         "elevation": 7.6, "accessible_side": "S"},
        {"id": "J2", "type": "junction", "label": "", "x": 20, "y": 28,
         "elevation": 7.5, "accessible_side": "S"},
        {"id": "J3", "type": "junction", "label": "", "x": 30, "y": 14,
         "elevation": 7.2, "accessible_side": "S"},
        {"id": "OA", "type": "outlet", "label": "A口", "x": 10, "y": 10,
         "elevation": 6, "accessible_side": "W"},
        {"id": "OB", "type": "outlet", "label": "B口", "x": 30, "y": 10,
         "elevation": 5, "accessible_side": "E"},
        {"id": "OC", "type": "outlet", "label": "C口", "x": 20, "y": 24,
         "elevation": 7, "accessible_side": "S"},
    ],
    "pipes": [
        {"id": "P0", "from_node": "T", "to_node": "V", "capacity_l": 30,
         "max_flow_lpm": 12, "length_m": 15},
        {"id": "P1", "from_node": "V", "to_node": "J1", "capacity_l": 10,
         "max_flow_lpm": 12, "length_m": 18},
        {"id": "P2", "from_node": "V", "to_node": "J2", "capacity_l": 10,
         "max_flow_lpm": 12, "length_m": 2},
        {"id": "P3", "from_node": "J1", "to_node": "OA", "capacity_l": 8,
         "max_flow_lpm": 8, "length_m": 4},
        {"id": "P4", "from_node": "J2", "to_node": "OC", "capacity_l": 8,
         "max_flow_lpm": 8, "length_m": 4},
        {"id": "P5", "from_node": "J1", "to_node": "J3", "capacity_l": 10,
         "max_flow_lpm": 12, "length_m": 20},
        {"id": "P6", "from_node": "J3", "to_node": "OB", "capacity_l": 8,
         "max_flow_lpm": 8, "length_m": 4},
    ],
    "furrows": [
        {"id": "FA", "name": "A畦", "outlet_id": "OA", "tail_x": 10,
         "tail_y": 18, "tail_elevation": 5.6, "wet_min_min": 0,
         "wet_max_min": 30},
        {"id": "FB", "name": "B畦", "outlet_id": "OB", "tail_x": 30,
         "tail_y": 18, "tail_elevation": 4.6, "wet_min_min": 0,
         "wet_max_min": 30},
        {"id": "FC", "name": "C畦", "outlet_id": "OC", "tail_x": 20,
         "tail_y": 6, "tail_elevation": 6.6, "wet_min_min": 0,
         "wet_max_min": 30},
    ],
    "zones": [{"id": "Z1", "x": 15, "y": 8, "w": 4, "h": 4, "label": "禁踩区"}],
    "fittings": [{"id": "H1", "name": "软管", "hose_length_m": 30, "count": 1}],
}


def put_layout(**overrides):
    lay = {**LAYOUT, **overrides}
    r = client.put("/api/layout", json=lay)
    assert r.status_code == 200, r.text
    return r.json()


def view():
    return client.get("/api/sessions/active").json()


def active_step(v):
    return next((s for s in v["steps"] if s["status"] == "active"), None)


def confirm(step_id, expect=200):
    r = client.post(f"/api/sessions/{SID}/confirm", json={"step_id": step_id})
    assert r.status_code == expect, r.text
    return r.json()


def solve_move(st):
    """R4: try detour routes until one confirms."""
    r = st["payload"]["route"]
    a, b = r[0], r[-1]
    candidates = [
        [a, [a[0] - 6, a[1]], [b[0] - 6, b[1]], b],
        [a, [a[0], a[1] - 8], [b[0], b[1] - 8], b],
        [a, [a[0], a[1] + 8], [b[0], b[1] + 8], b],
        [a, [a[0] + 6, a[1]], [b[0] + 6, b[1]], b],
    ]
    for cand in candidates:
        client.post(f"/api/sessions/{SID}/steps/{st['id']}/route",
                    json={"points": cand})
        resp = client.post(f"/api/sessions/{SID}/confirm",
                           json={"step_id": st["id"]})
        if resp.status_code == 200:
            return
    raise AssertionError(f"no detour worked for {st['text']}")


def walk_until(pred, limit=80):
    for _ in range(limit):
        v = view()
        if pred(v):
            return v
        st = active_step(v)
        if not st:
            return v
        if st["type"] == "MOVE_PIPE" and st["warning"]:
            solve_move(st)
        else:
            confirm(st["id"])
    raise AssertionError("walk did not converge")


def new_session():
    global SID
    active = client.get("/api/sessions/active").json()
    if active.get("session") and active["session"]["status"] == "active":
        client.post(f"/api/sessions/{active['session']['id']}/abort")
    r = client.post("/api/sessions", json={"flow_lpm": 8})
    assert r.status_code == 200, r.text
    SID = r.json()["session"]["id"]
    return r.json()


def test_full_sequence_and_rules():
    put_layout()
    v = new_session()
    types = [s["type"] for s in v["steps"]]
    # 顺序：预充主管 -> 预充分支 -> 开高口(C) -> ... -> 收尾
    assert types[0] == "PREFILL_MAIN"
    assert types[1] == "PREFILL_BRANCH"
    assert types[-1] == "END_SESSION"
    opens = [s for s in v["steps"] if s["type"] == "OPEN_OUTLET"]
    assert [o["payload"]["furrow_id"] for o in opens] == ["FC", "FA", "FB"]
    for i, t in enumerate(types):
        if t == "OPEN_OUTLET":
            assert types[i + 1] == "AWAIT_TAIL"
        if t == "MOVE_PIPE":
            assert types[i - 1] == "CLOSE_OUTLET"

    # R1 顺序强制：只能确认当前步骤
    r = client.post(f"/api/sessions/{SID}/confirm",
                    json={"step_id": v["steps"][1]["id"]})
    assert r.status_code == 409

    # 走到 A->B 的移管：路线直线穿过仍在渗水的 C 畦与禁踩区
    v = walk_until(lambda x: (active_step(x) or {}).get("type") == "MOVE_PIPE"
                   and active_step(x)["payload"]["to_outlet"] == "OB")
    st = active_step(v)
    assert "C畦" in st["warning"] and "禁踩区" in st["warning"]
    # R4：跨越过水畦沟不得确认
    confirm(st["id"], expect=409)
    # 自定义绕行路线后放行
    r = client.post(f"/api/sessions/{SID}/steps/{st['id']}/route",
                    json={"points": [[8.8, 10], [8.8, 2], [31.2, 2],
                                     [31.2, 10]]})
    assert r.status_code == 200, r.text
    fixed = next(s for s in r.json()["steps"] if s["id"] == st["id"])
    assert not fixed["warning"]
    confirm(st["id"])

    # 撤回误确认：移管退回待执行，可再次确认
    r = client.post(f"/api/sessions/{SID}/undo")
    assert r.status_code == 200
    assert active_step(r.json())["type"] == "MOVE_PIPE"
    confirm(active_step(r.json())["id"])

    v = walk_until(lambda x: x["session"]["status"] != "active")
    assert v["session"]["status"] == "done"
    assert all(f["state"] == "done" for f in v["furrows"])


def test_wet_min_and_issue_replan():
    furrows = [dict(f, wet_min_min=5 if f["id"] == "FA" else 0)
               for f in LAYOUT["furrows"]]
    put_layout(furrows=furrows)
    new_session()
    v = walk_until(lambda x: (active_step(x) or {}).get("type") == "AWAIT_TAIL"
                   and active_step(x)["payload"]["furrow_id"] == "FA")
    st = active_step(v)
    # R2：未到最短润湿时间不得确认到尾
    confirm(st["id"], expect=409)
    # 现场延长供水后把下限调回 0（布局保存不重置过水状态）
    put_layout(furrows=[dict(f, wet_min_min=0) for f in furrows])
    confirm(st["id"])

    # 堵沟 -> 从最近确认状态重排：先关口、排除异常、再重灌；已浇畦保留
    r = client.post(f"/api/sessions/{SID}/issue",
                    json={"furrow_id": "FA", "kind": "blocked"})
    assert r.status_code == 200, r.text
    v = r.json()
    assert active_step(v)["type"] == "CLOSE_OUTLET"
    rest = [s["type"] for s in v["steps"] if s["status"] != "done"]
    assert "FIX_ISSUE" in rest
    assert next(f for f in v["furrows"] if f["id"] == "FA")["state"] == "issue"
    assert next(f for f in v["furrows"] if f["id"] == "FC")["state"] == "done"

    # 撤回异常上报 -> 恢复到上报前一刻（A畦关口的确认点）
    r = client.post(f"/api/sessions/{SID}/undo")
    assert r.status_code == 200
    assert active_step(r.json())["type"] == "CLOSE_OUTLET"

    # 漏接 -> 管路泄压，重排后须重新预充主管
    r = client.post(f"/api/sessions/{SID}/issue",
                    json={"furrow_id": "FA", "kind": "leak"})
    rest = [s["type"] for s in r.json()["steps"] if s["status"] != "done"]
    assert "PREFILL_MAIN" in rest

    v = walk_until(lambda x: x["session"]["status"] != "active")
    assert v["session"]["status"] == "done"


def test_layout_validation_and_back_siphon_guard():
    put_layout()
    r = client.get("/api/layout").json()
    assert r["warnings"] == []
    # 畦口高于水池 -> 无法自流告警
    bad = dict(LAYOUT)
    bad["nodes"] = [dict(n, elevation=20) if n["id"] == "OA" else n
                    for n in LAYOUT["nodes"]]
    r = client.put("/api/layout", json=bad).json()
    assert any("无法自流" in w or "逆坡" in w for w in r["warnings"])
    put_layout()
