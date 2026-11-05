// Typed wrapper around the backend API. All requests are same-origin and
// rely on the httpOnly session cookie; no token is ever stored in JS.

export type Camera = {
  name: string;
  enabled: boolean;
  detect_width: number | null;
  detect_height: number | null;
  recording: boolean;
};

export type Capture = {
  id: string;
  camera: string;
  kind: "snapshot" | "clip";
  status: "pending" | "ready" | "failed";
  created_at: string;
  size_bytes: number | null;
  duration_seconds: number | null;
  error: string | null;
  file_url: string | null;
  source?: string | null; // "face_event:<id>" / "crossing:<id>" for event footage
};

export type Health = {
  status: string;
  app: string;
  version: string;
  frigate: { reachable: boolean; version?: string; error?: string };
  inference?: { reachable: boolean; models_ready?: boolean; error?: string };
  mqtt?: { enabled: boolean; connected: boolean };
};

export type DeviceKind = "ip_camera" | "nvr" | "synthetic";

export type DeviceStatus =
  | "not_tested"
  | "connected"
  | "unreachable"
  | "invalid_credentials"
  | "stream_not_found"
  | "reachable_unverified"
  | "address_not_allowed"
  | "error";

export type StreamTest = {
  status: DeviceStatus;
  detail: string;
  codec: string | null;
  width: number | null;
  height: number | null;
  fps: number | null;
};

// What the server returns: never a password or a credential-bearing URL.
export type Device = {
  id: string;
  name: string;
  kind: DeviceKind;
  source_label: string;
  host: string;
  rtsp_port: number;
  username: string | null;
  has_password: boolean;
  main_stream: string;
  sub_stream: string | null;
  main_url_display: string;
  sub_url_display: string | null;
  status: DeviceStatus;
  status_detail: string | null;
  tested_at: string | null;
  streams: Partial<Record<"main" | "sub", StreamTest>>;
  editable: boolean;
  use_in_frigate: boolean;
};

export type FrigateApplyResult = {
  cameras: { device_id: string; name: string; camera: string }[];
  skipped: { device_id: string; name: string; reason: string }[];
  restarts: number;
};

export type DeviceInput = {
  name: string;
  kind: "ip_camera" | "nvr";
  host: string;
  rtsp_port: number;
  username: string | null;
  password: string | null; // null on edit = keep the stored password
  clear_password?: boolean;
  main_stream: string;
  sub_stream: string | null;
};

export type Box = { x: number; y: number; w: number; h: number };

export type FaceQuality = {
  face_px: number;
  small_face: boolean;
  touches_edge: boolean;
  sharpness: number | null;
};

export type AnalysedFace = {
  index: number;
  box: Box;
  score: number;
  keypoints5: [number, number][];
  quality: FaceQuality | null;
  crop: { box: Box; width: number; height: number; data_url: string } | null;
};

export type FaceAnalysis = {
  status: "faces_detected" | "no_faces_detected";
  source: "inference";
  image: { width: number; height: number; format: string };
  faces: AnalysedFace[];
  face_count: number;
  parameters: { min_score: number; max_faces: number; crop_margin: number; small_face_px?: number } | null;
  model: { name: string; version: string };
  processing_ms: number | null;
  stored: boolean;
};

export type ModelInfo = {
  name: string;
  task: string;
  version: string;
  status: "ready" | "missing" | "checksum_mismatch" | "load_error" | string;
  detail: string | null;
  license: string;
  license_url: string;
  source: string;
  sha256: string | null;
  notes: string;
  runtime: string;
};

export type ModelsResponse = {
  inference: { reachable: boolean; ready?: boolean; detail?: string };
  models: ModelInfo[];
};

// --- face events, gallery, recognition (ADR-0004) ---------------------------------

export type Outcome = "AUTHORIZED" | "UNRECOGNIZED" | "INCONCLUSIVE" | "NOT_MATCHED" | "SYSTEM_ERROR";
export const OUTCOMES: Outcome[] = ["AUTHORIZED", "UNRECOGNIZED", "INCONCLUSIVE", "SYSTEM_ERROR", "NOT_MATCHED"];

export type FaceEventStatus =
  | "faces_detected"
  | "no_faces_detected"
  | "frame_unavailable"
  | "frame_rejected"
  | "inference_failed"
  | "gave_up";
export const FACE_EVENT_STATUSES: FaceEventStatus[] = [
  "faces_detected", "no_faces_detected", "frame_unavailable", "frame_rejected", "inference_failed", "gave_up",
];

export type OutcomeReason =
  | "match"
  | "below_reject_threshold"
  | "gallery_empty"
  | "between_thresholds"
  | "several_people_match"
  | "insufficient_quality"
  | "recognition_error"
  | "recognition_off"
  | "recognition_unavailable"
  | "not_performed";

export type FaceRecognition = {
  outcome: Outcome;
  reason: OutcomeReason;
  person: { id: string; display_name: string | null } | null;
  similarity: number | null;
  thresholds: { accept: number | null; reject: number | null } | null;
};

export type FaceDetectionItem = {
  id: string;
  position: number;
  box: Box;
  score: number;
  keypoints5: [number, number][];
  quality: Partial<FaceQuality>;
  crop_url: string | null;
  recognition: FaceRecognition | null; // null: stored before recognition existed
  attributes?: Record<string, Estimate>; // fallible estimates, display only
  liveness?: Liveness;
};

export type FaceEvent = {
  id: string;
  frigate_event_id: string;
  camera: string;
  started_at: string;
  ended_at: string;
  status: FaceEventStatus;
  face_count: number;
  frame_source: "recording" | "snapshot" | null;
  frame: { width: number; height: number } | null;
  frame_url: string | null;
  detector: string | null;
  detail: string | null;
  recognition_state: "off" | "unavailable" | "done" | null;
  recognizer: string | null;
  detections: FaceDetectionItem[];
};

export type FaceEventFilters = {
  camera?: string;
  status?: string;
  outcome?: string;
  person_id?: string;
  has_faces?: "true" | "false";
  since?: string; // ISO 8601
  until?: string;
};

export type Page<T> = { items: T[]; next_cursor: string | null };

export type ReferenceFace = {
  id: string;
  image: { width: number; height: number; media_type: string };
  image_url: string;
  box: Box;
  score: number;
  keypoints5: [number, number][];
  quality: Partial<FaceQuality>;
  detector: string | null;
  embedded: boolean;
  embedder: string | null;
  created_by: string;
  created_at: string;
};

export type Person = {
  id: string;
  display_name: string;
  notes: string | null;
  consent: { date: string; note: string };
  active: boolean;
  face_count: number;
  created_by: string;
  created_at: string;
  updated_at: string;
  faces?: ReferenceFace[];
};

export type PersonInput = {
  display_name: string;
  consent_date: string; // YYYY-MM-DD
  consent_note: string;
  notes?: string | null;
};

export type PersonUpdate = Partial<PersonInput & { active: boolean }>;

export type RecognitionStatus = {
  enabled: boolean;
  updated_at: string | null;
  updated_by: string | null;
  embedder: { ready: boolean; model: string | null; status: string };
  // people / reference_faces / pending are null while the embedder is unavailable (counts_known false):
  // which embeddings are usable depends on the model the embedder reports.
  gallery: {
    counts_known: boolean;
    total_reference_faces: number;
    people: number | null;
    reference_faces: number | null;
    pending: number | null;
    unreadable: number | null;
  };
  thresholds: { accept: number; reject: number; min_face_px: number };
};

export type AuditEntry = {
  id: string;
  at: string;
  username: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: string | null;
};

// --- accounts, gate, alarm, footage, privacy --------------------------------------------

export type Role = "viewer" | "operator" | "admin";
export const ROLE_ORDER: Role[] = ["viewer", "operator", "admin"];
// The server enforces roles; the UI only hides what a role cannot use.
export const atLeast = (role: Role | undefined, required: Role) =>
  ROLE_ORDER.indexOf(role ?? "viewer") >= ROLE_ORDER.indexOf(required);

export type Me = { username: string; role?: Role };

export type UserAccount = {
  id: string;
  username: string;
  role: Role;
  disabled: boolean;
  created_at: string;
  password_changed_at: string | null;
};

export type Point = { x: number; y: number }; // fractions of the frame, 0..1

export type GateLine = {
  id: string;
  camera: string;
  name: string;
  p1: Point;
  p2: Point;
  in_side: "left" | "right";
  record_exits: boolean;
  enabled: boolean;
  alarm_on_unauthorized: boolean;
  cooldown_seconds: number;
  updated_by: string;
  updated_at: string;
};

export type GateLineInput = {
  name: string;
  x1: number; y1: number; x2: number; y2: number;
  in_side: "left" | "right";
  record_exits: boolean;
  enabled: boolean;
  alarm_on_unauthorized: boolean;
  cooldown_seconds: number;
  password: string;
};

export type GateStatus = {
  tracking: boolean;
  mqtt: { enabled: boolean; connected: boolean; last_message_at?: string | null; last_error?: string | null };
  note: string | null;
};

export type Verdict = "pending" | "AUTHORIZED" | "UNAUTHORIZED" | "NEEDS_REVIEW" | "NOT_CHECKED";

export type GateCrossing = {
  id: string;
  line_id: string;
  camera: string;
  frigate_event_id: string;
  sequence: number;
  direction: "in" | "out";
  crossed_at: string;
  point: Point;
  verdict: Verdict;
  reason: string | null;
  checked_at: string | null;
  // operators and administrators only
  outcome?: Outcome | null;
  similarity?: number | null;
  person?: { id: string; display_name: string | null } | null;
  face_event_id?: string | null;
};

export type Alert = {
  id: string;
  created_at: string;
  kind: "unauthorized_entry" | "needs_review" | "alarm_test";
  camera: string | null;
  crossing_id: string | null;
  detail: string | null;
  status: "open" | "acknowledged";
  alarm: "none" | "simulated" | "activated" | "failed" | "silenced" | "cooldown" | "disabled";
  delivery: string | null;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
};

export type AlarmStatus = {
  output: "simulation" | "http_relay" | "none";
  physical: boolean;
  configured: boolean;
  problem: string | null;
  duration_seconds: number;
  cooldown_seconds: number;
  max_silence_minutes: number;
  webhook: boolean;
  last_error: string | null;
  silenced_until: string | null;
  open_alerts: number;
};

export type Estimate = { state: "estimated" | "unknown"; value: string | null; confidence: number | null; reason?: string };
export type Liveness = { state: "checked" | "unavailable"; label?: string | null; score?: number | null; note: string };

export type Capabilities = {
  inference_reachable: boolean;
  attributes: { installed: boolean; status: string; model: string | null; names: string[]; note: string };
  liveness: { installed: boolean; status: string; model: string | null; note: string };
};

export type PrivacyOverview = {
  retention_days: Record<string, number>;
  counts: Record<string, number>;
  encryption: { biometric_data: string; key_source: string; not_encrypted: string };
  recognition_enabled: boolean;
};

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string, public reasons?: string[]) {
    super(message);
  }
}

function query(params: Record<string, string | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  const s = q.toString();
  return s ? `?${s}` : "";
}

// Central handling of expired or invalid sessions. Any 401 from a protected
// endpoint calls the registered handler (the app returns to the login
// screen). Only 401 does this: 403, 5xx and network errors leave the
// session alone. The auth endpoints are exempt: a wrong password at login,
// the "not signed in yet" check and logout are not session expiry.
export const NETWORK_ERROR = "The server could not be reached. Check your connection.";
export const API_DOWN = "The server is not responding (it may be restarting). Try again in a minute.";

const AUTH_EXEMPT = new Set(["/api/auth/login", "/api/auth/me", "/api/auth/logout"]);
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  // FormData sets its own multipart Content-Type (with boundary); JSON otherwise.
  const defaults: Record<string, string> = init.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  let resp: Response;
  try {
    resp = await fetch(path, {
      credentials: "same-origin",
      ...init,
      headers: { ...defaults, ...((init.headers as Record<string, string>) ?? {}) },
    });
  } catch {
    // fetch rejects only when no answer arrived (offline, server down, DNS); the browser's own
    // message ("Failed to fetch") means nothing to an operator.
    throw new ApiError(0, NETWORK_ERROR, "network");
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    let code: string | undefined;
    let reasons: string[] | undefined;
    let fromApi = false; // the api always answers errors with a JSON body; the proxy does not
    try {
      const body = await resp.json();
      fromApi = true;
      if (typeof body.error === "string") code = body.error;
      if (Array.isArray(body.reasons)) reasons = body.reasons.map(String);
      if (typeof body.detail === "string") detail = body.detail;
      // FastAPI validation errors: [{loc: [..., "field"], msg: "..."}]
      else if (Array.isArray(body.detail))
        detail = body.detail
          .map((e: { loc?: unknown[]; msg?: string }) => {
            const field = e.loc && e.loc.length > 1 ? String(e.loc[e.loc.length - 1]) : "";
            const msg = (e.msg ?? "invalid").replace(/^Value error, /, "");
            return field && field !== "body" ? `${field}: ${msg}` : msg;
          })
          .join("; ");
    } catch {
      // non-JSON error body
    }
    if (resp.status === 401 && !AUTH_EXEMPT.has(path.split("?")[0])) onUnauthorized?.();
    // Caddy answers 502/503/504 itself when the api is down or restarting.
    if (!fromApi && resp.status >= 502 && resp.status <= 504) throw new ApiError(resp.status, API_DOWN, "api_down");
    throw new ApiError(resp.status, detail || `HTTP ${resp.status}`, code, reasons);
  }
  return resp.status === 204 ? (undefined as T) : ((await resp.json()) as T);
}

const cam = (name: string) => `/api/cameras/${encodeURIComponent(name)}`;
const person = (id: string) => `/api/people/${encodeURIComponent(id)}`;
const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/api/health"),
  me: () => request<Me>("/api/auth/me"),
  login: (username: string, password: string) =>
    request<Me>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("/api/auth/password", json("POST", { current_password, new_password })),
  users: () => request<{ items: UserAccount[]; roles: Role[] }>("/api/users"),
  createUser: (username: string, role: Role, new_password: string, password: string) =>
    request<UserAccount>("/api/users", json("POST", { username, role, new_password, password })),
  updateUser: (id: string, change: { role?: Role; disabled?: boolean }, password: string) =>
    request<UserAccount>(`/api/users/${encodeURIComponent(id)}`, json("PATCH", { ...change, password })),
  resetUserPassword: (id: string, new_password: string, password: string) =>
    request<void>(`/api/users/${encodeURIComponent(id)}/password`, json("POST", { new_password, password })),
  deleteUser: (id: string, password: string) =>
    request<void>(`/api/users/${encodeURIComponent(id)}`, json("DELETE", { password })),
  gateLines: () => request<{ items: GateLine[]; status: GateStatus }>("/api/gate/lines"),
  saveGateLine: (camera: string, input: GateLineInput) =>
    request<GateLine>(`/api/gate/lines/${encodeURIComponent(camera)}`, json("PUT", input)),
  deleteGateLine: (id: string, password: string) =>
    request<void>(`/api/gate/lines/${encodeURIComponent(id)}`, json("DELETE", { password })),
  crossings: (params: { camera?: string; verdict?: string; before?: string } = {}, limit = 50) =>
    request<{ items: GateCrossing[] }>(`/api/gate/crossings${query({ ...params, limit: String(limit) })}`),
  alerts: (status?: "open" | "acknowledged") => request<{ items: Alert[] }>(`/api/alerts${query({ status })}`),
  acknowledgeAlert: (id: string) => request<Alert>(`/api/alerts/${encodeURIComponent(id)}/acknowledge`, { method: "POST" }),
  alarm: () => request<AlarmStatus>("/api/alarm"),
  silenceAlarm: (minutes: number) => request<AlarmStatus>("/api/alarm/silence", json("POST", { minutes })),
  unsilenceAlarm: () => request<AlarmStatus>("/api/alarm/silence", { method: "DELETE" }),
  testAlarm: (password: string) =>
    request<{ alert: Alert | null; alarm: AlarmStatus }>("/api/alarm/test", json("POST", { password })),
  // Starts (or returns) the export of the recording around the event; poll capture(id) until ready.
  footage: (kind: "face-events" | "crossings", id: string) =>
    request<Capture>(`/api/footage/${kind}/${encodeURIComponent(id)}`, { method: "POST" }),
  capture: (id: string) => request<Capture>(`/api/captures/${encodeURIComponent(id)}`),
  capabilities: () => request<Capabilities>("/api/capabilities"),
  privacy: () => request<PrivacyOverview>("/api/privacy"),
  runRetention: (password: string) =>
    request<{ deleted: Record<string, number> }>("/api/privacy/retention/run", json("POST", { password })),
  purgeEmbeddings: (password: string) =>
    request<{ deleted_embeddings: number; recognition_switched_off: boolean }>(
      "/api/privacy/embeddings/purge", json("POST", { password })),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  cameras: () => request<Camera[]>("/api/cameras"),
  snapshot: (camera: string) => request<Capture>(`${cam(camera)}/snapshot`, { method: "POST" }),
  clip: (camera: string, seconds: number) =>
    request<Capture>(`${cam(camera)}/clip`, { method: "POST", body: JSON.stringify({ seconds }) }),
  captures: () => request<Capture[]>("/api/captures"),
  deleteCapture: (id: string) => request<void>(`/api/captures/${encodeURIComponent(id)}`, { method: "DELETE" }),
  devices: () => request<Device[]>("/api/devices"),
  createDevice: (input: DeviceInput) =>
    request<Device>("/api/devices", { method: "POST", body: JSON.stringify(input) }),
  updateDevice: (id: string, input: DeviceInput) =>
    request<Device>(`/api/devices/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(input) }),
  deleteDevice: (id: string) => request<void>(`/api/devices/${encodeURIComponent(id)}`, { method: "DELETE" }),
  testDevice: (id: string) => request<Device>(`/api/devices/${encodeURIComponent(id)}/test`, { method: "POST" }),
  setUseInFrigate: (id: string, useInFrigate: boolean) =>
    request<Device>(`/api/devices/${encodeURIComponent(id)}/frigate`, {
      method: "PUT",
      body: JSON.stringify({ use_in_frigate: useInFrigate }),
    }),
  addSynthetic: () => request<Device>("/api/devices/synthetic", { method: "POST" }),
  applyToFrigate: () => request<FrigateApplyResult>("/api/frigate/apply", { method: "POST" }),
  models: () => request<ModelsResponse>("/api/models"),
  // Multipart upload, field "file". The server ignores the file name and checks the bytes.
  analyseFaces: (file: File, minScore?: number) => {
    const form = new FormData();
    form.append("file", file);
    return request<FaceAnalysis>(`/api/analysis/faces${minScore !== undefined ? `?min_score=${minScore}` : ""}`, {
      method: "POST",
      body: form,
    });
  },
  faceEvents: (filters: FaceEventFilters, cursor?: string | null, limit = 25) =>
    request<Page<FaceEvent>>(`/api/face-events${query({ ...filters, cursor: cursor ?? undefined, limit: String(limit) })}`),
  deleteFaceEvent: (id: string) => request<void>(`/api/face-events/${encodeURIComponent(id)}`, { method: "DELETE" }),
  people: () => request<{ items: Person[] }>("/api/people"),
  person: (id: string) => request<Person>(person(id)),
  createPerson: (input: PersonInput) => request<Person>("/api/people", json("POST", input)),
  updatePerson: (id: string, update: PersonUpdate) => request<Person>(person(id), json("PATCH", update)),
  // Needs the signed-in user's password again.
  deletePerson: (id: string, password: string) => request<void>(person(id), json("DELETE", { password })),
  enrollFace: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ReferenceFace>(`${person(id)}/faces`, { method: "POST", body: form });
  },
  deleteReferenceFace: (id: string, faceId: string) =>
    request<void>(`${person(id)}/faces/${encodeURIComponent(faceId)}`, { method: "DELETE" }),
  recognition: () => request<RecognitionStatus>("/api/recognition"),
  setRecognition: (enabled: boolean, password: string) =>
    request<RecognitionStatus>("/api/recognition", json("PUT", { enabled, password })),
  auditLog: (cursor?: string | null, limit = 20) =>
    request<Page<AuditEntry>>(`/api/audit-log${query({ cursor: cursor ?? undefined, limit: String(limit) })}`),
  latestFrameUrl: (camera: string) => `${cam(camera)}/latest.jpg?t=${Date.now()}`,
  liveSocketUrl: (camera: string) => {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${window.location.host}${cam(camera)}/live`;
  },
};
