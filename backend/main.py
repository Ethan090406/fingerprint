from __future__ import annotations

import math
from typing import List

import cv2
import numpy as np
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Fingerprint Analyzer API", version="0.4.0")
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


# ---------------------------------------------------------------- basics
def enhance(gray):
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def estimate_ridge_period(gray, mask):
    """Dominant ridge period (px) from the FFT of the most textured central window."""
    h, w = gray.shape
    win = int(min(160, min(h, w) // 2))
    win -= win % 2
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return 8.0
    cy, cx = int(np.median(ys)), int(np.median(xs))
    ests = []
    for dy in (-win // 2, 0, win // 2):
        for dx in (-win // 2, 0, win // 2):
            y0 = int(np.clip(cy + dy - win // 2, 0, h - win))
            x0 = int(np.clip(cx + dx - win // 2, 0, w - win))
            m = mask[y0:y0 + win, x0:x0 + win]
            if m.mean() < 0.9:
                continue
            patch = gray[y0:y0 + win, x0:x0 + win].astype(np.float32)
            patch = cv2.GaussianBlur(patch, (0, 0), 1.0) - cv2.GaussianBlur(patch, (0, 0), 9.0)
            patch *= np.outer(np.hanning(win), np.hanning(win)).astype(np.float32)
            spec = np.abs(np.fft.fftshift(np.fft.fft2(patch))) ** 2
            yy, xx = np.indices(spec.shape)
            r = np.hypot(yy - win // 2, xx - win // 2)
            lo, hi = win / 20.0, win / 5.0           # periods 20 .. 5 px
            sel = (r >= lo) & (r <= hi)
            if not sel.any():
                continue
            rb = np.round(r[sel]).astype(int)
            prof = np.bincount(rb, weights=spec[sel])
            cnt = np.bincount(rb)
            prof = prof / np.maximum(cnt, 1)
            k = int(np.argmax(prof))
            if k <= 0:
                continue
            # peak must stand out from the rest of the band
            if prof[k] < 2.0 * float(np.median(prof[prof > 0])):
                continue
            ests.append(win / k)
    if not ests:
        return 8.0
    return float(np.clip(np.median(ests), 5.5, 20.0))


def foreground_mask(gray, p):
    g = gray.astype(np.float32)
    k = max(3, int(round(p * 1.5)) | 1)
    mean = cv2.blur(g, (k, k))
    sq = cv2.blur(g * g, (k, k))
    std = np.sqrt(np.clip(sq - mean * mean, 0, None))
    std8 = cv2.normalize(std, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    t, _ = cv2.threshold(std8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = (std8 > max(8, 0.6 * t)).astype(np.uint8) * 255
    ks = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(p * 2) | 1, int(p * 2) | 1))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, ks)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, ks)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n > 1:
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        mask = (lab == big).astype(np.uint8) * 255
    # fill holes (pad first so the flood fill always starts on background)
    h, w = mask.shape
    pad = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    ff = cv2.bitwise_not(pad)
    cv2.floodFill(ff, np.zeros((h + 4, w + 4), np.uint8), (0, 0), 0)
    mask = (pad | ff)[1:-1, 1:-1]
    return mask > 0


# ---------------------------------------------------------------- orientation
def orientation_field(gray, p):
    g = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), max(0.8, 0.25 * p))
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    sw = max(2.0, 1.1 * p)
    Jxx = cv2.GaussianBlur(gx * gx, (0, 0), sw)
    Jyy = cv2.GaussianBlur(gy * gy, (0, 0), sw)
    Jxy = cv2.GaussianBlur(gx * gy, (0, 0), sw)
    c2 = Jxx - Jyy
    s2 = 2.0 * Jxy
    mag = np.sqrt(c2 * c2 + s2 * s2)
    coh = mag / (Jxx + Jyy + 1e-6)
    # unit doubled-angle vectors, smoothed once more so noise does not make fake singularities
    ux = cv2.GaussianBlur(c2 / (mag + 1e-6), (0, 0), max(1.5, 0.8 * p))
    uy = cv2.GaussianBlur(s2 / (mag + 1e-6), (0, 0), max(1.5, 0.8 * p))
    theta = 0.5 * np.arctan2(uy, ux) + math.pi / 2.0      # ridge direction, mod pi
    return theta, coh


def wrap(d):
    return (d + math.pi / 2.0) % math.pi - math.pi / 2.0


def poincare_map(theta, coh, mask, radius, ys, xs, n=16, coh_min=0.22):
    h, w = theta.shape
    ang = np.arange(n) * 2 * math.pi / n
    oy = np.round(radius * np.sin(ang)).astype(int)
    ox = np.round(radius * np.cos(ang)).astype(int)
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    yy, xx = yy.ravel(), xx.ravel()
    ring_y = yy[:, None] + oy[None, :]
    ring_x = xx[:, None] + ox[None, :]
    th = theta[ring_y, ring_x]
    d = wrap(np.roll(th, -1, axis=1) - th)
    idx = d.sum(axis=1) / (2 * math.pi)
    inside = mask[ring_y, ring_x].mean(axis=1) >= 0.999
    inside &= mask[yy, xx]
    ring_coh = coh[ring_y, ring_x].mean(axis=1)
    ok = inside & (ring_coh >= coh_min)
    out = np.zeros((len(ys), len(xs)), np.float32)
    okm = np.zeros_like(out, dtype=bool)
    out[:] = idx.reshape(out.shape)
    okm[:] = ok.reshape(out.shape)
    return out, okm


def find_singularities(theta, coh, mask, p, relaxed=False):
    step = max(2, int(round(p / 2)))
    R1 = max(6, int(round(2.2 * p)))
    R2 = max(9, int(round(3.4 * p)))
    cm = 0.15 if relaxed else 0.22
    th_i = 0.30 if relaxed else 0.38
    h, w = theta.shape
    m = R2 + 2
    ys = np.arange(m, h - m, step)
    xs = np.arange(m, w - m, step)
    i1, ok1 = poincare_map(theta, coh, mask, R1, ys, xs, coh_min=cm)
    i2, ok2 = poincare_map(theta, coh, mask, R2, ys, xs, coh_min=cm)
    # use the bigger ring where valid, otherwise the small one
    cands = []
    for a in range(len(ys)):
        for b in range(len(xs)):
            v1 = i1[a, b] if ok1[a, b] else None
            v2 = i2[a, b] if ok2[a, b] else None
            vals = [v for v in (v1, v2) if v is not None]
            if not vals:
                continue
            if v1 is not None and v2 is not None:
                if np.sign(v1) != np.sign(v2):
                    continue
                v = min(abs(v1), abs(v2)) * np.sign(v1)
                strength = min(abs(v1), abs(v2))
            else:
                v = vals[0]
                strength = abs(v) * 0.8
            if abs(v) < th_i:
                continue
            cands.append((int(xs[b]), int(ys[a]), 1 if v > 0 else -1, float(strength), float(coh[ys[a], xs[b]])))
    return cands, R1


def cluster(cands, sign, dist):
    pts = sorted([c for c in cands if c[2] == sign], key=lambda c: c[3], reverse=True)
    out = []
    for c in pts:
        for o in out:
            if math.hypot(c[0] - o["x"], c[1] - o["y"]) <= dist:
                o["members"].append(c)
                break
        else:
            out.append({"x": c[0], "y": c[1], "members": [c]})
    res = []
    for o in out:
        m = o["members"]
        wsum = sum(k[3] for k in m)
        x = sum(k[0] * k[3] for k in m) / wsum
        y = sum(k[1] * k[3] for k in m) / wsum
        res.append({"x": x, "y": y, "n": len(m), "strength": max(k[3] for k in m)})
    # a real singularity lights up several neighbouring grid points
    return [r for r in res if r["n"] >= 2]


def multiscale_singularities(gray, mask, p0, scales=(0.75, 1.0, 1.33)):
    """Run the detector at several scales and keep singularities seen at >= 2 of them."""
    found = {+1: [], -1: []}
    for sc in scales:
        p = p0 * sc
        theta, coh = orientation_field(gray, p)
        cands, _ = find_singularities(theta, coh, mask, p)
        for sign in (+1, -1):
            for c in cluster(cands, sign, 3.0 * p):
                found[sign].append(c)
    out = {}
    for sign in (+1, -1):
        groups = []
        for c in sorted(found[sign], key=lambda c: c["strength"], reverse=True):
            for g in groups:
                if math.hypot(c["x"] - g["x"], c["y"] - g["y"]) <= 3.5 * p0:
                    g["m"].append(c)
                    break
            else:
                groups.append({"x": c["x"], "y": c["y"], "m": [c]})
        res = []
        for g in groups:
            if len(g["m"]) < 2:
                continue
            res.append({"x": float(np.mean([k["x"] for k in g["m"]])),
                        "y": float(np.mean([k["y"] for k in g["m"]])),
                        "n": len(g["m"]),
                        "strength": float(np.mean([k["strength"] for k in g["m"]]))})
        out[sign] = res
    return out[+1], out[-1]


# ---------------------------------------------------------------- ridge counting
def ridge_count(gray, core, delta, p):
    x1, y1 = core
    x2, y2 = delta
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist < 2 * p:
        return 0
    n = max(40, int(dist * 2))
    xs = np.linspace(x1, x2, n).astype(np.float32)
    ys = np.linspace(y1, y2, n).astype(np.float32)
    vals = cv2.remap(gray.astype(np.float32), xs.reshape(1, -1), ys.reshape(1, -1), cv2.INTER_LINEAR).reshape(-1)
    spp = n / dist                                    # samples per pixel
    vals = cv2.GaussianBlur(vals.reshape(1, -1), (0, 0), sigmaX=max(0.8, 0.12 * p * spp)).reshape(-1)
    trend = cv2.GaussianBlur(vals.reshape(1, -1), (0, 0), sigmaX=max(3.0, 1.2 * p * spp)).reshape(-1)
    v = vals - trend
    trim = int(0.6 * p * spp)                         # do not count the ridges at the core / delta themselves
    v = v[trim:len(v) - trim]
    if len(v) < 5:
        return 0
    thr = 0.25 * float(np.std(v))
    state, runs = 0, 0
    for s in v:
        if state <= 0 and s > thr:
            state = 1
            runs += 1
        elif state >= 0 and s < -thr:
            state = -1
    return int(min(50, runs))


# ---------------------------------------------------------------- main entry
def analyze(gray_full, filename):
    H, W = gray_full.shape
    scale = min(1.0, 700.0 / max(H, W))
    gray = cv2.resize(gray_full, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray_full
    h, w = gray.shape
    enh = enhance(gray)

    mask0 = foreground_mask(enh, 8.0)
    # ridge spacing is roughly (print width / 28); trust the FFT estimate only near that prior
    ys0, xs0 = np.nonzero(mask0)
    if len(ys0) > 100:
        (_, _), (rw, rh), _ = cv2.minAreaRect(np.column_stack([xs0, ys0]).astype(np.float32))
        prior = max(5.0, min(rw, rh) / 26.0)
    else:
        prior = 8.0
    p = float(np.clip(estimate_ridge_period(enh, mask0), 0.75 * prior, 1.3 * prior))
    mask = foreground_mask(enh, p)
    cores, deltas = multiscale_singularities(enh, mask, p)

    ys, xs = np.nonzero(mask)
    mcx = float(xs.mean()) if len(xs) else w / 2
    top = float(ys.min()) if len(ys) else 0
    bot = float(ys.max()) if len(ys) else h
    span = max(1.0, bot - top)

    # ---- core: strong, and nearer the upper-centre of the print
    core = None
    if cores:
        def crank(c):
            ypos = (c["y"] - top) / span
            return c["strength"] - 0.6 * abs(c["x"] - mcx) / w - 0.5 * abs(ypos - 0.38)
        core = max(cores, key=crank)

    # ---- delta(s): below / beside the core and clearly separated from it
    valid_deltas = []
    for d in deltas:
        if core is not None:
            if math.hypot(d["x"] - core["x"], d["y"] - core["y"]) < 4.0 * p:
                continue
            if d["y"] < core["y"] - 2.0 * p:
                continue
        valid_deltas.append(d)

    relaxed_used = False
    if core is not None and not valid_deltas:
        theta, coh = orientation_field(enh, p)
        c2, _ = find_singularities(theta, coh, mask, p, relaxed=True)
        dd = [d for d in cluster(c2, -1, 3.0 * p)
              if math.hypot(d["x"] - core["x"], d["y"] - core["y"]) >= 4.0 * p and d["y"] >= core["y"] - 2.0 * p]
        if dd:
            valid_deltas = dd
            relaxed_used = True

    delta = None
    if valid_deltas and core is not None:
        def drank(d):
            dist = math.hypot(d["x"] - core["x"], d["y"] - core["y"]) / span
            return d["strength"] - 0.5 * max(0.0, dist - 0.6)
        delta = max(valid_deltas, key=drank)

    # ---- classification
    # two deltas on opposite sides of the core axis => whorl
    sides = {int(np.sign(d["x"] - core["x"])) for d in valid_deltas} if core else set()
    if core is None or not valid_deltas:
        n_delta = 0
    elif len(valid_deltas) >= 2 and len(sides - {0}) == 2:
        n_delta = 2
    else:
        n_delta = 1

    status = "success"
    if core is None:
        pattern, code = "Unknown", "?"
        status = "uncertain"
    elif n_delta == 0:
        pattern, code = "Arch", "A"
    elif n_delta == 1:
        pattern, code = "Loop", "L"
    else:
        pattern, code = "Whorl", "W"

    rc = None
    conf = 50.0
    if core is not None and delta is not None:
        rc = ridge_count(enh, (core["x"], core["y"]), (delta["x"], delta["y"]), p)
        if pattern == "Loop" and rc < 3:
            pattern, code = "Tented Arch", "TA"
        q = 0.5 * min(1.0, core["strength"] / 0.5) + 0.5 * min(1.0, delta["strength"] / 0.5)
        conf = 55.0 + 41.0 * q
        if relaxed_used:
            conf = min(conf, 70.0)
        if rc < 1:
            status = "uncertain"
    elif core is not None:
        rc = 0
        conf = 80.0
    if core is None:
        # nothing reliable: leave the markers for the manual editor instead of inventing a position
        core_pt = None
    else:
        core_pt = core

    def pt(d):
        if d is None:
            return None
        return {"x": int(round(max(0, min(W - 1, d["x"] / scale)))), "y": int(round(max(0, min(H - 1, d["y"] / scale))))}

    return {
        "filename": filename,
        "width": int(W), "height": int(H),
        "pattern": pattern, "pattern_code": code,
        "delta_count": n_delta,
        "core": pt(core_pt), "delta": pt(delta),
        "ridge_count": rc,
        "confidence": round(float(conf), 1),
        "status": status,
        "enhancement_attempted": True,
        "retry_attempted": relaxed_used,
    }


# ---------------------------------------------------------------- API
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
