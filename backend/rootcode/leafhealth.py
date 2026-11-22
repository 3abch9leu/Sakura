"""
Leaf health - the team's own DeepLabV3 (ResNet-50) leaf-lesion segmentation model, served on demand.

Reproduced exactly from rootcode/models/combine-model.ipynb ("DeepLabV3+ v2"):
  * torchvision deeplabv3_resnet50, classifier[4] and aux_classifier[4] replaced by 2-class 1x1 convs
  * preprocessing: Resize((256, 256)) -> ToTensor -> Normalize(ImageNet mean / std)
  * output["out"], argmax over 2 classes: 1 = diseased tissue (dataset mask value 38), 0 = everything else
  * notebook validation: best IoU 0.78, Dice 0.88 (deeplabv3_history.pkl)

No download: the network is built with weights=None and the checkpoint is loaded with strict=True.
Lazy: nothing is loaded until the first analysis; one cached instance; CUDA when available, CPU otherwise.

What the model does NOT do: it does not name the disease, and it was trained on close-up leaf photos.
The "affected share" is lesion pixels over an approximate leaf mask (colour rule, not a model).
"""
import base64
import io
import os
import threading
import time

import cv2
import numpy as np

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "deeplabv3_model.pth")
SIZE = 256
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)

_MODEL = {"net": None, "device": None}
_LOAD_LOCK = threading.Lock()
_RUN_LOCK = threading.Lock()          # one inference at a time (shares the GPU with SAM 2 / SD)
STATUS = {"loaded": False, "device": None, "load_seconds": None, "last_error": None, "runs": 0}


def _device():
    import torch
    want = os.getenv("ROOTCODE_LEAF_DEVICE", "auto")
    if want == "cpu":
        return torch.device("cpu")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load():
    """Build the notebook's architecture and load the trained weights (once)."""
    if _MODEL["net"] is not None:
        return _MODEL["net"], _MODEL["device"]
    with _LOAD_LOCK:
        if _MODEL["net"] is not None:
            return _MODEL["net"], _MODEL["device"]
        import torch
        import torch.nn as nn
        from torchvision import models
        t = time.perf_counter()
        net = models.segmentation.deeplabv3_resnet50(weights=None, weights_backbone=None, num_classes=21, aux_loss=True)
        net.classifier[4] = nn.Conv2d(net.classifier[4].in_channels, 2, kernel_size=1)
        net.aux_classifier[4] = nn.Conv2d(net.aux_classifier[4].in_channels, 2, kernel_size=1)
        sd = torch.load(MODEL_PATH, map_location="cpu", weights_only=True)
        net.load_state_dict(sd, strict=True)
        dev = _device()
        try:
            net = net.to(dev).eval()
        except RuntimeError as e:                       # GPU full (e.g. during an SD render): CPU fallback
            STATUS["last_error"] = f"CUDA unavailable for leaf model: {e}"[:200]
            dev = torch.device("cpu")
            net = net.to(dev).eval()
        _MODEL.update(net=net, device=dev)
        STATUS.update(loaded=True, device=str(dev), load_seconds=round(time.perf_counter() - t, 2))
        return net, dev


def preprocess(rgb):
    """Exactly the notebook transform: PIL Resize((256,256)) (bilinear, antialias) -> ToTensor -> Normalize."""
    from PIL import Image
    im = Image.fromarray(rgb).resize((SIZE, SIZE), Image.BILINEAR)
    x = np.asarray(im, np.float32) / 255.0
    x = (x - MEAN) / STD
    return x.transpose(2, 0, 1)[None]


def predict_prob(rgb):
    """Probability of 'diseased tissue' at 256 x 256."""
    import torch
    net, dev = load()
    x = torch.from_numpy(preprocess(rgb)).to(dev)
    with _RUN_LOCK, torch.inference_mode():
        out = net(x)["out"]
        prob = torch.softmax(out, dim=1)[0, 1].float().cpu().numpy()
    if dev.type == "cuda":
        torch.cuda.synchronize()
    STATUS["runs"] += 1
    return prob


def leaf_mask(rgb):
    """Approximate plant-tissue mask (green, yellow and brown tissue vs. soil, sky, wall). A colour rule, not a model."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    r, g, b = [rgb[..., i].astype(int) for i in range(3)]
    green = (h >= 25) & (h <= 95) & (s >= 40) & (v >= 35)
    yellow_brown = (h >= 8) & (h < 25) & (s >= 60) & (v >= 40)
    exg = (2 * g - r - b) > 18
    m = (green | yellow_brown | (exg & (s >= 30))).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
    return m.astype(bool)


def _b64(img_rgb, fmt=".jpg", q=88):
    params = [cv2.IMWRITE_JPEG_QUALITY, q] if fmt == ".jpg" else []
    ok, buf = cv2.imencode(fmt, cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR) if img_rgb.ndim == 3 and img_rgb.shape[2] == 3
                           else img_rgb, params)
    return base64.b64encode(buf.tobytes()).decode()


def decode(data, max_side=1024):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    s = max_side / max(im.size)
    if s < 1:
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    return np.asarray(im)


CARE = {
    "none": ["No lesion-like region was found. Keep watching the leaves every few days, especially after hot or humid spells."],
    "low": [
        "Remove the affected leaves with clean scissors and throw them away (not in compost).",
        "Water the roots, not the leaves: INBETWEEN's gravity channels already feed the pocket from below.",
        "Check again in 3 to 5 days with a photo taken in the same light.",
    ],
    "moderate": [
        "Remove the affected leaves and check the neighbouring pockets of the same branch.",
        "Avoid wetting the foliage and keep the open cells around this plant free for airflow.",
        "If spots keep spreading within a week, show a sample to a local agronomist or plant nursery before using any treatment.",
    ],
    "high": [
        "Isolate the plant if possible: take the pocket out of the structure so the problem does not spread.",
        "Remove heavily affected leaves; replace the plant if most of it is damaged.",
        "Ask a local agronomist or plant nursery to identify the problem before using any treatment.",
    ],
}


def analyze(data, plant=None, weather=None):
    """bytes of a JPG/PNG -> lesion mask, overlay, affected share, timings and cautious advice."""
    t0 = time.perf_counter()
    rgb = decode(data)
    h, w = rgb.shape[:2]
    t1 = time.perf_counter()
    cold = not STATUS["loaded"]
    prob256 = predict_prob(rgb)
    t2 = time.perf_counter()

    prob = cv2.resize(prob256, (w, h), interpolation=cv2.INTER_LINEAR)
    raw = prob >= 0.5
    tissue = leaf_mask(rgb)
    # keep a detected region only if it sits on a leaf: >= 35 % of the ring around it is plant tissue
    # (drops blobs on pots, plates, soil or glass; reported, never hidden)
    n_c, lab, stats, _ = cv2.connectedComponentsWithStats(raw.astype(np.uint8))
    lesion = np.zeros_like(raw)
    ring_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(5, w // 60) | 1,) * 2)
    dropped = 0
    for i in range(1, n_c):
        x, y, bw, bh, area = stats[i]
        if area < 0.00005 * w * h:
            continue
        pad = max(5, w // 60)
        x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(w, x + bw + pad), min(h, y + bh + pad)
        comp = (lab[y0:y1, x0:x1] == i).astype(np.uint8)
        ring = cv2.dilate(comp, ring_k) & (1 - comp)
        on_leaf = tissue[y0:y1, x0:x1][ring > 0].mean() if ring.any() else 0.0
        if on_leaf >= 0.35:
            lesion[y0:y1, x0:x1] |= comp.astype(bool)
        else:
            dropped += 1
    leaf = tissue | lesion
    leaf_frac = float(leaf.mean())
    lesion_px, leaf_px = int(lesion.sum()), int(leaf.sum())
    affected = lesion_px / leaf_px if leaf_px else 0.0
    n_spots = int(cv2.connectedComponents(lesion.astype(np.uint8))[0] - 1)

    overlay = rgb.astype(np.float32)
    tint = np.array([183, 82, 40], np.float32)
    a = (np.clip((prob - 0.35) / 0.4, 0, 1) * cv2.dilate(lesion.astype(np.uint8), np.ones((3, 3), np.uint8)))[..., None] * 0.6
    overlay = overlay * (1 - a) + tint * a
    overlay = overlay.astype(np.uint8)
    cnts, _ = cv2.findContours(lesion.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay, cnts, -1, (255, 236, 200), max(1, w // 500), cv2.LINE_AA)

    warnings = []
    if dropped:
        warnings.append(f"{dropped} region(s) flagged by the model were not on a leaf (pot, soil, background) and were ignored.")
    big = 0
    nl, _, ls, _ = cv2.connectedComponentsWithStats(tissue.astype(np.uint8))
    if nl > 1:
        big = ls[1:, 4].max() / (w * h)
    if leaf_frac >= 0.08 and big < 0.2:
        warnings.append("The photo shows a whole scene rather than one leaf. The model was trained on leaf close-ups: "
                        "fill the frame with one leaf for a reliable result.")
    if leaf_frac < 0.08:
        warnings.append("Little plant tissue in the photo: come closer so one leaf fills most of the frame.")
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if cv2.Laplacian(gray, cv2.CV_64F).var() < 40:
        warnings.append("The photo looks blurry: the result may miss small spots.")
    if gray.mean() < 50:
        warnings.append("The photo is dark: take it in daylight, without flash.")
    if gray.mean() > 225:
        warnings.append("The photo is over-exposed: avoid direct sun on the leaf.")

    band = "none" if affected < 0.01 else "low" if affected < 0.05 else "moderate" if affected < 0.15 else "high"
    from .leafcare import measure, recommend
    meas = measure(rgb, lesion, tissue)
    care = recommend(band, affected, n_spots, meas, plant, weather)
    label = {"none": "No visible lesion", "low": "A few spots", "moderate": "Noticeable damage", "high": "Extensive damage"}[band]
    t3 = time.perf_counter()
    return {
        "image_size": [w, h],
        "original_jpg_base64": _b64(rgb),
        "overlay_jpg_base64": _b64(overlay),
        "affected_share": round(affected, 4),
        "lesion_share_of_image": round(float(lesion.mean()), 4),
        "leaf_share_of_image": round(leaf_frac, 4),
        "spots": n_spots,
        "regions_ignored": dropped,
        "mean_confidence": round(float(prob[lesion].mean()), 3) if lesion_px else None,
        "severity": band, "label": label,
        "recommendations": CARE[band],
        "care": care,
        "measurements": meas,
        "weather_used": bool(weather),
        "warnings": warnings,
        "plant": plant,
        "model": {"name": "DeepLabV3-ResNet50 (team model, combine-model.ipynb)", "device": STATUS["device"],
                  "input": f"{SIZE}x{SIZE}", "validation": "IoU 0.78 / Dice 0.88 on the notebook validation split"},
        "timing_ms": {"decode": round((t1 - t0) * 1000, 1), "inference": round((t2 - t1) * 1000, 1),
                      "post": round((t3 - t2) * 1000, 1), "total": round((t3 - t0) * 1000, 1),
                      "includes_model_load": cold},
        "disclaimer": ("Segmentation of lesion-like regions only: it does not identify the disease, and the "
                       "affected share is an estimate (leaf area from a colour rule). Not a diagnosis."),
    }
