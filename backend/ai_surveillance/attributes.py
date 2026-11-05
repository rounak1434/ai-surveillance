"""Facial attribute estimates and presentation-attack (liveness) checks: contract and status.

No model for either is bundled. Models that were considered either have licences that do not
allow this use (e.g. InsightFace's pretrained weights: non-commercial research only) or have not
been evaluated on this camera, and an unevaluated anti-spoofing model would give false
assurance. The system therefore reports every estimate as "unknown" and liveness as
"unavailable", and says so in the API and the UI.

Contract for a future model (in the inference service, behind its adapter registry): each face in
a /v1/embed or /v1/detect response may carry
  "attributes": {"<name>": {"value": "<label>", "confidence": 0..1}, ...}   names: ATTRIBUTES
  "liveness":   {"label": "live" | "spoof" | "uncertain", "score": 0..1, "model": "<name version>"}
and /v1/models lists the model with task "face_attributes" or "presentation_attack_detection".
Values are validated here and stored per face (face_detections.attributes / .liveness).

Estimates are fallible model guesses about appearance. They are shown to operators only, marked
as estimates, and are never read by recognition, gate verdicts or the alarm.
"""

import json
import math

from .inference_client import InferenceClient, InferenceUnavailable

ATTRIBUTES = ("age_range", "gender_presentation", "expression", "glasses", "beard", "mask")
ATTRIBUTE_TASK = "face_attributes"
LIVENESS_TASK = "presentation_attack_detection"
LIVENESS_LABELS = frozenset({"live", "spoof", "uncertain"})


def _confidence(value) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1:
        return round(float(value), 4)
    return None


def sanitize_attributes(value) -> str | None:
    """JSON to store, from an inference face's `attributes`; None when nothing usable."""
    if not isinstance(value, dict):
        return None
    clean = {}
    for name in ATTRIBUTES:
        item = value.get(name)
        if isinstance(item, dict) and isinstance(item.get("value"), str) and item["value"].strip():
            confidence = _confidence(item.get("confidence"))
            if confidence is not None:
                clean[name] = {"value": item["value"].strip()[:32], "confidence": confidence}
    return json.dumps(clean) if clean else None


def sanitize_liveness(value) -> str | None:
    if not isinstance(value, dict) or value.get("label") not in LIVENESS_LABELS:
        return None
    score = _confidence(value.get("score"))
    if score is None:
        return None
    model = value.get("model") if isinstance(value.get("model"), str) else None
    return json.dumps({"label": value["label"], "score": score, "model": model[:64] if model else None})


def present_attributes(stored: str | None) -> dict:
    """Every attribute, with state "estimated" (value + confidence) or "unknown"."""
    try:
        values = json.loads(stored) if stored else {}
    except ValueError:
        values = {}
    out = {}
    for name in ATTRIBUTES:
        item = values.get(name) if isinstance(values, dict) else None
        if isinstance(item, dict):
            out[name] = {"state": "estimated", "value": item.get("value"), "confidence": item.get("confidence")}
        else:
            out[name] = {"state": "unknown", "value": None, "confidence": None,
                         "reason": "no_model" if not stored else "not_estimated"}
    return out


def present_liveness(stored: str | None) -> dict:
    try:
        value = json.loads(stored) if stored else None
    except ValueError:
        value = None
    if not isinstance(value, dict):
        return {"state": "unavailable", "label": None, "score": None,
                "note": "No presentation-attack check ran: a photo or screen showing an enrolled face can match."}
    return {"state": "checked", **value,
            "note": "A model estimate; not proof that a live person was present."}


async def capabilities(inference: InferenceClient) -> dict:
    try:
        models = await inference.models()
        reachable = True
    except InferenceUnavailable:
        models, reachable = [], False

    def find(task: str):
        for m in models if isinstance(models, list) else []:
            if isinstance(m, dict) and m.get("task") == task:
                return {"installed": True, "status": m.get("status"), "model": f"{m.get('name')} {m.get('version')}"}
        return {"installed": False, "status": "not_installed" if reachable else "unknown", "model": None}

    return {
        "inference_reachable": reachable,
        "attributes": {**find(ATTRIBUTE_TASK), "names": list(ATTRIBUTES),
                       "note": "Estimates are fallible model guesses about appearance, shown for information only; "
                               "they never decide authorization and never trigger an alarm."},
        "liveness": {**find(LIVENESS_TASK),
                     "note": "Without a presentation-attack model the system cannot detect photos, screens or masks "
                             "of an enrolled person. Even with one, results are estimates."},
    }
