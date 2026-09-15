import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import Canvas from "./components/Canvas";
import EditPanel from "./components/EditPanel";
import SessionPanel from "./components/SessionPanel";
import type { Layout, Selection, SessionView, StepT, Tool } from "./types";

const EMPTY: Layout = {
  nodes: [], pipes: [], furrows: [], zones: [], fittings: [],
};

export default function App() {
  const [layout, setLayout] = useState<Layout | null>(null);
  const [view, setView] = useState<SessionView | null>(null);
  const [mode, setMode] = useState<"edit" | "run">("edit");
  const [tool, setTool] = useState<Tool>("select");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [routeDraft, setRouteDraft] = useState<[number, number][] | null>(null);
  const dirty = useRef(false);

  const showToast = useCallback((m: string) => {
    setToast(m);
    setTimeout(() => setToast(null), 4500);
  }, []);

  const refreshView = useCallback(async () => {
    try {
      const v = await api.activeSession();
      setView(v);
      if (v.notice) showToast(v.notice);
    } catch {
      /* no active session */
    }
  }, [showToast]);

  useEffect(() => {
    api.getLayout().then(setLayout).catch((e) => showToast(e.message));
    refreshView();
  }, [refreshView, showToast]);

  // 编辑自动保存（防抖）
  useEffect(() => {
    if (!layout || !dirty.current) return;
    const t = setTimeout(async () => {
      dirty.current = false;
      try {
        setLayout(await api.putLayout(layout));
      } catch (e) {
        showToast((e as Error).message);
      }
    }, 600);
    return () => clearTimeout(t);
  }, [layout, showToast]);

  // 作业模式轮询
  useEffect(() => {
    if (mode !== "run") return;
    const t = setInterval(refreshView, 3000);
    return () => clearInterval(t);
  }, [mode, refreshView]);

  const onLayout = (l: Layout) => {
    dirty.current = true;
    setLayout(l);
  };

  const seed = async () => {
    try {
      setLayout(await api.seedDemo());
      showToast("已载入示例地块");
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  const clear = async () => {
    try {
      setLayout(await api.putLayout(EMPTY));
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  const start = async (flow: number) => {
    try {
      if (dirty.current && layout) setLayout(await api.putLayout(layout));
      dirty.current = false;
      setView(await api.createSession(flow));
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  // 新一轮：保存布局（无进行中作业时畦沟自动重置为待灌）后开作业
  const restart = async (flow: number) => {
    try {
      if (layout) setLayout(await api.putLayout(layout));
      dirty.current = false;
      setView(await api.createSession(flow));
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  const guard = async (fn: () => Promise<SessionView>) => {
    try {
      const v = await fn();
      setView(v);
      if (v.notice) showToast(v.notice);
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  const sid = view?.session?.id ?? "";
  const currentStep = view?.steps.find((s) => s.id === view.current_step_id);

  return (
    <div className="app">
      <header>
        <h1>坡地菜畦重力灌水换口台</h1>
        <nav>
          <button className={mode === "edit" ? "on" : ""}
                  onClick={() => setMode("edit")}>地块编辑</button>
          <button className={mode === "run" ? "on" : ""}
                  onClick={() => { setMode("run"); refreshView(); }}>
            灌水作业</button>
        </nav>
        {view?.session && (
          <span className="sess">
            作业 {view.session.id.slice(-6)} · {view.session.flow_lpm} L/min
          </span>
        )}
      </header>

      <main>
        {layout && (
          <Canvas
            layout={layout}
            mode={mode}
            tool={tool}
            selection={selection}
            onSelect={setSelection}
            onLayout={onLayout}
            view={view}
            routeDraft={routeDraft}
            onRouteDraft={setRouteDraft}
            onToast={showToast}
          />
        )}
        {mode === "edit" ? (
          <EditPanel
            layout={layout ?? EMPTY}
            tool={tool}
            setTool={setTool}
            selection={selection}
            onLayout={onLayout}
            onSeed={seed}
            onClear={clear}
            onToast={showToast}
          />
        ) : (
          <SessionPanel
            view={view}
            layout={layout ?? EMPTY}
            onStart={start}
            onRestart={restart}
            onConfirm={(st: StepT) =>
              guard(() => api.confirm(sid, st.id))}
            onIssue={(fid, kind) =>
              guard(() => api.issue(sid, fid, kind))}
            onUndo={() => guard(() => api.undo(sid))}
            onAbort={() =>
              guard(() => api.abort(sid).then(() => api.activeSession()))}
            routeArmed={routeDraft !== null}
            onToggleRoute={() => setRouteDraft([])}
            onFinishRoute={() => {
              if (currentStep && routeDraft && routeDraft.length >= 2) {
                guard(() => api.setRoute(sid, currentStep.id, routeDraft));
              }
              setRouteDraft(null);
            }}
            onCancelRoute={() => setRouteDraft(null)}
          />
        )}
      </main>

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
