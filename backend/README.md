# Fingerprint Analyzer Backend

FastAPI prototype for the fingerprint-analysis UI.

## Run

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The API accepts up to 30 JPG/PNG-style image uploads at `POST /api/analyze`.

### Prototype detection

The current implementation uses OpenCV/scikit-image heuristics:

- CLAHE + normalization for enhancement
- ridge orientation estimation
- Poincare-style singularity candidates
- core/delta candidate selection
- farthest delta selection when multiple deltas exist
- core-to-delta ridge-line sampling for a prototype ridge count
- confidence/status reporting

This is intentionally a prototype. It must be validated against labeled fingerprints before being used for forensic, biometric, medical, legal, or production scoring decisions.
