"""Session lifecycle: plan, confirm, report issues, undo, replan."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from . import db, planner
from .models import ConfirmIn, IssueIn, RouteIn, SessionCreate
from .routes_layout import load_layout

router = APIRouter(prefix="/api/sessions", tags=["session"])


# ---------------------------------------------------------------------------
# view assembly
# ---------------------------------------------------------------------------

def _session_view(conn, session_id: str) -> dict:
    s = db.row(conn, "SELECT * FROM sessions WHERE id=?", (session_id,))
    if not s:
        raise HTTPException(404, "作业不存在")
    layout = load_layout(conn)
    nodes_by_id = {n["id"]: n for n in layout["nodes"]}
    furrows_by_id = {f["id"]: f for f in layout["furrows"]}
    steps = db.rows(conn,
                    "SELECT * FROM steps WHERE session_id=? ORDER BY seq",
                    (session_id,))
    now = datetime.now(timezone.utc)
    for st in steps:
        st["payload"] = db.jload(st["payload"], {})
        st["text"] = planner.step_text(st, nodes_by_id, furrows_by_id)
        # 移管警告随现场过水状态实时刷新
        if st["type"] == "MOVE_PIPE" and st["status"] in ("pending", "active"):
            p = st["payload"]
            segs = planner.wet_furrow_segments(
                layout["furrows"], nodes_by_id,
                {p.get("from_outlet"), p.get("to_outlet")}, now)
            hits = planner.check_route(p.get("route") or [], segs,
                                       layout["zones"])
            st["warning"] = "携管路线跨越：" + "、".join(hits) if hits else None
    current = next((st for st in steps if st["status"] == "active"), None)
    state = db.jload(s["state_json"], planner.empty_state())

    highlight = {"valve_node_id": None, "outlet_node_id": None,
                 "observe_furrow_id": None, "hose_route": None}
    if current:
        p = current["payload"]
        t = current["type"]
        if t in ("OPEN_OUTLET", "CLOSE_OUTLET"):
            highlight["valve_node_id"] = p.get("outlet_id")
            highlight["outlet_node_id"] = p.get("outlet_id")
        elif t == "AWAIT_TAIL":
            highlight["observe_furrow_id"] = p.get("furrow_id")
            highlight["outlet_node_id"] = p.get("outlet_id")
        elif t == "MOVE_PIPE":
            highlight["hose_route"] = p.get("route")
            highlight["outlet_node_id"] = p.get("to_outlet")
        elif t == "PREFILL_BRANCH":
            highlight["valve_node_id"] = p.get("valve_id")
        elif t in ("PREFILL_MAIN", "END_SESSION"):
            highlight["valve_node_id"] = p.get("tank_id")

    can_undo = bool(db.row(
        conn, "SELECT id FROM events WHERE session_id=? LIMIT 1",
        (session_id,)))
    return {
        "session": {**s, "state": state},
        "steps": steps,
        "current_step_id": current["id"] if current else None,
        "highlight": highlight,
        "furrows": layout["furrows"],
        "can_undo": can_undo,
    }


def _snapshot(conn, session_id: str) -> dict:
    return {
        "steps": db.rows(conn,
                         "SELECT * FROM steps WHERE session_id=? ORDER BY seq",
                         (session_id,)),
        "furrows": {f["id"]: f for f in db.rows(conn, "SELECT * FROM furrows")},
        "state": db.row(conn, "SELECT state_json FROM sessions WHERE id=?",
                        (session_id,))["state_json"],
    }


def _record_event(conn, session_id: str, kind: str, detail: dict):
    conn.execute(
        "INSERT INTO events (session_id, at, kind, detail) VALUES (?,?,?,?)",
        (session_id, planner.now_iso(), kind, db.jdump({
            **detail, "snapshot": _snapshot(conn, session_id)})))


def _restore(conn, session_id: str, snap: dict):
    with conn:
        conn.execute("DELETE FROM steps WHERE session_id=?", (session_id,))
        for st in snap["steps"]:
            conn.execute(
                "INSERT INTO steps (id,session_id,seq,type,payload,status,"
                "warning,activated_at) VALUES (?,?,?,?,?,?,?,?)",
                (st["id"], session_id, st["seq"], st["type"], st["payload"],
                 st["status"], st["warning"], st["activated_at"]))
        for fid, f in snap["furrows"].items():
            conn.execute(
                "UPDATE furrows SET state=?, opened_at=?, closed_at=? WHERE id=?",
                (f["state"], f["opened_at"], f["closed_at"], fid))
        conn.execute("UPDATE sessions SET state_json=? WHERE id=?",
                     (snap["state"], session_id))


def _activate_next(conn, session_id: str):
    nxt = db.row(conn,
                 "SELECT id FROM steps WHERE session_id=? AND status='pending'"
                 " ORDER BY seq LIMIT 1", (session_id,))
    if nxt:
        conn.execute("UPDATE steps SET status='active', activated_at=? WHERE id=?",
                     (planner.now_iso(), nxt["id"]))


def _get_active_step(conn, session_id: str) -> dict:
    st = db.row(conn,
                "SELECT * FROM steps WHERE session_id=? AND status='active'",
                (session_id,))
    if not st:
        raise HTTPException(409, "当前没有待执行步骤")
    st["payload"] = db.jload(st["payload"], {})
    return st


# ---------------------------------------------------------------------------
# session creation
# ---------------------------------------------------------------------------

@router.get("/active")
def active_session():
    with db.connect() as conn:
        s = db.row(conn,
                   "SELECT id FROM sessions WHERE status='active'"
                   " ORDER BY created_at DESC LIMIT 1")
        if not s:  # 最近一场（已结束）也返回，便于展示结果与再次开局
            s = db.row(conn,
                       "SELECT id FROM sessions ORDER BY created_at DESC"
                       " LIMIT 1")
        return _session_view(conn, s["id"]) if s else {"session": None}


@router.post("")
def create_session(body: SessionCreate):
    with db.connect() as conn:
        layout = load_layout(conn)
        if not layout["nodes"]:
            raise HTTPException(409, "请先绘制地块布局")
        old = db.row(conn, "SELECT id FROM sessions WHERE status='active'")
        if old:
            raise HTTPException(409, "已有进行中的作业，请先收尾或中止")

        todo = [f for f in layout["furrows"]
                if f["state"] in ("pending", "issue")
                and (body.furrow_ids is None or f["id"] in body.furrow_ids)]
        if not todo:
            raise HTTPException(409, "没有待灌的畦沟")

        state = planner.empty_state()
        steps = planner.build_steps(
            state, todo, layout["nodes"], layout["pipes"], layout["furrows"],
            layout["zones"], layout["fittings"], body.flow_lpm)
        sid = planner.new_id("ss")
        with conn:
            conn.execute(
                "INSERT INTO sessions (id,created_at,status,flow_lpm,state_json)"
                " VALUES (?,?,?,?,?)",
                (sid, planner.now_iso(), "active", body.flow_lpm,
                 db.jdump(state)))
            for st in steps:
                conn.execute(
                    "INSERT INTO steps (id,session_id,seq,type,payload,status,"
                    "warning) VALUES (?,?,?,?,?,?,?)",
                    (st["id"], sid, st["seq"], st["type"],
                     db.jdump(st["payload"]), st["status"], st["warning"]))
            _activate_next(conn, sid)
        return _session_view(conn, sid)


# ---------------------------------------------------------------------------
# confirm current step
# ---------------------------------------------------------------------------

def _fail(msg: str):
    raise HTTPException(409, msg)


@router.post("/{session_id}/confirm")
def confirm_step(session_id: str, body: ConfirmIn):
    with db.connect() as conn:
        s = db.row(conn, "SELECT * FROM sessions WHERE id=?", (session_id,))
        if not s or s["status"] != "active":
            _fail("作业已结束")
        step = _get_active_step(conn, session_id)
        if step["id"] != body.step_id:
            _fail("只能确认当前高亮步骤")
        layout = load_layout(conn)
        nodes_by_id = {n["id"]: n for n in layout["nodes"]}
        furrows_by_id = {f["id"]: f for f in layout["furrows"]}
        state = db.jload(s["state_json"], planner.empty_state())
        p, t = step["payload"], step["type"]
        now = datetime.now(timezone.utc)
        warn = None

        _record_event(conn, session_id, "confirm",
                      {"step_id": step["id"], "type": t})

        if t == "PREFILL_MAIN":
            if state["open_outlet"]:
                _fail("预充主管前须关闭所有畦口")
            state["main_charged"] = True

        elif t == "PREFILL_BRANCH":
            if not state["main_charged"]:
                _fail("主管未充水，无法预充分支")
            branch = p.get("branch")
            if branch not in state["charged_branches"]:
                state["charged_branches"].append(branch)

        elif t == "OPEN_OUTLET":
            out_id = p["outlet_id"]
            out = nodes_by_id.get(out_id)
            if not out:
                _fail("畦口不存在")
            if not state["main_charged"]:
                _fail("主管未预充，禁止开畦口（R3 防倒吸）")
            if state["open_outlet"]:
                _fail("已有畦口在过水，须先关旧口（R1）")
            _, _, tank, parent = planner.build_graph(layout["nodes"],
                                                     layout["pipes"])
            path = planner.path_to_tank(out_id, parent)
            if not path:
                _fail("该畦口与水池不连通")
            rise = planner.path_max_rise(nodes_by_id, path)
            if rise > planner.UPHILL_TOLERANCE_M:
                _fail(f"上游管段逆坡 {rise:.2f}m，重力无法送达")
            if tank and out["elevation"] >= tank["elevation"]:
                _fail("畦口不低于水池，无法自流")
            branch = p.get("branch", "main")
            valve_id = planner.branch_valve_of(branch)
            charged = set(state["charged_branches"])
            if state["main_charged"]:
                charged.add("main")
            if valve_id and branch not in charged and \
                    out["elevation"] < nodes_by_id[valve_id]["elevation"] \
                    - planner.UPHILL_TOLERANCE_M:
                _fail("低位口上游为空管，须先预充分支防倒吸（R3）")
            state["open_outlet"] = out_id
            state["hose_at"] = out_id
            if branch not in state["charged_branches"]:
                state["charged_branches"].append(branch)
            conn.execute("UPDATE furrows SET state='flowing', opened_at=? "
                         "WHERE id=?", (planner.now_iso(), p["furrow_id"]))

        elif t == "AWAIT_TAIL":
            f = furrows_by_id.get(p["furrow_id"])
            if not f or f["state"] != "flowing":
                _fail("该畦沟未在供水")
            if f["opened_at"]:
                opened = datetime.fromisoformat(f["opened_at"])
                elapsed = (now - opened).total_seconds() / 60
                if elapsed < f["wet_min_min"]:
                    _fail(f"润湿不足 {f['wet_min_min']} 分钟，不得确认到尾（R2）")
                if elapsed > f["wet_max_min"]:
                    warn = f"已超最长润湿 {f['wet_max_min']} 分钟，注意漫溢"
            conn.execute("UPDATE furrows SET state='tail_ok' WHERE id=?",
                         (f["id"],))

        elif t == "CLOSE_OUTLET":
            f = furrows_by_id.get(p.get("furrow_id") or "")
            if state["open_outlet"] != p["outlet_id"]:
                _fail("该畦口未在过水")
            if f and f["state"] == "tail_ok":
                conn.execute(
                    "UPDATE furrows SET state='done', closed_at=? WHERE id=?",
                    (planner.now_iso(), f["id"]))
            elif f:
                # 未见尾端润湿不得完成（R2）：安全关闭后退回待灌
                conn.execute(
                    "UPDATE furrows SET state='pending', opened_at=NULL "
                    "WHERE id=?", (f["id"],))
            state["open_outlet"] = None

        elif t == "MOVE_PIPE":
            route = p.get("route") or []
            segs = planner.wet_furrow_segments(
                layout["furrows"], nodes_by_id,
                {p.get("from_outlet"), p.get("to_outlet")}, now)
            hits = planner.check_route(route, segs, layout["zones"])
            if hits:
                _fail("携管路线仍跨越：" + "、".join(hits) + "（R4）")
            state["hose_at"] = p["to_outlet"]

        elif t == "FIX_ISSUE":
            fid = p.get("furrow_id")
            if fid:
                conn.execute("UPDATE furrows SET state='pending' WHERE id=?",
                             (fid,))

        elif t == "END_SESSION":
            if state["open_outlet"]:
                _fail("仍有畦口在过水，不能收尾")
            state["main_charged"] = False
            state["charged_branches"] = []
            conn.execute("UPDATE sessions SET status='done' WHERE id=?",
                         (session_id,))

        with conn:
            conn.execute("UPDATE sessions SET state_json=? WHERE id=?",
                         (db.jdump(state), session_id))
            conn.execute("UPDATE steps SET status='done' WHERE id=?",
                         (step["id"],))
            if t != "END_SESSION":
                _activate_next(conn, session_id)
        view = _session_view(conn, session_id)
        if warn:
            view["notice"] = warn
        return view


# ---------------------------------------------------------------------------
# issue report -> replan from last confirmed state
# ---------------------------------------------------------------------------

@router.post("/{session_id}/issue")
def report_issue(session_id: str, body: IssueIn):
    with db.connect() as conn:
        s = db.row(conn, "SELECT * FROM sessions WHERE id=?", (session_id,))
        if not s or s["status"] != "active":
            _fail("作业已结束")
        layout = load_layout(conn)
        furrows_by_id = {f["id"]: f for f in layout["furrows"]}
        f = furrows_by_id.get(body.furrow_id)
        if not f:
            raise HTTPException(404, "畦沟不存在")
        state = db.jload(s["state_json"], planner.empty_state())

        _record_event(conn, session_id, "issue",
                      {"furrow_id": body.furrow_id, "kind": body.kind})

        with conn:
            conn.execute("UPDATE furrows SET state='issue' WHERE id=?",
                         (f["id"],))
            if body.kind == "leak":
                # 漏接 -> 管路泄压，后续须重新预充
                state["main_charged"] = False
                state["charged_branches"] = []
            conn.execute("UPDATE sessions SET state_json=? WHERE id=?",
                         (db.jdump(state), session_id))

            # 保留已完成步骤与已浇畦，重排其余
            done_steps = db.rows(
                conn, "SELECT * FROM steps WHERE session_id=? AND "
                "status='done' ORDER BY seq", (session_id,))
            conn.execute("DELETE FROM steps WHERE session_id=? AND "
                         "status IN ('pending','active')", (session_id,))
            seq0 = (done_steps[-1]["seq"] + 1) if done_steps else 0

            new_steps: list[dict] = []

            def add(stype, payload, warning=None):
                nonlocal seq0
                new_steps.append(planner._step(seq0, stype, payload, warning))
                seq0 += 1

            # 安全关闭仍在过水的畦口：先生成关旧口步骤，编排时按已关闭处理，
            # 但持久化状态保持开口，待该步骤确认时再真正关闭
            plan_state = dict(state)
            if plan_state["open_outlet"]:
                open_f = next((x for x in layout["furrows"]
                               if x["outlet_id"] == plan_state["open_outlet"]), None)
                add("CLOSE_OUTLET", {"outlet_id": plan_state["open_outlet"],
                                     "furrow_id": open_f["id"] if open_f else None})
                plan_state["open_outlet"] = None

            instruction = {
                "blocked": f"疏通 {f['name']} 沟尾堵塞，确认通水后继续",
                "leak": f"检查 {f['name']} 进水口软管接头，紧固或更换管件",
                "no_tail": f"检查 {f['name']} 沿程渗漏与流量，必要时延长供水",
            }[body.kind]
            if body.note:
                instruction += f"（备注：{body.note}）"
            add("FIX_ISSUE", {"furrow_id": f["id"], "kind": body.kind,
                              "instruction": instruction})

            todo = [x for x in layout["furrows"]
                    if x["state"] in ("pending", "issue", "flowing", "tail_ok")]
            new_steps += planner.build_steps(
                plan_state, todo, layout["nodes"], layout["pipes"],
                layout["furrows"], layout["zones"], layout["fittings"],
                s["flow_lpm"], seq0)
            for st in new_steps:
                conn.execute(
                    "INSERT INTO steps (id,session_id,seq,type,payload,status,"
                    "warning) VALUES (?,?,?,?,?,?,?)",
                    (st["id"], session_id, st["seq"], st["type"],
                     db.jdump(st["payload"]), st["status"], st["warning"]))
            _activate_next(conn, session_id)
        return _session_view(conn, session_id)


# ---------------------------------------------------------------------------
# undo last confirmation / issue
# ---------------------------------------------------------------------------

@router.post("/{session_id}/undo")
def undo(session_id: str):
    with db.connect() as conn:
        s = db.row(conn, "SELECT status FROM sessions WHERE id=?", (session_id,))
        if not s or s["status"] != "active":
            _fail("作业已结束，无法撤回")
        ev = db.row(conn,
                    "SELECT * FROM events WHERE session_id=? ORDER BY id DESC"
                    " LIMIT 1", (session_id,))
        if not ev:
            _fail("没有可撤回的操作")
        detail = db.jload(ev["detail"], {})
        snap = detail.get("snapshot")
        if not snap:
            _fail("该操作缺少快照，无法撤回")
        _restore(conn, session_id, snap)
        with conn:
            conn.execute("DELETE FROM events WHERE id=?", (ev["id"],))
        return _session_view(conn, session_id)


# ---------------------------------------------------------------------------
# manual route override for a MOVE_PIPE step
# ---------------------------------------------------------------------------

@router.post("/{session_id}/steps/{step_id}/route")
def set_route(session_id: str, step_id: str, body: RouteIn):
    with db.connect() as conn:
        st = db.row(conn,
                    "SELECT * FROM steps WHERE id=? AND session_id=?",
                    (step_id, session_id))
        if not st or st["type"] != "MOVE_PIPE":
            raise HTTPException(404, "移管步骤不存在")
        payload = db.jload(st["payload"], {})
        payload["route"] = body.points
        layout = load_layout(conn)
        nodes_by_id = {n["id"]: n for n in layout["nodes"]}
        segs = planner.wet_furrow_segments(
            layout["furrows"], nodes_by_id,
            {payload.get("from_outlet"), payload.get("to_outlet")},
            datetime.now(timezone.utc))
        hits = planner.check_route(body.points, segs, layout["zones"])
        warning = "携管路线跨越：" + "、".join(hits) if hits else None
        with conn:
            conn.execute("UPDATE steps SET payload=?, warning=? WHERE id=?",
                         (db.jdump(payload), warning, step_id))
        return _session_view(conn, session_id)


@router.post("/{session_id}/abort")
def abort(session_id: str):
    with db.connect() as conn:
        with conn:
            conn.execute("UPDATE sessions SET status='aborted' WHERE id=?",
                         (session_id,))
    return {"ok": True}
