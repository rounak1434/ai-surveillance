import { useCallback, useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { api, ApiError, atLeast, Camera, Health, Me, Role, setUnauthorizedHandler } from "./api";
import { AccountPage } from "./components/admin/AccountPage";
import { PrivacyPage } from "./components/admin/PrivacyPage";
import { UsersPage } from "./components/admin/UsersPage";
import { AnalysisPage } from "./components/analysis/AnalysisPage";
import { CameraTile } from "./components/CameraTile";
import { Captures } from "./components/Captures";
import { AlertsPage } from "./components/events/AlertsPage";
import { GatePage } from "./components/events/GatePage";
import { FaceEventsPage } from "./components/faces/FaceEventsPage";
import { PeoplePage } from "./components/faces/PeoplePage";
import { Login } from "./components/Login";
import { SetupPage } from "./components/setup/SetupPage";

const DEFAULT_APP_NAME = "AI Surveillance";

const tab = ({ isActive }: { isActive: boolean }) => (isActive ? "tab active" : "tab");

function LivePage({ role }: { role: Role | undefined }) {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const canCapture = atLeast(role, "operator");

  const loadCameras = useCallback(async () => {
    try {
      setCameras(await api.cameras());
      setCameraError(null);
    } catch (err) {
      setCameraError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    loadCameras();
  }, [loadCameras]);

  return (
    <>
      {cameraError && <p className="error">Cameras unavailable: {cameraError}</p>}
      {!cameraError && cameras.length === 0 && <p className="muted">No cameras configured.</p>}
      <section className="grid">
        {cameras.map((c) => (
          <CameraTile key={c.name} camera={c} canCapture={canCapture} onCaptured={() => setRefreshKey((k) => k + 1)} />
        ))}
      </section>
      {canCapture && <Captures refreshKey={refreshKey} />}
    </>
  );
}

export function App() {
  const [user, setUser] = useState<Me | null | undefined>(undefined); // undefined = checking
  const [health, setHealth] = useState<Health | null>(null);
  const [loginNotice, setLoginNotice] = useState<string | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);

  const appName = health?.app ?? DEFAULT_APP_NAME;

  const checkSession = useCallback(() => {
    setBootError(null);
    api.me().then((me) => setUser(me)).catch((err) => {
      // Only "not signed in" shows the login form; a server or network
      // failure must not look like a logout.
      if (err instanceof ApiError && err.status === 401) setUser(null);
      else setBootError(err instanceof ApiError ? err.message : "The server could not be reached.");
    });
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    checkSession();
  }, [checkSession]);

  // Any 401 from a protected endpoint means the session expired or was revoked.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser((current) => {
        if (current) setLoginNotice("Your session has expired. Please sign in again.");
        return null;
      });
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    document.title = appName;
  }, [appName]);

  if (user === undefined) {
    return bootError ? (
      <div className="center">
        <p className="error" role="alert">{bootError}</p>
        <button onClick={checkSession}>Retry</button>
      </div>
    ) : (
      <p className="center muted">Loading…</p>
    );
  }
  if (user === null) {
    const signedIn = (me: Me) => {
      setLoginNotice(null);
      setUser(me); // the login answer carries the role
    };
    return <Login appName={appName} onSignedIn={signedIn} notice={loginNotice} />;
  }

  const logout = async () => {
    await api.logout().catch(() => undefined);
    setLoginNotice(null);
    setUser(null);
  };

  // Accounts created before roles existed were administrators; an answer without a role is one of those.
  const role: Role = user.role ?? "admin";
  const operator = atLeast(role, "operator");
  const admin = atLeast(role, "admin");

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-left">
          <h1>{appName}</h1>
          <nav className="tabs" aria-label="Sections">
            <NavLink to="/live" className={tab}>Live</NavLink>
            <NavLink to="/gate" className={tab}>Gate</NavLink>
            <NavLink to="/alerts" className={tab}>Alerts</NavLink>
            {operator && <NavLink to="/events" className={tab}>Face events</NavLink>}
            {operator && <NavLink to="/people" className={tab}>People</NavLink>}
            {operator && <NavLink to="/analysis" className={tab}>AI analysis</NavLink>}
            {admin && <NavLink to="/setup" className={tab}>Camera &amp; NVR Setup</NavLink>}
            {admin && <NavLink to="/users" className={tab}>Accounts</NavLink>}
            {admin && <NavLink to="/privacy" className={tab}>Privacy</NavLink>}
          </nav>
        </div>
        <div className="topbar-right">
          <span className={`dot ${health?.frigate.reachable ? "ok" : "bad"}`} />
          <span className="muted">
            {health?.frigate.reachable ? `Engine ${health.frigate.version}` : "Engine unreachable"}
          </span>
          <span className={`dot ${health?.inference?.reachable ? "ok" : "bad"}`} />
          <span className="muted">{health?.inference?.reachable ? "AI ready" : "AI unreachable"}</span>
          {health?.mqtt?.enabled && (
            <>
              <span className={`dot ${health.mqtt.connected ? "ok" : "bad"}`} />
              <span className="muted">{health.mqtt.connected ? "Events live" : "Events delayed"}</span>
            </>
          )}
          <NavLink to="/account" className="muted">{user.username} ({role})</NavLink>
          <button className="secondary" onClick={logout}>Sign out</button>
        </div>
      </header>
      <main className="content">
        <Routes>
          <Route path="/live" element={<LivePage role={role} />} />
          <Route path="/gate" element={<GatePage role={role} />} />
          <Route path="/alerts" element={<AlertsPage role={role} />} />
          {operator && <Route path="/events" element={<FaceEventsPage />} />}
          {operator && <Route path="/people" element={<PeoplePage />} />}
          {operator && <Route path="/analysis" element={<AnalysisPage />} />}
          {admin && <Route path="/setup" element={<SetupPage />} />}
          {admin && <Route path="/users" element={<UsersPage me={user.username} />} />}
          {admin && <Route path="/privacy" element={<PrivacyPage />} />}
          <Route path="/account" element={<AccountPage username={user.username} role={role} />} />
          <Route path="*" element={<Navigate to="/live" replace />} />
        </Routes>
      </main>
    </div>
  );
}
