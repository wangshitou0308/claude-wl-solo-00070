import type { Layout, Selection, Tool } from "../types";

const TOOLS: { id: Tool; label: string }[] = [
  { id: "select", label: "选择/拖动" },
  { id: "tank", label: "水池" },
  { id: "valve", label: "分支阀" },
  { id: "junction", label: "结点" },
  { id: "outlet", label: "畦口" },
  { id: "pipe", label: "管段" },
  { id: "furrow", label: "畦沟" },
  { id: "zone", label: "禁踩区" },
  { id: "delete", label: "删除" },
];

interface Props {
  layout: Layout;
  tool: Tool;
  setTool: (t: Tool) => void;
  selection: Selection | null;
  onLayout: (l: Layout) => void;
  onSeed: () => void;
  onClear: () => void;
  onToast: (m: string) => void;
}

export default function EditPanel(p: Props) {
  const sel = p.selection;
  const node = sel?.kind === "node"
    ? p.layout.nodes.find((n) => n.id === sel.id) : null;
  const pipe = sel?.kind === "pipe"
    ? p.layout.pipes.find((q) => q.id === sel.id) : null;
  const furrow = sel?.kind === "furrow"
    ? p.layout.furrows.find((f) => f.id === sel.id) : null;
  const zone = sel?.kind === "zone"
    ? p.layout.zones.find((z) => z.id === sel.id) : null;

  const mutate = (fn: (l: Layout) => void) => {
    const l: Layout = JSON.parse(JSON.stringify(p.layout));
    fn(l);
    p.onLayout(l);
  };

  const num = (v: string) => (v === "" ? 0 : Number(v));

  return (
    <div className="panel">
      <h3>地块编辑</h3>
      <div className="tools">
        {TOOLS.map((t) => (
          <button key={t.id}
                  className={p.tool === t.id ? "tool on" : "tool"}
                  onClick={() => p.setTool(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      <p className="hint">
        {p.tool === "pipe" && "依次点击两个节点连成管段"}
        {p.tool === "furrow" && "先点畦口节点，再点沟尾位置"}
        {p.tool === "zone" && "在图上拖出禁踩矩形"}
        {p.tool === "select" && "点击图元查看属性，拖动可移动"}
      </p>

      {node && (
        <div className="form">
          <h4>节点 {node.id}</h4>
          <label>名称
            <input value={node.label} onChange={(e) =>
              mutate((l) => { l.nodes.find((n) => n.id === node.id)!.label = e.target.value; })} />
          </label>
          <label>高程 (m)
            <input type="number" step="0.1" value={node.elevation}
                   onChange={(e) => mutate((l) => {
                     l.nodes.find((n) => n.id === node.id)!.elevation = num(e.target.value);
                   })} />
          </label>
          {(node.type === "valve" || node.type === "outlet") && (
            <label>可达侧
              <select value={node.accessible_side} onChange={(e) =>
                mutate((l) => {
                  l.nodes.find((n) => n.id === node.id)!.accessible_side =
                    e.target.value as never;
                })}>
                <option value="N">北</option><option value="S">南</option>
                <option value="E">东</option><option value="W">西</option>
              </select>
            </label>
          )}
        </div>
      )}

      {pipe && (
        <div className="form">
          <h4>管段 {pipe.id}</h4>
          <label>容量 (L)
            <input type="number" value={pipe.capacity_l} onChange={(e) =>
              mutate((l) => { l.pipes.find((q) => q.id === pipe.id)!.capacity_l = num(e.target.value); })} />
          </label>
          <label>允许流量 (L/min)
            <input type="number" value={pipe.max_flow_lpm} onChange={(e) =>
              mutate((l) => { l.pipes.find((q) => q.id === pipe.id)!.max_flow_lpm = num(e.target.value); })} />
          </label>
          <label>长度 (m)
            <input type="number" value={pipe.length_m} onChange={(e) =>
              mutate((l) => { l.pipes.find((q) => q.id === pipe.id)!.length_m = num(e.target.value); })} />
          </label>
        </div>
      )}

      {furrow && (
        <div className="form">
          <h4>畦沟 {furrow.name}</h4>
          <label>名称
            <input value={furrow.name} onChange={(e) =>
              mutate((l) => { l.furrows.find((f) => f.id === furrow.id)!.name = e.target.value; })} />
          </label>
          <label>沟尾高程 (m)
            <input type="number" step="0.1" value={furrow.tail_elevation}
                   onChange={(e) => mutate((l) => {
                     l.furrows.find((f) => f.id === furrow.id)!.tail_elevation = num(e.target.value);
                   })} />
          </label>
          <label>润湿下限 (min)
            <input type="number" step="0.1" value={furrow.wet_min_min}
                   onChange={(e) => mutate((l) => {
                     l.furrows.find((f) => f.id === furrow.id)!.wet_min_min = num(e.target.value);
                   })} />
          </label>
          <label>润湿上限 (min)
            <input type="number" step="0.1" value={furrow.wet_max_min}
                   onChange={(e) => mutate((l) => {
                     l.furrows.find((f) => f.id === furrow.id)!.wet_max_min = num(e.target.value);
                   })} />
          </label>
        </div>
      )}

      {zone && (
        <div className="form">
          <h4>禁踩区</h4>
          <label>名称
            <input value={zone.label} onChange={(e) =>
              mutate((l) => { l.zones.find((z) => z.id === zone.id)!.label = e.target.value; })} />
          </label>
        </div>
      )}

      <h4>可携管件</h4>
      {p.layout.fittings.map((ft) => (
        <div className="fitting" key={ft.id}>
          <input value={ft.name} onChange={(e) =>
            mutate((l) => { l.fittings.find((x) => x.id === ft.id)!.name = e.target.value; })} />
          <input type="number" title="软管长度 m" value={ft.hose_length_m}
                 onChange={(e) => mutate((l) => {
                   l.fittings.find((x) => x.id === ft.id)!.hose_length_m = num(e.target.value);
                 })} />
          <span>m ×</span>
          <input type="number" value={ft.count} onChange={(e) =>
            mutate((l) => { l.fittings.find((x) => x.id === ft.id)!.count = num(e.target.value); })} />
          <button onClick={() =>
            mutate((l) => { l.fittings = l.fittings.filter((x) => x.id !== ft.id); })}>
            ✕</button>
        </div>
      ))}
      <button className="mini" onClick={() =>
        mutate((l) => l.fittings.push({
          id: `ft${Date.now()}`, name: "软管", hose_length_m: 6, count: 1,
        }))}>+ 管件</button>

      {p.layout.warnings && p.layout.warnings.length > 0 && (
        <div className="warnbox">
          <h4>布局告警</h4>
          {p.layout.warnings.map((w, i) => <p key={i}>⚠ {w}</p>)}
        </div>
      )}

      <div className="row">
        <button onClick={p.onSeed}>载入示例地块</button>
        <button className="danger" onClick={p.onClear}>清空</button>
      </div>
    </div>
  );
}
