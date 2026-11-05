import { Verdict } from "../../api";

export const VERDICT_LABEL: Record<Verdict, string> = {
  pending: "Checking…",
  AUTHORIZED: "Automated match: authorized",
  UNAUTHORIZED: "Not matched to an authorized person",
  NEEDS_REVIEW: "Needs review",
  NOT_CHECKED: "Not checked",
};

export const VERDICT_CLASS: Record<Verdict, string> = {
  pending: "status-neutral",
  AUTHORIZED: "status-ok",
  UNAUTHORIZED: "status-bad",
  NEEDS_REVIEW: "status-warn",
  NOT_CHECKED: "status-neutral",
};

export const GATE_REASON: Record<string, string> = {
  exit: "exit (exits are recorded, not checked)",
  recognition_off: "recognition is switched off",
  recognition_unavailable: "recognition was unavailable",
  check_failed: "the check could not run (Frigate or the AI service did not answer)",
  no_face: "no face was visible",
  no_face_on_person: "no face inside the person's box",
  several_faces: "several faces: cannot tell which one crossed",
  face_too_small: "the face was too small to compare",
  face_touches_edge: "the face was cut off at the frame edge",
  match: "matched an authorized person",
  below_reject_threshold: "clear face, below the reject threshold",
  gallery_empty: "nobody is enrolled to compare with",
  between_thresholds: "similarity between the thresholds",
  several_people_match: "looks like more than one enrolled person",
  insufficient_quality: "face quality too low",
  recognition_error: "the face could not be analysed",
};

export const ALARM_LABEL: Record<string, string> = {
  none: "no alarm",
  simulated: "alarm simulated (nothing switched)",
  activated: "alarm output activated",
  failed: "alarm output FAILED",
  silenced: "alarm silenced",
  cooldown: "alarm in cooldown",
  disabled: "alarm output disabled",
};

export const ATTRIBUTE_LABEL: Record<string, string> = {
  age_range: "Age range",
  gender_presentation: "Gender presentation",
  expression: "Expression",
  glasses: "Glasses",
  beard: "Beard",
  mask: "Face mask",
};
