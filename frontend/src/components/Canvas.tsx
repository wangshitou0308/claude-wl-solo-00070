import { useRef, useState } from "react";
import type {
  FurrowT, Layout, NodeT, Selection, SessionView, Tool,
} from "../types";

const W = 120;
const H = 80;

const FURROW_COLOR: Record<string, string> = {
  pending: "#9aa5ad",
  flowing: "#1e88e5",
  tail_ok: "#4fc3f7",
  done: "#66bb6a",
  issue: "#e53935",
};

let uid = 0;
const nid = (p: string) => `${p}${Date.now().toString(36)}${uid++}`;

interface Props {
  layout: Layout;
  mode: "edit" | "run";
  tool: Tool;
  selection: Selection;
  onSelect: (s: Selection) => void;
  onLayout: (l: Layout) => void;
  view: SessionView | null;
  routeDraft: [number, number][] | null;
  onRouteDraft: (pts: [number, number][] | null) => void;
  onToast: (m: string) => void;
}

type Drag =
  | { kind: "node"; id: string }
  | { kind: "tail"; id: string }
  | { kind: "zone"; id: string }
  | { kind: "zoneNew"; x0: number; y0: number }
  | null;

export default function Canvas(p: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<Drag>(null);
  const [cursor, setCursor] = useState<[number, number] | null>(null);
  const [pipeFrom, setPipeFrom] = useState<string | null>(null);
  const [furrowOutlet, setFurrowOutlet] = useState<string | null>(null);

  const edit = p.mode === "edit";
  const nodesById = new Map(p.layout.nodes.map((n) => [n.id, n]));
  const hl = p.view?.highlight;
  // 作业模式用会话返回的实时畦沟状态着色
  const furrows = !edit && p.view ? p.view.furrows : p.layout.furrows;

  const toSvg = (e: React.PointerEvent): [number, number] => {
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(
      svgRef.current!.getScreenCTM()!.inverse());
    return [Math.round(pt.x * 2) / 2, Math.round(pt.y * 2) / 2];
  };

  const mutate = (fn: (l: Layout) => void) => {
    const l: Layout = JSON.parse(JSON.stringify(p.layout));
    fn(l);
    p.onLayout(l);
  };

  const deleteSel = (sel: NonNullable<Selection>) => {
    mutate((l) => {
      if (sel.kind === "node") {
        l.nodes = l.nodes.filter((n) => n.id !== sel.id);
        l.pipes = l.pipes.filter(
          (q) => q.from_node !== sel.id && q.to_node !== sel.id);
        l.furrows = l.furrows.filter((f) => f.outlet_id !== sel.id);
      } else if (sel.kind === "pipe") {
        l.pipes = l.pipes.filter((q) => q.id !== sel.id);
      } else if (sel.kind === "furrow") {
        l.furrows = l.furrows.filter((f) => f.id !== sel.id);
      } else {
        l.zones = l.zones.filter((z) => z.id !== sel.id);
      }
    });
    p.onSelect(null);
  };

  // ---------------- background click ----------------
  const onBgDown = (e: React.PointerEvent) => {
    const [x, y] = toSvg(e);
    if (!edit) {
      if (p.routeDraft) p.onRouteDraft([...p.routeDraft, [x, y]]);
      return;
    }
    if (["tank", "valve", "junction", "outlet"].includes(p.tool)) {
      if (p.tool === "tank" && p.layout.nodes.some((n) => n.type === "tank")) {
        p.onToast("水池只能有一个");
        return;
      }
      mutate((l) => l.nodes.push({
        id: nid(p.tool[0]), type: p.tool as NodeT["type"], label: "",
        x, y, elevation: 0, accessible_side: "S",
      }));
    } else if (p.tool === "zone") {
      setDrag({ kind: "zoneNew", x0: x, y0: y });
    } else if (p.tool === "furrow" && furrowOutlet) {
      mutate((l) => l.furrows.push({
        id: nid("f"), name: `畦${l.furrows.length + 1}`,
        outlet_id: furrowOutlet, tail_x: x, tail_y: y,
        tail_elevation: 0, wet_min_min: 3, wet_max_min: 10,
      }));
      setFurrowOutlet(null);
    } else if (p.tool === "select") {
      p.onSelect(null);
    }
  };

  const onNodeDown = (e: React.PointerEvent, n: NodeT) => {
    if (!edit) return;
    e.stopPropagation();
    if (p.tool === "select") {
      p.onSelect({ kind: "node", id: n.id });
      setDrag({ kind: "node", id: n.id });
    } else if (p.tool === "pipe") {
      if (!pipeFrom) setPipeFrom(n.id);
      else if (pipeFrom !== n.id) {
        mutate((l) => l.pipes.push({
          id: nid("p"), from_node: pipeFrom, to_node: n.id,
          capacity_l: 10, max_flow_lpm: 10, length_m: 0,
        }));
        setPipeFrom(null);
      }
    } else if (p.tool === "furrow") {
      if (n.type !== "outlet") p.onToast("畦沟必须从畦口节点引出");
      else setFurrowOutlet(n.id);
    } else if (p.tool === "delete") {
      deleteSel({ kind: "node", id: n.id });
    }
  };

  const onMove = (e: React.PointerEvent) => {
    const [x, y] = toSvg(e);
    setCursor([x, y]);
    if (!drag) return;
    if (drag.kind === "node") {
      mutate((l) => {
        const n = l.nodes.find((n) => n.id === (drag as { id: string }).id);
        if (n) { n.x = x; n.y = y; }
      });
    } else if (drag.kind === "tail") {
      mutate((l) => {
        const f = l.furrows.find((f) => f.id === (drag as { id: string }).id);
        if (f) { f.tail_x = x; f.tail_y = y; }
      });
    } else if (drag.kind === "zone") {
      mutate((l) => {
        const z = l.zones.find((z) => z.id === (drag as { id: string }).id);
        if (z) { z.x = x - z.w / 2; z.y = y - z.h / 2; }
      });
    }
  };

  const onUp = (e: React.PointerEvent) => {
    if (drag?.kind === "zoneNew") {
      const [x, y] = toSvg(e);
      const w = Math.abs(x - drag.x0);
      const h = Math.abs(y - drag.y0);
      if (w > 1 && h > 1) {
        mutate((l) => l.zones.push({
          id: nid("z"), x: Math.min(drag.x0, x), y: Math.min(drag.y0, y),
          w, h, label: "禁踩区",
        }));
      }
    }
    setDrag(null);
  };

  // ---------------- render helpers ----------------
  const selId = p.selection?.id;

  const nodeShape = (n: NodeT) => {
    const sel = selId === n.id;
    const pulseValve = hl?.valve_node_id === n.id;
    const pulseOutlet = hl?.outlet_node_id === n.id;
    const side = n.accessible_side;
    return (
      <g key={n.id} onPointerDown={(e) => onNodeDown(e, n)}
         style={{ cursor: edit ? "pointer" : "default" }}>
        {(pulseValve || pulseOutlet) && (
          <circle cx={n.x} cy={n.y} r={2.6} className="pulse" fill="none"
                  stroke={pulseOutlet ? "#fb8c00" : "#43a047"}
                  strokeWidth={0.5} />
        )}
        {n.type === "tank" && (
          <>
            <rect x={n.x - 2.6} y={n.y - 1.8} width={5.2} height={3.6} rx={0.4}
                  fill="#0277bd"
                  stroke={sel ? "#ffeb3b" : "#01579b"}
                  strokeWidth={sel ? 0.5 : 0.25} />
            <path d={`M ${n.x - 2} ${n.y - 0.3} q 0.7 -0.7 1.3 0 t 1.4 0 t 1.3 0`}
                  stroke="#b3e5fc" strokeWidth={0.3} fill="none" />
          </>
        )}
        {n.type === "valve" && (
          <>
            <circle cx={n.x} cy={n.y} r={1.1} fill="#43a047"
                    stroke={sel ? "#ffeb3b" : "#1b5e20"}
                    strokeWidth={sel ? 0.5 : 0.25} />
            <line x1={n.x} y1={n.y}
                  x2={n.x + (side === "E" ? 1.7 : side === "W" ? -1.7 : 0)}
                  y2={n.y + (side === "S" ? 1.7 : side === "N" ? -1.7 : 0)}
                  stroke="#1b5e20" strokeWidth={0.35} />
          </>
        )}
        {n.type === "junction" && (
          <circle cx={n.x} cy={n.y} r={0.55} fill="#78909c"
                  stroke={sel ? "#ffeb3b" : "#455a64"}
                  strokeWidth={sel ? 0.45 : 0.2} />
        )}
        {n.type === "outlet" && (
          <rect x={n.x - 0.9} y={n.y - 0.9} width={1.8} height={1.8}
                fill="#fb8c00" stroke={sel ? "#ffeb3b" : "#e65100"}
                strokeWidth={sel ? 0.5 : 0.25} />
        )}
        <text x={n.x} y={n.y + 3.2} className="lbl" textAnchor="middle">
          {n.label || n.type}
        </text>
        <text x={n.x + 1.5} y={n.y - 1.5} className="elev">▲{n.elevation}</text>
      </g>
    );
  };

  const furrowLine = (f: FurrowT) => {
    const o = nodesById.get(f.outlet_id);
    if (!o) return null;
    const color = FURROW_COLOR[f.state ?? "pending"];
    const sel = selId === f.id;
    const observe = hl?.observe_furrow_id === f.id;
    return (
      <g key={f.id}
         onPointerDown={(e) => {
           if (!edit) return;
           e.stopPropagation();
           if (p.tool === "delete") deleteSel({ kind: "furrow", id: f.id });
           else if (p.tool === "select")
             p.onSelect({ kind: "furrow", id: f.id });
         }}>
        {(f.state === "flowing" || f.state === "tail_ok") && (
          <line x1={o.x} y1={o.y} x2={f.tail_x} y2={f.tail_y}
                stroke="#90caf9" strokeWidth={1.7} opacity={0.45} />
        )}
        <line x1={o.x} y1={o.y} x2={f.tail_x} y2={f.tail_y}
              stroke={color} strokeWidth={sel || observe ? 1 : 0.55}
              strokeDasharray={f.state === "flowing" ? "1.6 1" : undefined}
              className={f.state === "flowing" ? "flow" : undefined}
              markerEnd="url(#arrow)" />
        {observe && (
          <circle cx={f.tail_x} cy={f.tail_y} r={2.2} className="pulse"
                  fill="none" stroke="#1e88e5" strokeWidth={0.5} />
        )}
        <circle cx={f.tail_x} cy={f.tail_y} r={0.7} fill={color}
                onPointerDown={(e) => {
                  if (edit && p.tool === "select") {
                    e.stopPropagation();
                    setDrag({ kind: "tail", id: f.id });
                  }
                }} />
        <text x={(o.x + f.tail_x) / 2 + 1} y={(o.y + f.tail_y) / 2 - 0.8}
              className="lbl">{f.name}</text>
      </g>
    );
  };

  const hoseRoute = p.routeDraft ?? hl?.hose_route ?? null;
  const moveWarn = p.view?.steps.find(
    (s) => s.id === p.view?.current_step_id)?.warning;

  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="canvas"
         onPointerDown={onBgDown} onPointerMove={onMove} onPointerUp={onUp}>
      <defs>
        <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3"
                orient="auto">
          <path d="M0,0 L6,3 L0,6 z" fill="#607d8b" />
        </marker>
        <pattern id="hatch" width="2.4" height="2.4"
                 patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="2.4" height="2.4" fill="#ffebee" />
          <line x1="0" y1="0" x2="0" y2="2.4" stroke="#ef9a9a"
                strokeWidth="0.5" />
        </pattern>
      </defs>

      {Array.from({ length: W / 5 + 1 }, (_, i) => (
        <line key={`v${i}`} x1={i * 5} y1={0} x2={i * 5} y2={H}
              stroke={i % 2 ? "#eef3f5" : "#dce6ea"} strokeWidth={0.15} />
      ))}
      {Array.from({ length: H / 5 + 1 }, (_, i) => (
        <line key={`h${i}`} x1={0} y1={i * 5} x2={W} y2={i * 5}
              stroke={i % 2 ? "#eef3f5" : "#dce6ea"} strokeWidth={0.15} />
      ))}
      <text x={2} y={3} className="axis">高（水池侧）</text>
      <text x={2} y={H - 1.5} className="axis">低（坡下） · 单位：米</text>

      {p.layout.zones.map((z) => (
        <g key={z.id}
           onPointerDown={(e) => {
             if (!edit) return;
             e.stopPropagation();
             if (p.tool === "delete") deleteSel({ kind: "zone", id: z.id });
             else if (p.tool === "select") {
               p.onSelect({ kind: "zone", id: z.id });
               setDrag({ kind: "zone", id: z.id });
             }
           }}>
          <rect x={z.x} y={z.y} width={z.w} height={z.h} fill="url(#hatch)"
                stroke={selId === z.id ? "#ffeb3b" : "#e57373"}
                strokeWidth={0.3} />
          <text x={z.x + z.w / 2} y={z.y + z.h / 2} className="lbl zone"
                textAnchor="middle">{z.label}</text>
        </g>
      ))}

      {p.layout.pipes.map((q) => {
        const a = nodesById.get(q.from_node);
        const b = nodesById.get(q.to_node);
        if (!a || !b) return null;
        const sel = selId === q.id;
        return (
          <line key={q.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={sel ? "#ffeb3b" : "#546e7a"}
                strokeWidth={sel ? 1 : 0.6} strokeLinecap="round"
                onPointerDown={(e) => {
                  if (!edit) return;
                  e.stopPropagation();
                  if (p.tool === "delete") deleteSel({ kind: "pipe", id: q.id });
                  else if (p.tool === "select")
                    p.onSelect({ kind: "pipe", id: q.id });
                }} />
        );
      })}

      {furrows.map(furrowLine)}
      {p.layout.nodes.map(nodeShape)}

      {hoseRoute && hoseRoute.length > 0 && (
        <polyline
          points={hoseRoute.map(([x, y]) => `${x},${y}`).join(" ")}
          fill="none"
          stroke={p.routeDraft ? "#8e24aa" : moveWarn ? "#e53935" : "#8e24aa"}
          strokeWidth={0.7} strokeDasharray="1.4 0.9" className="flow" />
      )}

      {pipeFrom && cursor && nodesById.get(pipeFrom) && (
        <line x1={nodesById.get(pipeFrom)!.x} y1={nodesById.get(pipeFrom)!.y}
              x2={cursor[0]} y2={cursor[1]} stroke="#546e7a" strokeWidth={0.4}
              strokeDasharray="1 0.8" />
      )}
      {furrowOutlet && cursor && nodesById.get(furrowOutlet) && (
        <line x1={nodesById.get(furrowOutlet)!.x}
              y1={nodesById.get(furrowOutlet)!.y}
              x2={cursor[0]} y2={cursor[1]} stroke="#1e88e5" strokeWidth={0.4}
              strokeDasharray="1 0.8" />
      )}
      {drag?.kind === "zoneNew" && cursor && (
        <rect x={Math.min(drag.x0, cursor[0])}
              y={Math.min(drag.y0, cursor[1])}
              width={Math.abs(cursor[0] - drag.x0)}
              height={Math.abs(cursor[1] - drag.y0)}
              fill="url(#hatch)" stroke="#e57373" strokeWidth={0.3}
              strokeDasharray="1 0.6" />
      )}
    </svg>
  );
}
