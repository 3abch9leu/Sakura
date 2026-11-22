"""
Hero visual for the landing page, made with the project's own Stage-2 models (SD 1.5 + ControlNet Canny,
cached in ../hf_cache). A line drawing fixes the layout of the INBETWEEN wall (shade tiles with star
perforations above, root tiles with plant pockets at the bottom, reservoir on top), and the diffusion model
renders materials and light. Output is an AI visualisation, labelled as such on the site.

    python samples/make_hero_render.py --seeds 11 23 37 42 --out front/public/images/hero
"""
import argparse
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rootcode.enhance import BASE_MODEL, CACHE_DIR, CONTROLNET, weights_cached  # noqa: E402

W, H = 576, 704
PROMPT = ("architectural photograph, terracotta clay tile screen with eight-point star perforations on a white "
          "Tunisian apartment balcony wall, bottom row of terracotta planters with green herbs, small tank on top, "
          "warm Mediterranean sunlight, soft shadows, realistic, high detail")
NEGATIVE = ("cartoon, illustration, render, cgi, blurry, distorted, deformed, text, watermark, logo, people, "
            "oversaturated, lowres")


def star(cx, cy, r_out, r_in, n=8, rot=-math.pi / 2):
    pts = []
    for i in range(2 * n):
        r = r_out if i % 2 == 0 else r_in
        a = rot + i * math.pi / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def control_image():
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    line = lambda xy, w=2: d.line(xy, fill=255, width=w)  # noqa: E731
    # building outline, slab edges, balcony
    line([(0, 90), (W, 70)], 3)
    line([(0, 610), (W, 600)], 3)
    line([(0, 640), (W, 632)], 2)
    for x in range(30, W, 46):                     # balcony railing
        line([(x, 610), (x, 640)], 1)
    # wall grid: 4 columns x 4 rows of tiles, x 120..480, y 170..590
    x0, y0, tw, th, nx, ny = 120, 175, 88, 100, 4, 4
    for i in range(nx + 1):
        line([(x0 + i * tw, y0), (x0 + i * tw, y0 + ny * th)], 2)
    for j in range(ny + 1):
        line([(x0, y0 + j * th), (x0 + nx * tw, y0 + j * th)], 2)
    for j in range(ny - 1):                        # shade tiles: star perforations
        for i in range(nx):
            cx0, cy0 = x0 + i * tw, y0 + j * th
            for a in range(2):
                for b in range(2):
                    cx, cy = cx0 + 22 + a * 44, cy0 + 25 + b * 50
                    d.polygon(star(cx, cy, 17, 8), outline=255)
    jr = ny - 1                                    # root tiles: pockets
    for i in range(nx):
        cx0, cy0 = x0 + i * tw, y0 + jr * th
        for a in range(2):
            d.rectangle([cx0 + 8 + a * 40, cy0 + 50, cx0 + 40 + a * 40, cy0 + 88], outline=255, width=2)
    # reservoir on top with a descending channel
    d.rectangle([x0 + 120, y0 - 60, x0 + 232, y0 - 14], outline=255, width=3)
    line([(x0 + 176, y0 - 14), (x0 + 176, y0)], 3)
    # side window
    d.rectangle([20, 200, 95, 520], outline=255, width=2)
    d.rectangle([505, 200, 560, 520], outline=255, width=2)
    return Image.merge("RGB", [img] * 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[11, 23, 37, 42])
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "front", "public", "images", "hero"))
    ap.add_argument("--scale", type=float, default=0.75, help="ControlNet conditioning scale")
    a = ap.parse_args()
    import torch
    from diffusers import ControlNetModel, StableDiffusionControlNetPipeline, UniPCMultistepScheduler
    kw = dict(torch_dtype=torch.float16, variant="fp16", cache_dir=CACHE_DIR, local_files_only=weights_cached())
    cn = ControlNetModel.from_pretrained(CONTROLNET, **kw)
    pipe = StableDiffusionControlNetPipeline.from_pretrained(BASE_MODEL, controlnet=cn, safety_checker=None,
                                                             requires_safety_checker=False, **kw)
    pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)
    pipe.enable_model_cpu_offload()
    pipe.enable_attention_slicing()
    pipe.set_progress_bar_config(disable=True)
    ctrl = control_image()
    ctrl.save(a.out + "_control.png")
    for s in a.seeds:
        img = pipe(PROMPT, negative_prompt=NEGATIVE, image=ctrl, num_inference_steps=30, guidance_scale=7.5,
                   controlnet_conditioning_scale=a.scale, generator=torch.Generator("cpu").manual_seed(s)).images[0]
        img.save(f"{a.out}_{s}.jpg", quality=90)
        print("wrote", f"{a.out}_{s}.jpg")


if __name__ == "__main__":
    main()
