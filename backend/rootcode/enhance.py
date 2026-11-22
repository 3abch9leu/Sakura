"""
Stage 2 - AI-enhanced photorealistic render of the Stage 1 try-on.

Stable Diffusion 1.5 + ControlNet (Canny) img2img:
  * input image   = the Stage 1 try-on (real optimized geometry painted on the real photo)
  * control image = Canny edges of that try-on, so the tile grid, pockets and perforations keep
                    their place while the materials, light and plants become photographic
  * the result is pasted back ONLY inside the try-on mask (feathered); everything outside the
    tiles stays the original photo, at the original resolution.

Fits a 6 GB RTX 4050: fp16 + model CPU offload + attention slicing + VAE slicing.
Weights are cached in ROOTCODE_HF_CACHE (default: <project parent>/hf_cache, i.e. on the D: drive).
If anything fails, the Stage 1 image is returned with "enhancement unavailable: <reason>".
Nothing is ever faked.
"""
import os
import threading
import time

import cv2
import numpy as np

BASE_MODEL = "stable-diffusion-v1-5/stable-diffusion-v1-5"   # runwayml/... was removed from the Hub
CONTROLNET = "lllyasviel/control_v11p_sd15_canny"
CACHE_DIR = os.getenv("ROOTCODE_HF_CACHE",
                      os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "hf_cache")))

PROMPT = ("architectural photograph of an apartment building facade covered with handcrafted terracotta "
          "tiles with geometric eight-point star perforations, small edible herbs and strawberries growing "
          "in ceramic pockets, Mediterranean sunlight, soft shadows, realistic materials, high detail")
NEGATIVE = "cartoon, blurry, distorted geometry, extra windows, text, watermark, deformed"
CAPTION = "AI-enhanced visualization of the optimized design"

DEFAULT_STRENGTH = 0.35   # best tile-geometry preservation (tested 0.35 / 0.45 / 0.55)
DEFAULT_SEED = 42
STEPS = 20                # UniPC: 20 x strength 0.35 = 7 denoising steps (same look as 25 in our tests)
FULL_GPU_MIN_FREE_MB = 4000   # whole pipeline on the GPU when this much VRAM is free (3.7 GB peak + margin)
PROBE_SPILL_S = 4.0           # warm-up probe slower than this on full GPU = VRAM spill -> switch to CPU offload
MAX_SIDE = 768

_PIPE = None
_LOCK = threading.Lock()          # one render at a time on a 6 GB GPU
STATUS = {"pipeline_loaded": False, "load_seconds": None, "last_error": None,
          "last_render_seconds": None, "peak_vram_mb": None, "placement": None}


# ---------------------------------------------------------------- status (cheap, loads nothing)
def weights_cached():
    """True if both model folders are already in the local cache."""
    def has(repo):
        d = os.path.join(CACHE_DIR, "models--" + repo.replace("/", "--"), "snapshots")
        return os.path.isdir(d) and any(os.scandir(d))
    return has(BASE_MODEL) and has(CONTROLNET)


def status():
    try:
        import diffusers
        ver = diffusers.__version__
    except Exception as e:
        ver = None
        STATUS.setdefault("last_error", f"diffusers not installed: {e}")
    return {"diffusers": ver, "base_model": BASE_MODEL, "controlnet": CONTROLNET,
            "weights_cached": weights_cached(), "cache_dir": CACHE_DIR, **STATUS}


# ---------------------------------------------------------------- pipeline
def load_pipeline():
    """Load once and cache (about 30 s the first time)."""
    global _PIPE
    if _PIPE is not None:
        return _PIPE
    import torch
    from diffusers import ControlNetModel, StableDiffusionControlNetImg2ImgPipeline, UniPCMultistepScheduler

    if not torch.cuda.is_available():
        raise RuntimeError("no CUDA GPU (CPU rendering would take minutes)")
    t = time.perf_counter()
    kw = dict(torch_dtype=torch.float16, variant="fp16", cache_dir=CACHE_DIR,
              local_files_only=weights_cached())     # no Hub round-trip once downloaded (venue Wi-Fi)
    controlnet = ControlNetModel.from_pretrained(CONTROLNET, **kw)
    pipe = StableDiffusionControlNetImg2ImgPipeline.from_pretrained(
        BASE_MODEL, controlnet=controlnet, safety_checker=None, requires_safety_checker=False, **kw)
    pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)
    free_mb = torch.cuda.mem_get_info()[0] / 2**20
    if free_mb >= FULL_GPU_MIN_FREE_MB and os.getenv("ROOTCODE_SD_OFFLOAD", "0") != "1":
        pipe.to("cuda")                      # everything stays on the GPU: ~3x faster than CPU offload
        STATUS["placement"] = f"full GPU ({free_mb:.0f} MB were free)"
    else:
        pipe.enable_model_cpu_offload()      # tight VRAM: only the active sub-model sits on the GPU
        STATUS["placement"] = f"CPU offload ({free_mb:.0f} MB free, {FULL_GPU_MIN_FREE_MB} needed for full GPU)"
    pipe.enable_attention_slicing()
    try:
        pipe.vae.enable_slicing()
    except Exception:
        pipe.enable_vae_slicing()
    pipe.set_progress_bar_config(disable=True)
    _PIPE = pipe
    STATUS.update(pipeline_loaded=True, load_seconds=round(time.perf_counter() - t, 1), last_error=None)
    return pipe


# ---------------------------------------------------------------- helpers
def _to_offload():
    """Out of memory on the GPU: fall back to CPU offload for the rest of the session."""
    import torch
    if _PIPE is None or str(STATUS.get("placement", "")).startswith("CPU"):
        return False
    _PIPE.to("cpu")
    torch.cuda.empty_cache()
    _PIPE.enable_model_cpu_offload()
    STATUS["placement"] = "CPU offload (switched after a GPU out-of-memory)"
    return True


def warm_up():
    """Load the pipeline at server start and run one tiny render, so the user's first preview is not 60 s."""
    try:
        import torch
        if not torch.cuda.is_available() or not weights_cached():
            return
        t = time.perf_counter()
        from PIL import Image
        im = Image.fromarray(np.full((512, 768, 3), 200, np.uint8))

        def probe():
            t1 = time.perf_counter()
            pipe(prompt="wall", negative_prompt="", image=im, control_image=im, strength=0.5, num_inference_steps=4,
                 guidance_scale=7.0, generator=torch.Generator(device="cpu").manual_seed(0))
            torch.cuda.synchronize()
            return time.perf_counter() - t1

        with _LOCK:
            pipe = load_pipeline()
            probe()                                   # first run: CUDA kernels, cuDNN autotune
            secs = probe()                            # real-size run with classifier-free guidance, 2 steps
            STATUS["probe_seconds"] = round(secs, 2)
            # a full-GPU pipeline does this in well under 2 s; much slower means VRAM spilled into shared
            # system memory (another program holds the GPU) -> CPU offload is faster and stable
            if secs > PROBE_SPILL_S and _to_offload():
                STATUS["probe_seconds_offload"] = round(probe(), 2)
        STATUS["warm_seconds"] = round(time.perf_counter() - t, 1)
    except Exception as e:
        STATUS["last_error"] = f"warm-up: {type(e).__name__}: {e}"[:300]


def _fit(img, max_side=MAX_SIDE):
    """Resize so the long side is <= max_side and both sides are multiples of 8."""
    h, w = img.shape[:2]
    s = min(1.0, max_side / max(h, w))
    nw, nh = max(8, int(w * s) // 8 * 8), max(8, int(h * s) // 8 * 8)
    return cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)


def canny(img_rgb, lo=100, hi=200):
    e = cv2.Canny(cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY), lo, hi)
    return np.dstack([e, e, e])


def composite(original, generated, mask, feather_frac=0.012):
    """Paste `generated` over `original` only inside `mask`, with feathered edges."""
    h, w = original.shape[:2]
    gen = cv2.resize(generated, (w, h), interpolation=cv2.INTER_CUBIC)
    k = max(3, int(feather_frac * max(h, w)) | 1)
    # erode first, then blur: the soft edge fades out INSIDE the mask, never spills past it
    inner = cv2.erode(mask.astype(np.uint8), np.ones((k, k), np.uint8))
    m = cv2.GaussianBlur(inner.astype(np.float32), (k, k), 0)
    m = (m * mask)[..., None]
    out = gen.astype(np.float32) * m + original.astype(np.float32) * (1 - m)
    return np.clip(out, 0, 255).astype(np.uint8)


def caption(img, text=CAPTION):
    out = img.copy()
    h, w = out.shape[:2]
    scale = max(0.45, w / 1800)
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    pad = int(8 * scale / 0.45)
    y0 = h - th - base - 2 * pad
    band = out[y0:h, 0:tw + 2 * pad].astype(np.float32)
    out[y0:h, 0:tw + 2 * pad] = (band * 0.45).astype(np.uint8)
    cv2.putText(out, text, (pad, h - base - pad), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1,
                cv2.LINE_AA)
    return out


# ---------------------------------------------------------------- main entry point
def enhance(tryon_rgb, mask, strength=DEFAULT_STRENGTH, seed=DEFAULT_SEED, steps=STEPS,
            prompt=PROMPT, negative=NEGATIVE, conditioning_scale=1.0, add_caption=True):
    """
    tryon_rgb: Stage 1 image (RGB uint8), mask: uint8 0/1 area covered by tiles.
    Returns dict(image, enhanced: bool, message, seconds, strength, seed, peak_vram_mb).
    On any failure the Stage 1 image is returned unchanged with the reason.
    """
    t = time.perf_counter()
    try:
        # Work on the tiled area only (+ context margin): the tiles get the full 768 px budget
        # instead of a few hundred pixels of a downscaled full photo.
        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            raise ValueError("empty try-on mask")
        H, W = mask.shape[:2]
        mx, my = int(0.15 * (xs.max() - xs.min())) + 8, int(0.15 * (ys.max() - ys.min())) + 8
        x0, x1 = max(0, xs.min() - mx), min(W, xs.max() + mx + 1)
        y0, y1 = max(0, ys.min() - my), min(H, ys.max() + my + 1)
        crop = tryon_rgb[y0:y1, x0:x1]
        with _LOCK:
            import torch
            pipe = load_pipeline()
            small = _fit(crop)
            control = canny(small)
            from PIL import Image
            torch.cuda.reset_peak_memory_stats()
            def run():
                gen = torch.Generator(device="cpu").manual_seed(int(seed))
                return pipe(prompt=prompt, negative_prompt=negative,
                            image=Image.fromarray(small), control_image=Image.fromarray(control),
                            strength=float(strength), controlnet_conditioning_scale=float(conditioning_scale),
                            num_inference_steps=int(steps), guidance_scale=7.0, generator=gen).images[0]
            try:
                result = run()
            except torch.cuda.OutOfMemoryError:
                if not _to_offload():
                    raise
                result = run()
            peak = round(torch.cuda.max_memory_allocated() / 2**20)
        out = tryon_rgb.copy()
        out[y0:y1, x0:x1] = composite(crop, np.array(result), mask[y0:y1, x0:x1])
        if add_caption:
            out = caption(out)
        secs = round(time.perf_counter() - t, 2)
        STATUS.update(last_render_seconds=secs, peak_vram_mb=peak, last_error=None)
        return {"image": out, "enhanced": True, "message": "ok", "seconds": secs,
                "strength": float(strength), "seed": int(seed), "peak_vram_mb": peak}
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"[:300]
        STATUS["last_error"] = reason
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass
        return {"image": tryon_rgb, "enhanced": False, "message": f"enhancement unavailable: {reason}",
                "seconds": round(time.perf_counter() - t, 2), "strength": float(strength),
                "seed": int(seed), "peak_vram_mb": None}
