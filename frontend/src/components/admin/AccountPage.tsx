import { FormEvent, useState } from "react";
import { api, ApiError, Role } from "../../api";

export function AccountPage({ username, role }: { username: string; role: Role | undefined }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);
    if (next !== repeat) {
      setError("The new passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(current, next);
      setMessage("Password changed. Your other sessions were signed out.");
      setCurrent("");
      setNext("");
      setRepeat("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setError("The current password is incorrect.");
      else if (err instanceof ApiError && err.status === 429) setError("Too many failed attempts. Try again later.");
      else setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="setup">
      <h1 className="page-title">My account</h1>
      <p className="notice">Signed in as <strong>{username}</strong> ({role ?? "unknown role"}).</p>
      <form className="card dialog" onSubmit={submit} aria-label="Change password">
        <h2>Change password</h2>
        <label className="field">Current password
          <input type="password" autoComplete="current-password" required value={current}
            onChange={(e) => setCurrent(e.target.value)} /></label>
        <label className="field">New password (at least 12 characters)
          <input type="password" autoComplete="new-password" minLength={12} required value={next}
            onChange={(e) => setNext(e.target.value)} /></label>
        <label className="field">Repeat the new password
          <input type="password" autoComplete="new-password" minLength={12} required value={repeat}
            onChange={(e) => setRepeat(e.target.value)} /></label>
        {error && <p className="error" role="alert">{error}</p>}
        {message && <p className="message" role="status">{message}</p>}
        <div className="actions"><button type="submit" disabled={busy}>Change password</button></div>
      </form>
    </div>
  );
}
