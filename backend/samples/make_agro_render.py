"""
Agro visual for the landing page (AI visualisation, labelled on the site), with the project's SD 1.5 + ControlNet.
Layout from a line drawing: elevated growing troughs on a frame, tank above, drainage pipe below.

    python samples/make_agro_render.py --seeds 5 17 --out front/public/images/agro
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rootcode.enhance import BASE_MODEL, CACHE_DIR, CONTROLNET, weights_cached  # noqa: E402

W, H = 704, 512
PROMPT = ("photograph, elevated wooden raised-bed planters on a metal frame in a Tunisian farm field, rows of lettuce "
          "and herbs, water tank on top, drainage pipe below, olive trees, warm afternoon sunlight, realistic, high detail")
NEGATIVE = "cartoon, illustration, cgi, blurry, distorted, text, watermark, people, lowres"


def control():
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    d.line([(0, 300), (W, 290)], fill=255, width=2)                 # horizon
    for k, (x0, y0, x1) in enumerate([(70, 250, 640), (40, 330, 670)]):
        d.rectangle([x0, y0, x1, y0 + 46], outline=255, width=3)     # trough
        for x in range(x0 + 20, x1, 58):                             # plants
            d.ellipse([x, y0 - 18, x + 30, y0 + 6], outline=255, width=2)
        for x in (x0 + 10, (x0 + x1) // 2, x1 - 10):                 # legs
            d.line([(x, y0 + 46), (x, y0 + 130 + k * 40)], fill=255, width=3)
        d.line([(x0, y0 + 60), (x1, y0 + 66)], fill=255, width=2)    # drainage pipe
    d.rectangle([300, 150, 410, 215], outline=255, width=3)          # tank
    d.line([(355, 215), (355, 250)], fill=255, width=3)
    return Image.merge("RGB", [img] * 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[5, 17])
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "front", "public", "images", "agro"))
    a = ap.parse_args()
    import torch
    from diffusers import ControlNetModel, StableDiffusionControlNetPipeline, UniPCMultistepScheduler
    kw = dict(torch_dtype=torch.float16, variant="fp16", cache_dir=CACHE_DIR, local_files_only=weights_cached())
    pipe = StableDiffusionControlNetPipeline.from_pretrained(
        BASE_MODEL, controlnet=ControlNetModel.from_pretrained(CONTROLNET, **kw), safety_checker=None,
        requires_safety_checker=False, **kw)
    pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)
    pipe.enable_model_cpu_offload()
    pipe.set_progress_bar_config(disable=True)
    c = control()
    for s in a.seeds:
        im = pipe(PROMPT, negative_prompt=NEGATIVE, image=c, num_inference_steps=30, guidance_scale=7.5,
                  controlnet_conditioning_scale=0.7, generator=torch.Generator("cpu").manual_seed(s)).images[0]
        im.save(f"{a.out}_{s}.jpg", quality=90)
        print("wrote", f"{a.out}_{s}.jpg")


if __name__ == "__main__":
    main()
