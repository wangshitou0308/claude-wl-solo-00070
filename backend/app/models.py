"""Pydantic schemas shared by the API."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

NodeType = Literal["tank", "junction", "valve", "outlet"]
Side = Literal["N", "S", "E", "W"]


class NodeIn(BaseModel):
    id: str
    type: NodeType
    label: str = ""
    x: float
    y: float
    elevation: float = 0.0
    accessible_side: Side = "S"


class PipeIn(BaseModel):
    id: str
    from_node: str
    to_node: str
    capacity_l: float = 0.0
    max_flow_lpm: float = 10.0
    length_m: float = 0.0


class FurrowIn(BaseModel):
    id: str
    name: str
    outlet_id: str
    tail_x: float
    tail_y: float
    tail_elevation: float = 0.0
    wet_min_min: float = 3.0
    wet_max_min: float = 10.0


class ZoneIn(BaseModel):
    id: str
    x: float
    y: float
    w: float
    h: float
    label: str = ""


class FittingIn(BaseModel):
    id: str
    name: str
    hose_length_m: float = 0.0
    count: int = 1


class LayoutIn(BaseModel):
    nodes: list[NodeIn] = Field(default_factory=list)
    pipes: list[PipeIn] = Field(default_factory=list)
    furrows: list[FurrowIn] = Field(default_factory=list)
    zones: list[ZoneIn] = Field(default_factory=list)
    fittings: list[FittingIn] = Field(default_factory=list)


class SessionCreate(BaseModel):
    flow_lpm: float = 8.0
    furrow_ids: Optional[list[str]] = None  # None => all unfinished


class ConfirmIn(BaseModel):
    step_id: str


class IssueIn(BaseModel):
    furrow_id: str
    kind: Literal["blocked", "leak", "no_tail"]
    note: str = ""


class RouteIn(BaseModel):
    points: list[list[float]]
