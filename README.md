# Fingerprint Analyzer — Prototype

Minimal React + HTML/CSS frontend with a Python/FastAPI backend.

## What is implemented

- Up to 30 fingerprint uploads.
- 10-finger result dashboard.
- 30-upload convention: three captures per finger in upload order; the highest-confidence successful result is selected for each finger.
- Core and delta candidate detection.
- When multiple deltas are detected, the farthest from the core is selected.
- Enhancement is applied before detection; low-confidence results are flagged as retry/uncertain.
- Prototype ridge-count estimate from the core-to-delta ridge line.
- Pattern family output: Arch, Loop, Whorl; Accidental is reserved for irregular/mixed patterns in later validation.
- TRC is the sum of the ten selected RC values, matching the workbook's ten-finger TRC structure.
- Demo mode with synthetic fingerprint images and sample values so development can continue without real fingerprint files.

## Run backend

```bash
cd backend
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS/Linux
# source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Run frontend

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal, normally `http://localhost:5173`.

## Important prototype limitation

The supplied fingerprint material defines the conceptual rules: delta/core, pattern family by delta count, and ridge count as the number of ridge lines between delta and centre. The automated image detector here is a first-pass computer-vision heuristic, not a validated biometric/forensic algorithm. It should be tested against labeled fingerprint examples before real scoring or production use.

## Workbook compatibility

The supplied workbook uses ten pattern/RC inputs (L1–L5 and R1–R5) and calculates total TRC as the sum of those ten RC cells. This prototype mirrors that structure in its result payload.
