import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, Role, ROLE_ORDER, UserAccount } from "../../api";
import { PasswordDialog } from "../faces/PasswordDialog";

const ROLE_HELP: Record<Role, string> = {
  viewer: "live view, crossings and alerts (no names, faces or footage)",
  operator: "also face events, faces, footage, people records; acknowledge alerts, silence the alarm",
  admin: "also enrollment, recognition, gate lines, alarm tests, cameras, accounts, privacy",
};

type Pending = { title: string; label: string; danger?: boolean; text: string; run: (password: string) => Promise<unknown> };

export function UsersPage({ me }: { me: string }) {
  const [users, setUsers] = useState<UserAccount[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [form, setForm] = useState({ username: "", role: "operator" as Role, password: "" });

  const load = useCallback(async () => {
    try {
      setUsers((await api.users()).items);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const ask = (p: Pending) => setPending({
    ...p,
    run: async (password) => {
      await p.run(password);
      setPending(null);
      setMessage(`${p.title}: done.`);
      load();
    },
  });

  const create = (e: FormEvent) => {
    e.preventDefault();
    const { username, role, password } = form;
    ask({ title: "Create account", label: "Create", text: `${username} (${role})`,
      run: async (pw) => {
        await api.createUser(username, role, password, pw);
        setForm({ username: "", role: "operator", password: "" });
      } });
  };
  const reset = (u: UserAccount) => {
    const next = window.prompt(`New password for ${u.username} (at least 12 characters):`);
    if (!next) return;
    ask({ title: "Reset password", label: "Reset", text: `${u.username} is signed out everywhere.`,
      run: (pw) => api.resetUserPassword(u.id, next, pw) });
  };

  return (
    <div className="setup">
      <h1 className="page-title">Accounts</h1>
      <p className="notice">
        Roles: {ROLE_ORDER.map((r) => <span key={r}><strong>{r}</strong>: {ROLE_HELP[r]}. </span>)}
        Every change needs your password and is audited. The last active administrator cannot be removed; if every
        administrator password is lost, run <code>docker compose exec api ai-surveillance create-admin &lt;name&gt;</code> on
        the host.
      </p>
      {error && <p className="error" role="alert">{error}</p>}
      {message && <p className="message" role="status">{message}</p>}
      <section className="card" aria-label="Account list">
        <table className="audit">
          <thead><tr><th>User</th><th>Role</th><th>State</th><th>Actions</th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.username}{u.username === me ? " (you)" : ""}</td>
                <td>
                  <select aria-label={`Role of ${u.username}`} value={u.role}
                    onChange={(e) => {
                      const role = e.target.value as Role;
                      ask({ title: "Change role", label: "Change", text: `${u.username}: ${u.role} → ${role}`,
                        run: (pw) => api.updateUser(u.id, { role }, pw) });
                    }}>
                    {ROLE_ORDER.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </td>
                <td>{u.disabled ? "disabled" : "active"}</td>
                <td className="actions">
                  <button className="secondary" onClick={() => reset(u)}>Reset password</button>
                  {u.username !== me && (
                    <button className="secondary" onClick={() => ask({
                      title: u.disabled ? "Enable account" : "Disable account", label: u.disabled ? "Enable" : "Disable",
                      text: u.username, run: (pw) => api.updateUser(u.id, { disabled: !u.disabled }, pw) })}>
                      {u.disabled ? "Enable" : "Disable"}
                    </button>
                  )}
                  {u.username !== me && (
                    <button className="secondary danger" onClick={() => ask({ title: "Delete account", label: "Delete",
                      danger: true, text: `${u.username} is deleted.`, run: (pw) => api.deleteUser(u.id, pw) })}>
                      Delete
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <form className="card form-grid" onSubmit={create} aria-label="New account">
        <h2 className="span-2">New account</h2>
        <label>Username<input value={form.username} pattern="[A-Za-z0-9._\-]{3,64}" required
          onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))} /></label>
        <label>Role
          <select value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as Role }))}>
            {ROLE_ORDER.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <label className="span-2">Initial password (at least 12 characters)
          <input type="password" autoComplete="new-password" minLength={12} required value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} /></label>
        <div className="actions span-2"><button type="submit">Create account</button></div>
      </form>
      {pending && (
        <PasswordDialog title={pending.title} confirmLabel={pending.label} danger={pending.danger}
          onConfirm={async (pw) => { await pending.run(pw); }} onCancel={() => setPending(null)}>
          <p>{pending.text}</p>
        </PasswordDialog>
      )}
    </div>
  );
}
