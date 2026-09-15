export type NodeType = "tank" | "junction" | "valve" | "outlet";
export type Side = "N" | "S" | "E" | "W";

export interface NodeT {
  id: string;
  type: NodeType;
  label: string;
  x: number;
  y: number;
  elevation: number;
  accessible_side: Side;
}

export interface PipeT {
  id: string;
  from_node: string;
  to_node: string;
  capacity_l: number;
  max_flow_lpm: number;
  length_m: number;
}

export interface FurrowT {
  id: string;
  name: string;
  outlet_id: string;
  tail_x: number;
  tail_y: number;
  tail_elevation: number;
  wet_min_min: number;
  wet_max_min: number;
  state?: "pending" | "flowing" | "tail_ok" | "done" | "issue";
  opened_at?: string | null;
  closed_at?: string | null;
}

export interface ZoneT {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
}

export interface FittingT {
  id: string;
  name: string;
  hose_length_m: number;
  count: number;
}

export interface Layout {
  nodes: NodeT[];
  pipes: PipeT[];
  furrows: FurrowT[];
  zones: ZoneT[];
  fittings: FittingT[];
  warnings?: string[];
}

export interface StepT {
  id: string;
  seq: number;
  type: string;
  payload: Record<string, any>;
  status: "pending" | "active" | "done" | "skipped";
  warning: string | null;
  text: string;
}

export interface SessionState {
  main_charged: boolean;
  charged_branches: string[];
  open_outlet: string | null;
  hose_at: string | null;
}

export interface SessionT {
  id: string;
  created_at: string;
  status: "active" | "done" | "aborted";
  flow_lpm: number;
  state: SessionState;
}

export interface Highlight {
  valve_node_id: string | null;
  outlet_node_id: string | null;
  observe_furrow_id: string | null;
  hose_route: [number, number][] | null;
}

export interface SessionView {
  session: SessionT | null;
  steps: StepT[];
  current_step_id: string | null;
  highlight: Highlight;
  furrows: FurrowT[];
  can_undo: boolean;
  notice?: string;
}

export type Tool =
  | "select" | "tank" | "valve" | "junction" | "outlet"
  | "pipe" | "furrow" | "zone" | "delete";

export type Selection =
  | { kind: "node" | "pipe" | "furrow" | "zone"; id: string }
  | null;
