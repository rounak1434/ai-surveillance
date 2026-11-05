import { MouseEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, atLeast, Camera, GateCrossing, GateLine, GateLineInput, GateStatus, Point, Role } from "../../api";
import { PasswordDialog } from "../faces/PasswordDialog";
import { FootagePlayer } from "./FootagePlayer";
import { GATE_REASON, VERDICT_CLASS, VERDICT_LABEL } from "./labels";

const REFRESH_MS = 10000;

type Draft = Omit<GateLineInput, "password" | "x1" | "y1" | "x2" | "y2"> & { p1: Point | null; p2: Point | null };

const fromLine = (l: GateLine | undefined, camera: string): Draft => ({
  name: l?.name ?? `${camera} gate`, p1: l?.p1 ?? null, p2: l?.p2 ?? null, in_side: l?.in_side ?? "right",
  record_exits: l?.record_exits ?? true, enabled: l?.enabled ?? true,
  alarm_on_unauthorized: l?.alarm_on_unauthorized ?? false, cooldown_seconds: l?.cooldown_seconds ?? 10,
});

// The "in" arrow: perpendicular to p1 -> p2, on the in side (image coordinates, y down; same rule as the server).
function arrow(p1: Point, p2: Point, side: "left" | "right") {
  const dx = p2.x - p1.x, dy = p2.y - p1.y;
  const len = Math.hypot(dx, dy) || 1;
  const sign = side === "right" ? 1 : -1;
  const nx = (-dy / len) * sign, ny = (dx / len) * sign;
  const m = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 };
  return { from: m, to: { x: m.x + nx * 0.08, y: m.y + ny * 0.08 } };
}

function LineOverlay({ p1, p2, side }: { p1: Point; p2: Point; side: "left" | "right" }) {
  const a = arrow(p1, p2, side);
  return (
    <svg className="gate-overlay" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">
      <line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} className="gate-line" vectorEffect="non-scaling-stroke" />
      <line x1={a.from.x} y1={a.from.y} x2={a.to.x} y2={a.to.y} className="gate-arrow" vectorEffect="non-scaling-stroke" />
      <circle cx={a.to.x} cy={a.to.y} r={0.008} className="gate-arrow-head" />
    </svg>
  );
}

function CameraGate({ camera, line, role, onSaved }: {
  camera: Camera; line: GateLine | undefined; role: Role | undefined; onSaved: () => void;
}) {
  const isAdmin = atLeast(role, "admin");
  const [draft, setDraft] = useState<Draft>(() => fromLine(line, camera.name));
  const [drawing, setDrawing] = useState(false);
  const [confirm, setConfirm] = useState<"save" | "delete" | null>(null);
  const [frameUrl, setFrameUrl] = useState(() => api.latestFrameUrl(camera.name));
  const [message, setMessage] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => setDraft(fromLine(line, camera.name)), [line, camera.name]);

  const click = (e: MouseEvent<HTMLDivElement>) => {
    if (!drawing || !box.current) return;
    const r = box.current.getBoundingClientRect();
    const p = { x: Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1),
      y: Math.min(Math.max((e.clientY - r.top) / r.height, 0), 1) };
    setDraft((d) => (d.p1 && !d.p2 ? { ...d, p2: p } : { ...d, p1: p, p2: null }));
    if (draft.p1 && !draft.p2) setDrawing(false);
  };

  const save = async (password: string) => {
    if (!draft.p1 || !draft.p2) return;
    const { p1, p2, ...rest } = draft;
    await api.saveGateLine(camera.name, { ...rest, x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y, password });
    setConfirm(null);
    setMessage("Gate line saved.");
    onSaved();
  };
  const remove = async (password: string) => {
    if (!line) return;
    await api.deleteGateLine(line.id, password);
    setConfirm(null);
    setMessage("Gate line deleted.");
    onSaved();
  };
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => ({ ...d, [k]: v }));

  return (
    <section className="card" aria-label={`Gate ${camera.name}`}>
      <div className="camera-head">
        <h2>{camera.name}</h2>
        <span className="muted small">
          {line ? `${line.enabled ? "active" : "switched off"} · updated by ${line.updated_by}` : "no gate line"}
        </span>
      </div>
      <div ref={box} className={`gate-frame${drawing ? " drawing" : ""}`} onClick={click} data-testid="gate-frame">
        <img src={frameUrl} alt={`Current frame of ${camera.name}`} />
        {draft.p1 && draft.p2 && <LineOverlay p1={draft.p1} p2={draft.p2} side={draft.in_side} />}
        {draft.p1 && !draft.p2 && (
          <svg className="gate-overlay" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">
            <circle cx={draft.p1.x} cy={draft.p1.y} r={0.01} className="gate-arrow-head" />
          </svg>
        )}
      </div>
      <p className="muted small">
        The line is drawn on the camera's still frame; the arrow points to the <strong>in</strong> side. A person
        counts where their feet are (bottom of Frigate's box).
      </p>
      <div className="actions">
        <button className="secondary" onClick={() => setFrameUrl(api.latestFrameUrl(camera.name))}>Refresh frame</button>
        {isAdmin && (
          <button className="secondary" onClick={() => { setDraft((d) => ({ ...d, p1: null, p2: null })); setDrawing(true); }}>
            {drawing ? "Click two points on the frame…" : "Draw line"}
          </button>
        )}
      </div>
      {isAdmin && (
        <div className="form-grid gate-form">
          <label>Name<input value={draft.name} maxLength={64} onChange={(e) => set("name", e.target.value)} /></label>
          <label>In side
            <select value={draft.in_side} onChange={(e) => set("in_side", e.target.value as "left" | "right")}>
              <option value="right">right of the line (as drawn)</option>
              <option value="left">left of the line (as drawn)</option>
            </select>
          </label>
          <label>Cooldown (seconds per person)
            <input type="number" min={0} max={3600} value={draft.cooldown_seconds}
              onChange={(e) => set("cooldown_seconds", Number(e.target.value))} />
          </label>
          <label className="checkbox"><input type="checkbox" checked={draft.record_exits}
            onChange={(e) => set("record_exits", e.target.checked)} />Record exits too</label>
          <label className="checkbox"><input type="checkbox" checked={draft.enabled}
            onChange={(e) => set("enabled", e.target.checked)} />Line active</label>
          <label className="checkbox"><input type="checkbox" checked={draft.alarm_on_unauthorized}
            onChange={(e) => set("alarm_on_unauthorized", e.target.checked)} />
            Alarm on unauthorized entry (needs a configured alarm output)</label>
          <div className="actions span-2">
            <button disabled={!draft.p1 || !draft.p2 || !draft.name.trim()} onClick={() => setConfirm("save")}>Save line</button>
            {line && <button className="secondary danger" onClick={() => setConfirm("delete")}>Delete line</button>}
          </div>
        </div>
      )}
      {message && <p className="message" role="status">{message}</p>}
      {confirm === "save" && (
        <PasswordDialog title="Save gate line" confirmLabel="Save" onConfirm={save} onCancel={() => setConfirm(null)}>
          <p>The line decides which crossings are counted{draft.alarm_on_unauthorized ? " and can drive the alarm" : ""}.</p>
        </PasswordDialog>
      )}
      {confirm === "delete" && (
        <PasswordDialog title="Delete gate line" confirmLabel="Delete" danger onConfirm={remove} onCancel={() => setConfirm(null)}>
          <p>The line and all its recorded crossings are deleted.</p>
        </PasswordDialog>
      )}
    </section>
  );
}

export function CrossingList({ role, compact }: { role: Role | undefined; compact?: boolean }) {
  const [items, setItems] = useState<GateCrossing[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [verdict, setVerdict] = useState("");
  const [footage, setFootage] = useState<GateCrossing | null>(null);
  const detailed = atLeast(role, "operator");

  const load = useCallback(async () => {
    try {
      setItems((await api.crossings({ verdict: verdict || undefined }, compact ? 10 : 50)).items);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [verdict, compact]);

  useEffect(() => {
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => clearInterval(t);
  }, [load]);

  return (
    <section className="card" aria-label="Gate crossings">
      <div className="camera-head">
        <h2>Gate crossings</h2>
        <label className="small">Verdict{" "}
          <select value={verdict} onChange={(e) => setVerdict(e.target.value)}>
            <option value="">any</option>
            {Object.entries(VERDICT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {!error && items.length === 0 && <p className="muted">No crossings recorded.</p>}
      <ul className="captures">
        {items.map((c) => (
          <li key={c.id} className="capture-item">
            <div className="capture-row crossing-row">
              <span className="muted">{new Date(c.crossed_at).toLocaleString()}</span>
              <span>{c.camera} · {c.direction === "in" ? "entry" : "exit"}</span>
              <span className={`status ${VERDICT_CLASS[c.verdict]}`}>
                {c.verdict === "AUTHORIZED" && c.person ? `Automated match: ${c.person.display_name ?? "deleted person"}`
                  : VERDICT_LABEL[c.verdict]}
              </span>
              <span className="muted small">{c.reason ? GATE_REASON[c.reason] ?? c.reason : ""}</span>
            </div>
            {detailed && (
              <button className="secondary" onClick={() => setFootage(c)} aria-label={`Footage of crossing ${c.id}`}>
                Footage
              </button>
            )}
          </li>
        ))}
      </ul>
      {footage && (
        <FootagePlayer kind="crossings" id={footage.id} onClose={() => setFootage(null)}
          title={`${footage.camera} · ${new Date(footage.crossed_at).toLocaleString()}`} />
      )}
    </section>
  );
}

export function GatePage({ role }: { role: Role | undefined }) {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [lines, setLines] = useState<GateLine[]>([]);
  const [status, setStatus] = useState<GateStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [cams, gate] = await Promise.all([api.cameras(), api.gateLines()]);
      setCameras(cams);
      setLines(gate.items);
      setStatus(gate.status);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="setup">
      <h1 className="page-title">Gate</h1>
      <p className="notice">
        Each person Frigate tracks is followed across frames; one crossing is recorded each time they cross the line
        in either direction. Entries are checked at once against the authorized people while recognition is on:
        uncertain or poor-quality faces are marked <strong>needs review</strong>, never unauthorized.
        {status && !status.tracking && <><br /><strong>{status.note}</strong></>}
        {status?.tracking && !status.mqtt.connected && (
          <><br /><strong>The event stream from Frigate is disconnected: crossings are not counted until it reconnects.</strong></>
        )}
      </p>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="grid">
        {cameras.map((c) => (
          <CameraGate key={c.name} camera={c} role={role} line={lines.find((l) => l.camera === c.name)} onSaved={load} />
        ))}
      </div>
      <CrossingList role={role} />
    </div>
  );
}
