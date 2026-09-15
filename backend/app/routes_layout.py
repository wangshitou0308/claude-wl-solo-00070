"""Layout CRUD: the whole field graph is replaced atomically per save."""
from __future__ import annotations

from fastapi import APIRouter

from . import db, planner
from .models import LayoutIn

router = APIRouter(prefix="/api", tags=["layout"])


def load_layout(conn) -> dict:
    return {
        "nodes": db.rows(conn, "SELECT * FROM nodes"),
        "pipes": db.rows(conn, "SELECT * FROM pipes"),
        "furrows": db.rows(conn, "SELECT * FROM furrows"),
        "zones": db.rows(conn, "SELECT * FROM zones"),
        "fittings": db.rows(conn, "SELECT * FROM fittings"),
    }


@router.get("/layout")
def get_layout():
    with db.connect() as conn:
        layout = load_layout(conn)
    layout["warnings"] = planner.validate_layout(
        layout["nodes"], layout["pipes"], layout["furrows"])
    return layout


@router.put("/layout")
def put_layout(body: LayoutIn):
    with db.connect() as conn:
        # 作业进行中保存布局：保留畦沟过水状态，避免进度被重置；
        # 无进行中作业时保存：视为新一轮灌水，全部回到待灌。
        busy = db.row(conn, "SELECT id FROM sessions WHERE status='active'")
        prev = {f["id"]: f for f in db.rows(conn, "SELECT * FROM furrows")} \
            if busy else {}
        with conn:
            for table in ("furrows", "pipes", "nodes", "zones", "fittings"):
                conn.execute(f"DELETE FROM {table}")
            for n in body.nodes:
                conn.execute(
                    "INSERT INTO nodes VALUES (?,?,?,?,?,?,?)",
                    (n.id, n.type, n.label, n.x, n.y, n.elevation, n.accessible_side))
            for p in body.pipes:
                conn.execute(
                    "INSERT INTO pipes VALUES (?,?,?,?,?,?)",
                    (p.id, p.from_node, p.to_node, p.capacity_l,
                     p.max_flow_lpm, p.length_m))
            for f in body.furrows:
                old = prev.get(f.id, {})
                conn.execute(
                    "INSERT INTO furrows (id,name,outlet_id,tail_x,tail_y,"
                    "tail_elevation,wet_min_min,wet_max_min,state,opened_at,"
                    "closed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (f.id, f.name, f.outlet_id, f.tail_x, f.tail_y,
                     f.tail_elevation, f.wet_min_min, f.wet_max_min,
                     old.get("state", "pending"), old.get("opened_at"),
                     old.get("closed_at")))
            for z in body.zones:
                conn.execute("INSERT INTO zones VALUES (?,?,?,?,?,?)",
                             (z.id, z.x, z.y, z.w, z.h, z.label))
            for ft in body.fittings:
                conn.execute("INSERT INTO fittings VALUES (?,?,?,?)",
                             (ft.id, ft.name, ft.hose_length_m, ft.count))
        layout = load_layout(conn)
    layout["warnings"] = planner.validate_layout(
        layout["nodes"], layout["pipes"], layout["furrows"])
    return layout


@router.post("/demo/seed")
def seed_demo():
    """Load a small demonstration field so the console can be tried at once."""
    demo = LayoutIn(**{
        "nodes": [
            {"id": "T", "type": "tank", "label": "高位水池", "x": 8, "y": 10,
             "elevation": 8.0, "accessible_side": "S"},
            {"id": "VA", "type": "valve", "label": "阀A", "x": 30, "y": 10,
             "elevation": 7.6, "accessible_side": "S"},
            {"id": "VB", "type": "valve", "label": "阀B", "x": 55, "y": 10,
             "elevation": 7.2, "accessible_side": "S"},
            {"id": "VC", "type": "valve", "label": "阀C", "x": 80, "y": 10,
             "elevation": 6.8, "accessible_side": "S"},
            {"id": "OA1", "type": "outlet", "label": "A1口", "x": 30, "y": 22,
             "elevation": 7.2, "accessible_side": "W"},
            {"id": "OA2", "type": "outlet", "label": "A2口", "x": 30, "y": 34,
             "elevation": 6.6, "accessible_side": "W"},
            {"id": "OA3", "type": "outlet", "label": "A3口", "x": 30, "y": 46,
             "elevation": 6.0, "accessible_side": "W"},
            {"id": "OB1", "type": "outlet", "label": "B1口", "x": 55, "y": 22,
             "elevation": 6.8, "accessible_side": "E"},
            {"id": "OB2", "type": "outlet", "label": "B2口", "x": 55, "y": 34,
             "elevation": 6.2, "accessible_side": "E"},
            {"id": "OC1", "type": "outlet", "label": "C1口", "x": 80, "y": 22,
             "elevation": 6.4, "accessible_side": "E"},
        ],
        "pipes": [
            {"id": "P0", "from_node": "T", "to_node": "VA", "capacity_l": 30,
             "max_flow_lpm": 12, "length_m": 22},
            {"id": "P1", "from_node": "VA", "to_node": "VB", "capacity_l": 25,
             "max_flow_lpm": 12, "length_m": 25},
            {"id": "P2", "from_node": "VB", "to_node": "VC", "capacity_l": 25,
             "max_flow_lpm": 12, "length_m": 25},
            {"id": "P3", "from_node": "VA", "to_node": "OA1", "capacity_l": 12,
             "max_flow_lpm": 8, "length_m": 12},
            {"id": "P4", "from_node": "OA1", "to_node": "OA2", "capacity_l": 12,
             "max_flow_lpm": 8, "length_m": 12},
            {"id": "P5", "from_node": "OA2", "to_node": "OA3", "capacity_l": 12,
             "max_flow_lpm": 8, "length_m": 12},
            {"id": "P6", "from_node": "VB", "to_node": "OB1", "capacity_l": 12,
             "max_flow_lpm": 8, "length_m": 12},
            {"id": "P7", "from_node": "OB1", "to_node": "OB2", "capacity_l": 12,
             "max_flow_lpm": 8, "length_m": 12},
            {"id": "P8", "from_node": "VC", "to_node": "OC1", "capacity_l": 12,
             "max_flow_lpm": 8, "length_m": 12},
        ],
        "furrows": [
            {"id": "FA1", "name": "A1畦", "outlet_id": "OA1", "tail_x": 54,
             "tail_y": 23, "tail_elevation": 6.8, "wet_min_min": 0.2,
             "wet_max_min": 2},
            {"id": "FA2", "name": "A2畦", "outlet_id": "OA2", "tail_x": 54,
             "tail_y": 35, "tail_elevation": 6.2, "wet_min_min": 0.2,
             "wet_max_min": 2},
            {"id": "FA3", "name": "A3畦", "outlet_id": "OA3", "tail_x": 54,
             "tail_y": 47, "tail_elevation": 5.6, "wet_min_min": 0.2,
             "wet_max_min": 2},
            {"id": "FB1", "name": "B1畦", "outlet_id": "OB1", "tail_x": 79,
             "tail_y": 23, "tail_elevation": 6.4, "wet_min_min": 0.2,
             "wet_max_min": 2},
            {"id": "FB2", "name": "B2畦", "outlet_id": "OB2", "tail_x": 79,
             "tail_y": 35, "tail_elevation": 5.8, "wet_min_min": 0.2,
             "wet_max_min": 2},
            {"id": "FC1", "name": "C1畦", "outlet_id": "OC1", "tail_x": 102,
             "tail_y": 23, "tail_elevation": 6.0, "wet_min_min": 0.2,
             "wet_max_min": 2},
        ],
        "zones": [
            {"id": "Z1", "x": 26, "y": 26, "w": 6, "h": 6,
             "label": "菜苗禁踩区"},
        ],
        "fittings": [
            {"id": "H1", "name": "软管 8m", "hose_length_m": 8, "count": 2},
            {"id": "J1", "name": "直通接头", "hose_length_m": 0, "count": 2},
        ],
    })
    return put_layout(demo)
