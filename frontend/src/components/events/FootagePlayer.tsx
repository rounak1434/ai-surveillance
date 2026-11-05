import { useEffect, useState } from "react";
import { api, ApiError, Capture } from "../../api";

const POLL_MS = 2000;

// Opens the recording around a face event or gate crossing. The server exports it from Frigate
// (a few seconds to a minute) and serves it behind sign-in; this only polls and plays.
export function FootagePlayer({ kind, id, title, onClose }: {
  kind: "face-events" | "crossings";
  id: string;
  title: string;
  onClose: () => void;
}) {
  const [capture, setCapture] = useState<Capture | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async (current: Capture) => {
      if (stopped) return;
      setCapture(current);
      if (current.status !== "pending") return;
      timer = setTimeout(async () => {
        try {
          await poll(await api.capture(current.id));
        } catch (err) {
          if (!stopped) setError((err as Error).message);
        }
      }, POLL_MS);
    };
    api.footage(kind, id).then(poll).catch((err) => {
      if (stopped) return;
      if (err instanceof ApiError && err.status === 410) setError(err.message);
      else if (err instanceof ApiError && err.status === 403) setError("Your role cannot open footage.");
      else setError((err as Error).message);
    });
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [kind, id]);

  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label="Event footage" onClick={onClose}>
      <div className="modal-body dialog footage" onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>
        {error && <p className="error" role="alert">Footage unavailable: {error}</p>}
        {!error && (!capture || capture.status === "pending") && (
          <p className="muted" role="status">Preparing the clip from the recording… this can take up to a minute.</p>
        )}
        {capture?.status === "failed" && (
          <p className="error" role="alert">Footage unavailable: {capture.error ?? "the export failed"}</p>
        )}
        {capture?.status === "ready" && capture.file_url && (
          <video src={capture.file_url} controls autoPlay playsInline data-testid="footage-video" />
        )}
        <p className="muted small">The clip is kept with the captures and follows their retention.</p>
        <div className="actions">
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
