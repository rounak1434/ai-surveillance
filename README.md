# SAIL AI Surveillance

A locally hosted camera-monitoring and face-verification system for the SAIL gate project. It runs on Ubuntu with Docker Compose. Frigate handles camera streams, person tracking and recordings; the SAIL console is a local web application. The Ubuntu desktop shortcut opens that console in a browser.

> **Readiness:** gate monitoring, roles, event footage and alarm controls are present in code. New and adjusted automated tests have not been run. The Docker stack, Frigate/MQTT integration, real camera and physical relay or siren have not been verified on the target PC. See [Release Readiness](docs/RELEASE-READINESS.md) and [Verification](docs/VERIFICATION.md).

## Features

- Live camera view, snapshots and clip capture through Frigate.
- Face-event history and an authorized-person gallery. Enrollment uses consent records; reference images and face embeddings are encrypted at rest.
- Face recognition is **off by default**. A match is a model result, not proof of identity; thresholds need evaluation with the actual camera.
- Administrator-configured virtual gate lines with directional person-crossing records, using Frigate tracking data over MQTT.
- Event alerts and configurable alarm output. The default is **simulation**; a LAN HTTP relay must be explicitly configured.
- Event footage linked to face and gate records.
- Viewer, operator and administrator roles, password changes, audited access and configurable retention.
- Ubuntu service and desktop-shortcut scripts for local access and start-on-boot.

## Important limitations

- No face-attribute model is installed. Age range, gender presentation, expression, glasses, beard and face-mask estimates currently show as unknown.
- No liveness or anti-spoofing model is installed. The system cannot currently distinguish a live person from a photo or screen.
- A clear, good-quality face that does not match a non-empty authorized gallery can be marked unauthorized. No face, poor quality, an empty gallery, or uncertain/unavailable recognition is sent for review and does **not** trigger the alarm.
- MQTT update frequency, gate-crossing accuracy, clip export, relay behavior and reboot recovery still need verification on the real system.

## Quick start on Ubuntu

Use Ubuntu 22.04 or 24.04 (64-bit) with Docker Engine and the Compose plugin. Follow [Setup on Ubuntu](docs/SETUP.md) for prerequisites and the full procedure. The included synthetic RTSP source can be used before connecting a camera.

```bash
git clone https://github.com/rounak1434/ai-surveillance.git ~/ai-surveillance
cd ~/ai-surveillance/deploy
cp .env.example .env
chmod 600 .env
sed -i "s/^INFERENCE_API_TOKEN=.*/INFERENCE_API_TOKEN=$(openssl rand -hex 32)/" .env
docker compose up -d --build
docker compose ps
docker compose exec api ai-surveillance create-admin admin
bash doctor.sh
```

Then open `https://localhost/` on the Ubuntu PC and sign in with the administrator account you created. The setup and operations guides cover camera connection, Frigate configuration, the desktop shortcut, and automatic startup.

Keep the alarm in simulation while commissioning. Do not rely on automatic recognition or connect a physical relay until the camera, recognition thresholds, MQTT events, gate behavior and alarm have been checked in the intended environment.

## Documentation

- [Ubuntu setup](docs/SETUP.md)
- [Camera and NVR setup](docs/CAMERA-SETUP.md)
- [Gate lines and MQTT events](docs/GATE.md)
- [Alerts and alarm output](docs/ALARM.md)
- [Privacy, roles and retention](docs/PRIVACY.md)
- [Ubuntu operations and startup](docs/OPERATIONS.md)
- [Acceptance checklist](docs/ACCEPTANCE-CHECKLIST.md)
- [Release readiness](docs/RELEASE-READINESS.md)

The system is designed to keep processing and stored evidence on the local host. An optional webhook sends alert metadata to a configured LAN service. The operator is responsible for consent, access control, retention, and compliance with applicable rules before using biometric features.
