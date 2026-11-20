from __future__ import annotations

import io
import math
from typing import List

import cv2
import numpy as np
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Fingerprint Analyzer API", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FINGERS = [
    "L1 - Thumb", "L2 - Index", "L3 - Middle", "L4 - Ring", "L5 - Little",
    "R1 - Thumb", "R2 - Index", "R3 - Middle", "R4 - Ring", "R5 - Little",
]


def decode_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("Unable to decode image")
    return img


def enhance(gray: np.ndarray) -> np.ndarray:
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    out = clahe.apply(gray)
    return cv2.GaussianBlur(out, (3, 3), 0)


def extract_fingerprint_mask(gray: np.ndarray, block_size: int = 16) -> np.ndarray:
    """
    Computes a binary foreground mask of the actual friction ridge pattern,
    completely eliminating black borders and unprinted white zones.
    """
    h, w = gray.shape
    # Local variance filter
    mean = cv2.blur(gray.astype(np.float32), (block_size, block_size))
    sq_mean = cv2.blur((gray.astype(np.float32)) ** 2, (block_size, block_size))
    variance = sq_mean - (mean ** 2)
    variance = np.clip(variance, 0, None)
    std = np.sqrt(variance)

    thresh = np.percentile(std, 30)
    thresh = max(10.0, float(thresh))
    mask = (std > thresh).astype(np.uint8) * 255

    # Morphological clean up: erode to stay strictly away from the border edge
    kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    kernel_erode = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(block_size * 1.5), int(block_size * 1.5)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_small)
    mask = cv2.erode(mask, kernel_erode)
    return mask


def orientation_field(gray: np.ndarray, block: int = 12):
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    h, w = gray.shape
    hh, ww = h // block, w // block

    Gxx = np.zeros((hh, ww), dtype=np.float64)
    Gyy = np.zeros((hh, ww), dtype=np.float64)
    Gxy = np.zeros((hh, ww), dtype=np.float64)
    energy = np.zeros((hh, ww), dtype=np.float64)

    for y in range(hh):
        ys = slice(y * block, (y + 1) * block)
        for x in range(ww):
            xs = slice(x * block, (x + 1) * block)
            bx = gx[ys, xs]
            by = gy[ys, xs]
            Gxx[y, x] = np.sum(bx * bx)
            Gyy[y, x] = np.sum(by * by)
            Gxy[y, x] = np.sum(bx * by)
            energy[y, x] = np.mean(bx * bx + by * by)

    sin2 = cv2.GaussianBlur(2.0 * Gxy, (7, 7), 2.0)
    cos2 = cv2.GaussianBlur(Gxx - Gyy, (7, 7), 2.0)

    theta = 0.5 * np.arctan2(sin2, cos2) + (np.pi / 2.0)
    coherence = np.sqrt(sin2 * sin2 + cos2 * cos2) / (Gxx + Gyy + 1e-6)
    return theta, energy, coherence, block


def wrapped_delta(a: float, b: float) -> float:
    d = a - b
    while d > math.pi / 2.0:
        d -= math.pi
    while d < -math.pi / 2.0:
        d += math.pi
    return d


def find_singularities(theta: np.ndarray, mask_block: np.ndarray, energy: np.ndarray, coherence: np.ndarray):
    """
    Computes Poincare index ONLY on valid interior friction ridge blocks.
    """
    hh, ww = theta.shape
    candidates = []

    for y in range(2, hh - 2):
        for x in range(2, ww - 2):
            # Check 3x3 neighbourhood is 100% inside fingerprint mask
            if not np.all(mask_block[y - 1:y + 2, x - 1:x + 2]):
                continue
            if coherence[y, x] < 0.20:
                continue

            # 8-connected loop
            angles = [
                theta[y - 1, x - 1], theta[y - 1, x], theta[y - 1, x + 1],
                theta[y, x + 1], theta[y + 1, x + 1], theta[y + 1, x],
                theta[y + 1, x - 1], theta[y, x - 1]
            ]
            total_delta = sum(wrapped_delta(angles[(i + 1) % 8], angles[i]) for i in range(8))
            poincare_val = total_delta / math.pi

            if abs(poincare_val) >= 0.35:
                is_core = poincare_val > 0
                quality = 1.0 - min(abs(abs(poincare_val) - 0.5), abs(abs(poincare_val) - 1.0))
                candidates.append((x, y, is_core, quality, float(energy[y, x]), float(coherence[y, x])))

    return candidates


def dedupe_singularities(points, min_dist=3):
    points = sorted(points, key=lambda p: p[3] * p[4], reverse=True)
    out = []
    for p in points:
        if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= min_dist ** 2 for q in out):
            out.append(p)
    return out


def local_ridge_count(gray: np.ndarray, core, delta) -> int:
    x1, y1 = core
    x2, y2 = delta
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist < 8:
        return 0

    num_samples = max(40, int(dist * 2.5))
    xs = np.linspace(x1, x2, num_samples)
    ys = np.linspace(y1, y2, num_samples)
    h, w = gray.shape
    xi = np.clip(np.rint(xs).astype(int), 0, w - 1)
    yi = np.clip(np.rint(ys).astype(int), 0, h - 1)

    vals = gray[yi, xi].astype(np.float32)
    vals = cv2.GaussianBlur(vals.reshape(1, -1), (1, 5), 0).reshape(-1)

    trim = max(3, int(num_samples * 0.08))
    if len(vals) > 2 * trim:
        vals = vals[trim:-trim]

    threshold = float(np.percentile(vals, 48))
    dark = vals < threshold
    runs = int(np.sum(dark[1:] & ~dark[:-1])) + (1 if len(dark) and dark[0] else 0)
    return max(0, min(50, runs))


def detect_triradius_by_triplet(theta: np.ndarray, mask_block: np.ndarray, core_bx: int, core_by: int):
    """
    Direct triradius detection: A true delta is formed by three converging ridge directions
    spaced ~120 degrees apart (pi/3). Finds the triradius with highest delta symmetry.
    """
    hh, ww = theta.shape
    best_pt = None
    best_score = -1e9

    for y in range(3, hh - 3):
        for x in range(3, ww - 3):
            if not mask_block[y, x]:
                continue
            # Must be lower than or near level with core
            if y < core_by - 1:
                continue
            dist_c = math.hypot(x - core_bx, y - core_by)
            if dist_c < 3 or dist_c > min(hh, ww) * 0.7:
                continue

            # Sample 3 directions in a small circle of radius 2
            r = 2
            angles = []
            for angle_deg in [0, 60, 120, 180, 240, 300]:
                rad = math.radians(angle_deg)
                sx = int(round(x + r * math.cos(rad)))
                sy = int(round(y + r * math.sin(rad)))
                if 0 <= sx < ww and 0 <= sy < hh and mask_block[sy, sx]:
                    angles.append(theta[sy, sx])

            if len(angles) >= 5:
                # Angular dispersion
                sins = np.sin(2 * np.array(angles))
                coss = np.cos(2 * np.array(angles))
                coherence = math.hypot(float(np.mean(sins)), float(np.mean(coss)))
                # A true triradius has HIGH angular variance (LOW coherence) among neighbors
                triradius_measure = 1.0 - coherence
                
                # Favor lateral displacement (left or right of core)
                lateral_bonus = abs(x - core_bx) / float(ww)
                score = triradius_measure * 0.7 + lateral_bonus * 0.3

                if score > best_score:
                    best_score = score
                    best_pt = (x, y)

    return best_pt


def analyze(gray: np.ndarray, filename: str):
    h, w = gray.shape
    gray_enhanced = enhance(gray)

    block = max(10, min(16, int(min(h, w) / 25)))
    mask = extract_fingerprint_mask(gray_enhanced, block_size=block)
    
    # Downsample mask to block grid
    hh, ww = h // block, w // block
    mask_block = cv2.resize(mask, (ww, hh), interpolation=cv2.INTER_NEAREST) > 127

    theta, energy, coherence, block = orientation_field(gray_enhanced, block=block)
    raw_singularities = find_singularities(theta, mask_block, energy, coherence)
    candidates = dedupe_singularities(raw_singularities, min_dist=2)

    cx, cy = w / 2.0, h / 2.0
    core_candidates = []
    delta_candidates = []

    for bx, by, is_core, quality, en, coh in candidates:
        px = int((bx + 0.5) * block)
        py = int((by + 0.5) * block)
        if is_core:
            core_candidates.append((px, py, bx, by, quality, en, coh))
        else:
            delta_candidates.append((px, py, bx, by, quality, en, coh))

    # --- Pick Best Core ---
    if core_candidates:
        def core_rank(c):
            # Prioritize upper center of foreground mask
            dist_top_center = math.hypot((c[0] - cx) / w, (c[1] - cy * 0.75) / h)
            return c[4] * 0.5 + max(0.0, 1.0 - dist_top_center * 1.5) * 0.5
        core_candidates.sort(key=core_rank, reverse=True)
        best_core = core_candidates[0]
        core = (best_core[0], best_core[1], best_core[4])
        core_bx, core_by = best_core[2], best_core[3]
    else:
        # Fallback core at centroid of mask
        coords = np.argwhere(mask_block)
        if len(coords) > 0:
            c_by, c_bx = np.mean(coords, axis=0)
            c_by = max(2, c_by - 2)
            core = (int(c_bx * block), int(c_by * block), 0.5)
            core_bx, core_by = int(c_bx), int(c_by)
        else:
            core = (int(cx), int(cy * 0.75), 0.5)
            core_bx, core_by = int(cx / block), int(cy * 0.75 / block)

    # --- Pick Best Delta ---
    delta = None
    delta_count = 0

    if delta_candidates:
        def delta_rank(d):
            px, py = d[0], d[1]
            dist_core = math.hypot(px - core[0], py - core[1])
            if dist_core < 25:
                return -1.0
            # Delta should be lower or near level with core
            y_weight = 1.0 if py >= core[1] - 10 else 0.4
            # Lateral separation from core (loops have delta on one side)
            x_sep = abs(px - core[0]) / float(w)
            return d[4] * 0.4 + y_weight * 0.3 + min(1.0, x_sep * 3.0) * 0.3

        delta_candidates.sort(key=delta_rank, reverse=True)
        valid = [d for d in delta_candidates if delta_rank(d) > 0.2]
        if valid:
            delta = (valid[0][0], valid[0][1], valid[0][4])
            delta_count = len(valid)

    # If Poincaré missed the delta, use triradius triplet divergence
    if delta is None:
        tri_pt = detect_triradius_by_triplet(theta, mask_block, core_bx, core_by)
        if tri_pt is not None:
            delta = (int((tri_pt[0] + 0.5) * block), int((tri_pt[1] + 0.5) * block), 0.65)
            delta_count = 1

    # --- Classification & Ridge Count ---
    if delta_count == 0:
        pattern = "Arch"
        pattern_code = "A"
    elif delta_count == 1:
        pattern = "Loop"
        pattern_code = "L"
    else:
        pattern = "Whorl"
        pattern_code = "W"

    if core and delta:
        rc = local_ridge_count(gray_enhanced, (core[0], core[1]), (delta[0], delta[1]))
        if pattern == "Loop" and rc < 5:
            pattern = "Tented Arch"
            pattern_code = "TA"
        conf = min(0.96, max(0.55, 0.4 * core[2] + 0.4 * delta[2] + min(0.2, rc / 40.0)))
        confidence = round(float(conf) * 100.0, 1)
        status = "success" if rc >= 1 else "uncertain"
    elif "Arch" in pattern:
        rc = 0
        confidence = 88.0
        status = "success"
    else:
        rc = None
        confidence = 50.0
        status = "uncertain"

    def pt(p):
        return {"x": max(0, min(w - 1, int(p[0]))), "y": max(0, min(h - 1, int(p[1])))} if p else None

    return {
        "filename": filename,
        "width": int(w),
        "height": int(h),
        "pattern": pattern,
        "pattern_code": pattern_code,
        "delta_count": delta_count,
        "core": pt(core),
        "delta": pt(delta),
        "ridge_count": rc,
        "confidence": confidence,
        "status": status,
        "enhancement_attempted": True,
        "retry_attempted": False,
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "fingerprint-analyzer"}


@app.post("/api/analyze")
async def analyze_images(files: List[UploadFile] = File(...)):
    if len(files) > 30:
        raise HTTPException(status_code=400, detail="Maximum 30 images allowed.")
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one image.")

    analyses = []
    for index, file in enumerate(files):
        data = await file.read()
        try:
            gray = decode_image(data)
            if gray.shape[0] < 100 or gray.shape[1] < 100:
                raise ValueError("Image is too small")
            analyses.append({"index": index, **analyze(gray, file.filename or f"image-{index+1}.png")})
        except Exception as exc:
            analyses.append({
                "index": index,
                "filename": file.filename or f"image-{index+1}.png",
                "pattern": None,
                "pattern_code": None,
                "delta_count": 0,
                "core": None,
                "delta": None,
                "ridge_count": None,
                "confidence": 0,
                "status": "error",
                "error": str(exc),
            })

    grouped = {finger: [] for finger in FINGERS}
    finger_keys = [
        ("L1", ["l1", "left thumb", "l_thumb", "lthumb"]),
        ("L2", ["l2", "left index", "l_index", "lindex"]),
        ("L3", ["l3", "left middle", "l_middle", "lmiddle"]),
        ("L4", ["l4", "left ring", "l_ring", "lring"]),
        ("L5", ["l5", "left little", "l_little", "llittle"]),
        ("R1", ["r1", "right thumb", "r_thumb", "rthumb"]),
        ("R2", ["r2", "right index", "r_index", "rindex"]),
        ("R3", ["r3", "right middle", "r_middle", "rmiddle"]),
        ("R4", ["r4", "right ring", "r_ring", "rring"]),
        ("R5", ["r5", "right little", "r_little", "rlittle"]),
    ]

    for result in analyses:
        fn = (result.get("filename") or "").lower()
        matched_finger = None
        for code, aliases in finger_keys:
            if any(alias in fn for alias in aliases):
                for f_name in FINGERS:
                    if f_name.startswith(code):
                        matched_finger = f_name
                        break
            if matched_finger:
                break

        if matched_finger:
            grouped[matched_finger].append(result)
        else:
            slot = (result["index"] // 3) if len(analyses) >= 10 else (result["index"] % 10)
            slot = min(slot, 9)
            grouped[FINGERS[slot]].append(result)

    selected = []
    for finger, items in grouped.items():
        valid = [x for x in items if x.get("status") == "success" and x.get("ridge_count") is not None]
        best = max(valid, key=lambda x: x.get("confidence", 0)) if valid else (items[0] if items else None)
        if best:
            selected.append({"finger": finger, **best, "all_captures": items})

    trc = sum(x["ridge_count"] for x in selected if isinstance(x.get("ridge_count"), int))
    return {
        "max_images": 30,
        "received": len(files),
        "grouping": "3 captures per finger",
        "analyses": analyses,
        "finger_results": selected,
        "grouped_by_finger": grouped,
        "trc": trc,
    }
