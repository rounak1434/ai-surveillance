import { useCallback, useEffect, useState } from "react";
import { AlarmStatus, Alert, api, atLeast, Role } from "../../api";
import { PasswordDialog } from "../faces/PasswordDialog";
import { ALARM_LABEL } from "./labels";

const REFRESH_MS = 5000;
const KIND_LABEL: Record<Alert["kind"], string> = {
  unauthorized_entry: "Unauthorized entry",
  needs_review: "Needs review",
  alarm_test: "Alarm test",
};
const OUTPUT_LABEL: Record<AlarmStatus["output"], string> = {
  simulation: "Simulation: nothing is switched; alerts record what would have happened",
  http_relay: "Network relay (physical output)",
  none: "No alarm output: alerts only",
};

function AlarmPanel({ alarm, role, onChange }: { alarm: AlarmStatus; role: Role | undefined; onChange: () => void }) {
  const [minutes, setMinutes] = useState(15);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const silenced = alarm.silenced_until && new Date(alarm.silenced_until) > new Date();

  const run = async (action: () => Promise<unknown>, done: string) => {
    setError(null);
    try {
      await action();
      setMessage(done);
      onChange();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  const test = async (password: string) => {
    const result = await api.testAlarm(password);
    setTesting(false);
    setMessage(`Test recorded: ${ALARM_LABEL[result.alert?.alarm ?? "none"]}.`);
    onChange();
  };

  return (
    <section className="card" aria-label="Alarm">
      <h2>Alarm</h2>
      <dl className="facts">
        <dt>Output</dt><dd>{OUTPUT_LABEL[alarm.output]}</dd>
        {alarm.physical && <><dt>Configured</dt><dd>{alarm.configured ? "yes" : `no: ${alarm.problem ?? "see .env"}`}</dd></>}
        <dt>State</dt>
        <dd>{silenced ? `silenced until ${new Date(alarm.silenced_until!).toLocaleTimeString()}` : "armed"}</dd>
        <dt>Duration / cooldown</dt><dd>{alarm.duration_seconds} s / {alarm.cooldown_seconds} s</dd>
        <dt>Delivery</dt><dd>in-app{alarm.webhook ? " + LAN webhook" : ""}</dd>
        {alarm.last_error && <><dt>Last error</dt><dd className="error">{alarm.last_error}</dd></>}
      </dl>
      <p className="muted small">
        The alarm fires only for an entry that is not matched to an authorized person (one clear face) on a gate line
        with "alarm on unauthorized" switched on. Uncertain results are alerts for review, never alarms.
      </p>
      {atLeast(role, "operator") && (
        <div className="actions">
          {silenced ? (
            <button onClick={() => run(api.unsilenceAlarm, "Alarm re-armed.")}>Re-arm now</button>
          ) : (
            <>
              <select aria-label="Silence for" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
                {[5, 15, 30, 60, 120, 240].filter((m) => m <= alarm.max_silence_minutes)
                  .map((m) => <option key={m} value={m}>{m} minutes</option>)}
              </select>
              <button className="secondary" onClick={() => run(() => api.silenceAlarm(minutes), `Silenced for ${minutes} minutes.`)}>
                Silence
              </button>
            </>
          )}
          {atLeast(role, "admin") && <button className="secondary" onClick={() => setTesting(true)}>Test alarm</button>}
        </div>
      )}
      {message && <p className="message" role="status">{message}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {testing && (
        <PasswordDialog title="Test the alarm" confirmLabel="Run test" onConfirm={test} onCancel={() => setTesting(false)}>
          <p>{alarm.physical ? "The configured relay is switched on for the configured duration." :
            "Simulation: nothing is switched; the test is recorded as an alert."}</p>
        </PasswordDialog>
      )}
    </section>
  );
}

export function AlertsPage({ role }: { role: Role | undefined }) {
  const [alarm, setAlarm] = useState<AlarmStatus | null>(null);
  const [items, setItems] = useState<Alert[]>([]);
  const [onlyOpen, setOnlyOpen] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, list] = await Promise.all([api.alarm(), api.alerts(onlyOpen ? "open" : undefined)]);
      setAlarm(a);
      setItems(list.items);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [onlyOpen]);

  useEffect(() => {
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => clearInterval(t);
  }, [load]);

  const ack = async (id: string) => {
    try {
      await api.acknowledgeAlert(id);
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="setup">
      <h1 className="page-title">Alerts</h1>
      {error && <p className="error" role="alert">{error}</p>}
      {alarm && <AlarmPanel alarm={alarm} role={role} onChange={load} />}
      <section className="card" aria-label="Alert list">
        <div className="camera-head">
          <h2>{onlyOpen ? "Open alerts" : "All alerts"}</h2>
          <label className="checkbox"><input type="checkbox" checked={onlyOpen}
            onChange={(e) => setOnlyOpen(e.target.checked)} />open only</label>
        </div>
        {items.length === 0 && <p className="muted">No alerts.</p>}
        <ul className="captures">
          {items.map((a) => (
            <li key={a.id} className="capture-item">
              <div className="capture-row alert-row">
                <span className="muted">{new Date(a.created_at).toLocaleString()}</span>
                <span className={`status ${a.kind === "unauthorized_entry" ? "status-bad" : a.kind === "needs_review" ? "status-warn" : "status-neutral"}`}>
                  {KIND_LABEL[a.kind]}
                </span>
                <span>{a.camera ?? ""} {a.detail}</span>
                <span className="muted small">
                  {ALARM_LABEL[a.alarm] ?? a.alarm}{a.delivery ? ` · ${a.delivery}` : ""}
                  {a.status === "acknowledged" ? ` · acknowledged by ${a.acknowledged_by}` : ""}
                </span>
              </div>
              {a.status === "open" && atLeast(role, "operator") && (
                <button className="secondary" onClick={() => ack(a.id)}>Acknowledge</button>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
