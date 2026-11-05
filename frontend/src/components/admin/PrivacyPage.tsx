import { useCallback, useEffect, useState } from "react";
import { api, Capabilities, PrivacyOverview } from "../../api";
import { PasswordDialog } from "../faces/PasswordDialog";

const RETENTION_LABEL: Record<string, string> = {
  face_events: "Face events (frames, crops, results)",
  captures: "Snapshots, clips and event footage",
  gate_crossings: "Gate crossings",
  alerts: "Alerts",
  audit_log: "Audit log",
  frigate_recordings: "Frigate recordings (set in Frigate's config)",
};

const days = (n: number) => (n > 0 ? `${n} days` : "kept until deleted");

export function PrivacyPage() {
  const [data, setData] = useState<PrivacyOverview | null>(null);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"retention" | "embeddings" | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, c] = await Promise.all([api.privacy(), api.capabilities()]);
      setData(p);
      setCaps(c);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const runRetention = async (password: string) => {
    const r = await api.runRetention(password);
    setConfirm(null);
    setMessage("Retention applied: " + Object.entries(r.deleted).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(", "));
    load();
  };
  const purge = async (password: string) => {
    const r = await api.purgeEmbeddings(password);
    setConfirm(null);
    setMessage(`${r.deleted_embeddings} embedding(s) deleted${r.recognition_switched_off ? "; recognition switched off" : ""}.`);
    load();
  };

  return (
    <div className="setup">
      <h1 className="page-title">Privacy &amp; retention</h1>
      {error && <p className="error" role="alert">{error}</p>}
      {message && <p className="message" role="status">{message}</p>}
      {data && (
        <>
          <section className="card" aria-label="Retention">
            <h2>Retention</h2>
            <dl className="facts">
              {Object.entries(data.retention_days).map(([k, v]) => (
                <span key={k} style={{ display: "contents" }}><dt>{RETENTION_LABEL[k] ?? k}</dt><dd>{days(v)}</dd></span>
              ))}
              <dt>Reference images and embeddings</dt><dd>kept until the person or image is deleted (People page)</dd>
            </dl>
            <p className="muted small">Periods are set in deploy/.env (docs/PRIVACY.md) and applied hourly.</p>
            <div className="actions">
              <button className="secondary" onClick={() => setConfirm("retention")}>Apply retention now</button>
              <button className="secondary danger" onClick={() => setConfirm("embeddings")}>Delete all reference embeddings</button>
            </div>
          </section>
          <section className="card" aria-label="Stored data">
            <h2>Stored now</h2>
            <dl className="facts">
              {Object.entries(data.counts).map(([k, v]) => (
                <span key={k} style={{ display: "contents" }}><dt>{k.replace(/_/g, " ")}</dt><dd>{v}</dd></span>
              ))}
            </dl>
          </section>
          <section className="card" aria-label="Encryption and backups">
            <h2>Encryption and backups</h2>
            <p>{data.encryption.biometric_data} Key: {data.encryption.key_source}.</p>
            <p>{data.encryption.not_encrypted}</p>
            <p className="muted small">
              A backup must contain the database, <code>media/gallery</code> and the credentials key; without the key
              the reference images and embeddings cannot be decrypted. Keep the key apart from the backups. Backups
              still contain people deleted later, until those backups are deleted (docs/PRIVACY.md).
            </p>
          </section>
        </>
      )}
      {caps && (
        <section className="card" aria-label="Estimators">
          <h2>Face attribute estimates and liveness</h2>
          <dl className="facts">
            <dt>Attribute estimates</dt>
            <dd>{caps.attributes.installed ? `${caps.attributes.model} (${caps.attributes.status})` : "no model installed: shown as unknown"}</dd>
            <dt>Presentation-attack check</dt>
            <dd>{caps.liveness.installed ? `${caps.liveness.model} (${caps.liveness.status})` : "unavailable: no model installed"}</dd>
          </dl>
          <p className="muted small">{caps.attributes.note} {caps.liveness.note}</p>
        </section>
      )}
      {confirm === "retention" && (
        <PasswordDialog title="Apply retention now" confirmLabel="Apply" onConfirm={runRetention} onCancel={() => setConfirm(null)}>
          <p>Deletes everything older than the periods above, now instead of at the next hourly run.</p>
        </PasswordDialog>
      )}
      {confirm === "embeddings" && (
        <PasswordDialog title="Delete all reference embeddings" confirmLabel="Delete" danger onConfirm={purge}
          onCancel={() => setConfirm(null)}>
          <p>Every stored embedding is deleted and recognition is switched off. Reference images stay; switching
            recognition on again computes the embeddings from them.</p>
        </PasswordDialog>
      )}
    </div>
  );
}
