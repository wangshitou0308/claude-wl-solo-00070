import { useEffect, useState } from "react";
import type { FurrowT, Layout, SessionView, StepT } from "../types";

const STEP_ICON: Record<string, string> = {
  PREFILL_MAIN: "💧", PREFILL_BRANCH: "🚰", OPEN_OUTLET: "🟢",
  AWAIT_TAIL: "👁", CLOSE_OUTLET: "🔴", MOVE_PIPE: "🧰",
  FIX_ISSUE: "🛠", END_SESSION: "🏁",
};

interface Props {
  view: SessionView | null;
  layout: Layout;
  onStart: (flow: number) => void;
  onRestart: (flow: number) => void;
  onConfirm: (step: StepT) => void;
  onIssue: (furrow_id: string, kind: string) => void;
  onUndo: () => void;
  onAbort: () => void;
  routeArmed: boolean;
  onToggleRoute: () => void;
  onFinishRoute: () => void;
  onCancelRoute: () => void;
}

function TailTimer({ furrow }: { furrow?: FurrowT }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);
  if (!furrow?.opened_at) return null;
  const elapsed = (Date.now() - new Date(furrow.opened_at).getTime()) / 60000;
  const pct = Math.min(100, (elapsed / furrow.wet_max_min) * 100);
  const cls = elapsed < furrow.wet_min_min ? "bar min"
    : elapsed > furrow.wet_max_min ? "bar over" : "bar ok";
  return (
    <div className="timer">
      <div className={cls}><i style={{ width: `${pct}%` }} /></div>
      <span>
        已供水 {elapsed.toFixed(1)} 分钟（下限 {furrow.wet_min_min} /
        上限 {furrow.wet_max_min}）
        {elapsed < furrow.wet_min_min && " · 未到最短润湿时间"}
        {elapsed > furrow.wet_max_min && " · 超限，注意漫溢！"}
      </span>
    </div>
  );
}

export default function SessionPanel(p: Props) {
  const [flow, setFlow] = useState(8);
  const v = p.view;

  if (!v?.session) {
    return (
      <div className="panel">
        <h3>灌水作业</h3>
        <p className="hint">按当前布局生成完整换口顺序：预充主管 → 开上游畦口
          → 确认水头到尾 → 关旧口 → 移管 → 开新口。</p>
        <label>给水流量 (L/min)
          <input type="number" value={flow}
                 onChange={(e) => setFlow(Number(e.target.value))} />
        </label>
        <button className="primary" onClick={() => p.onStart(flow)}>
          开始灌水作业
        </button>
      </div>
    );
  }

  const s = v.session;
  const cur = v.steps.find((x) => x.id === v.current_step_id);
  const curFurrow = cur?.payload?.furrow_id
    ? v.furrows.find((f) => f.id === cur.payload.furrow_id) : undefined;
  const done = s.status !== "active";
  const nodeLabel = (id: string | null) => {
    if (!id) return "—";
    const n = p.layout.nodes.find((n) => n.id === id);
    return n ? n.label || n.id : id;
  };

  return (
    <div className="panel">
      <h3>灌水作业 {done && (s.status === "done" ? "（已完成）" : "（已中止）")}</h3>
      <div className="chips">
        <span className={s.state.main_charged ? "chip on" : "chip"}>
          主管{s.state.main_charged ? "已充" : "未充"}</span>
        <span className="chip">开口 {nodeLabel(s.state.open_outlet)}</span>
        <span className="chip">软管在 {nodeLabel(s.state.hose_at)}</span>
      </div>

      {done && (
        <div className="current">
          <p className="hint">
            {s.status === "done"
              ? "本轮灌水完成。重置畦沟为待灌后可开始新一轮。"
              : "作业已中止。"}
          </p>
          <button className="primary" onClick={() => p.onRestart(flow)}>
            重置并开始新一轮
          </button>
        </div>
      )}

      {cur && !done && (
        <div className="current">
          <div className="curtext">{STEP_ICON[cur.type]} {cur.text}</div>
          {cur.warning && <p className="warn">⚠ {cur.warning}</p>}
          {cur.type === "AWAIT_TAIL" && <TailTimer furrow={curFurrow} />}
          {cur.type === "MOVE_PIPE" && (
            <div className="row">
              {!p.routeArmed ? (
                <button className="mini" onClick={p.onToggleRoute}>
                  自定义绕行路线</button>
              ) : (
                <>
                  <button className="mini" onClick={p.onFinishRoute}>完成路线</button>
                  <button className="mini" onClick={p.onCancelRoute}>取消</button>
                </>
              )}
            </div>
          )}
          <div className="row">
            <button className="primary" onClick={() => p.onConfirm(cur)}>
              确认完成
            </button>
            {(cur.payload?.furrow_id || curFurrow) && (
              <>
                <button className="mini danger"
                        onClick={() => p.onIssue(cur.payload.furrow_id, "blocked")}>
                  堵沟</button>
                <button className="mini danger"
                        onClick={() => p.onIssue(cur.payload.furrow_id, "leak")}>
                  漏接</button>
                <button className="mini danger"
                        onClick={() => p.onIssue(cur.payload.furrow_id, "no_tail")}>
                  水未到尾</button>
              </>
            )}
          </div>
        </div>
      )}

      <div className="row">
        <button className="mini" disabled={!v.can_undo} onClick={p.onUndo}>
          ↩ 撤回上一步
        </button>
        {!done && (
          <button className="mini danger" onClick={p.onAbort}>中止作业</button>
        )}
      </div>

      <ol className="steps">
        {v.steps.map((st) => (
          <li key={st.id}
              className={`step ${st.status} ${st.id === v.current_step_id ? "cur" : ""}`}>
            <span className="ic">{STEP_ICON[st.type]}</span>
            <span>{st.text}</span>
            {st.warning && <em className="warn">⚠ {st.warning}</em>}
          </li>
        ))}
      </ol>
    </div>
  );
}
