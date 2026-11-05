# ADR-0005: No facial-attribute model is installed

- Status: **accepted**, owner's decision 2026-11-05: keep every attribute estimate as "unknown".
- Date: 2026-11-05, base commit `0acc529`

## Context
The face pipeline has a slot for optional appearance estimates (age range, gender presentation, glasses, beard, face mask, expression), see `backend/ai_surveillance/attributes.py`. Without a model each estimate is stored and shown as "unknown". Estimates are never used to authorize anyone, to mark anyone unauthorized, or to trigger an alarm.

A model may only be added when the licence of both the architecture and the trained weights clearly permits an operational, non-research deployment. Permissive code or weight licences are not enough when the training data is restricted to research or non-commercial use.

## Review (2026-11-05)
| Candidate | Covers | Weights licence | Training data | Verdict |
|---|---|---|---|---|
| OpenCV Zoo `facial_expression_recognition_mobilefacenet_2022july` | expression | Apache-2.0 ([opencv_zoo](https://github.com/opencv/opencv_zoo/tree/main/models/facial_expression_recognition)) | Not named on the model page; the paper uses RAF-DB ([arXiv 2205.14361](https://arxiv.org/pdf/2205.14361)), listed as non-commercial by a third-party catalogue ([hyper.ai](https://hyper.ai/en/datasets/17961)); the official page was unreachable | Unclear |
| InsightFace `buffalo_l` gender/age | age, gender | Non-commercial research only ([model zoo](https://github.com/deepinsight/insightface/blob/e68b8b076fb11e9f75c87244d234385f0f318181/model_zoo/README.md)) | — | Incompatible |
| FairFace | age bins, gender | Not stated for the weights; no LICENSE file; weights on Google Drive ([repo](https://github.com/dchen236/FairFace)) | CC BY 4.0, stated for the data | Unclear |
| Age/gender ONNX files (ONNX Model Zoo, Hugging Face, `yu4u/age-gender-estimation`) | age, gender | Apache-2.0 or MIT | IMDB-WIKI "academic research purpose only" ([ETH](https://data.vision.ee.ethz.ch/cvl/rrothe/imdb-wiki/)); UTKFace "non-commercial research purposes only" ([UTKFace](https://susanqq.github.io/UTKFace/)) | Incompatible |
| Glasses and beard classifiers | glasses, beard | Mostly not stated | CelebA "non-commercial research purposes only" ([CelebA](https://mmlab.ie.cuhk.edu.hk/projects/CelebA.html)) | Incompatible |
| AIZOOTech FaceMaskDetection | face mask | Code MIT; ONNX files are community conversions of uncertain origin | WIDER Face and MAFA; terms not confirmed | Unclear |

Nothing was downloaded or integrated.

## Decision
No attribute model is installed. `/v1/models` reports no `face_attributes` model, and the UI keeps showing "unknown (no estimation model installed)".

## Options for a later revisit
1. Written confirmation from the FairFace authors that the released weights are CC BY 4.0 (age range and gender presentation only, no race output).
2. Train SAIL's own models on clearly licensed data (for example FairFace images, synthetic masks, consented and locally labelled site footage).
3. A commercial on-premise model with written terms covering SAIL's use.

Any of these needs a licence check recorded here, a pinned SHA-256 in `inference/inference_service/registry.py`, and accuracy measured on representative site footage before it is enabled.
