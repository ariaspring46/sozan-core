#!/usr/bin/env python3
"""تولید تصویر آذرگ (موجود نماد برند) با ComfyUI + z_image_turbo روی GPU محلی.

نیازمند: ComfyUI روی http://127.0.0.1:8188 با مدل‌های:
  - diffusion_models/z_image_turbo_bf16.safetensors
  - text_encoders/qwen_3_4b.safetensors
  - vae/ae.safetensors

خروجی: PNG در promo-engine/brand/character.png و character-avatar.png
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

COMFY = "http://127.0.0.1:8188"
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "brand"

PROMPT = (
    "Clean brand logo emblem on a smooth cream-white background, flat vector illustration, "
    "minimalist anime mascot logo. A large stylized creature named Azar centered, filling most "
    "of the frame, rendered as a logo mark — warm copper linework and fill (#C66C43), charcoal "
    "accents, a single amber eye, a small ember glow in the chest. Anime key-visual creature but "
    "flat and clean like an app logo, defined outlines, cel-shaded with few tones, no gradient "
    "background, solid cream background. Warm copper and charcoal palette only. The creature sits "
    "alert and confident as a brand symbol, a few ember sparks. Simple, iconic, centered emblem, "
    "high contrast against the light background. Persian-night warmth but bright clean logo style."
)

NEGATIVE = (
    "dark background, black background, scene, environment, realistic, photorealistic, 3d render, "
    "human face, human, two eyes, mouth, teeth, smile, neon, chrome, glossy plastic, circuit board, "
    "blue, purple, green, text, watermark, logo text, cluttered, busy background, second creature, "
    "tiny, small, distant, chibi deformed, ugly, blurry, low detail, messy lines, watercolor, "
    "pencil sketch, noisy, gradient sky, shadows."
)


def build_workflow(prompt: str, seed: int, width: int = 1024, height: int = 1024) -> dict:
    return {
        "28": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"},
        },
        "30": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"},
        },
        "29": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "ae.safetensors"},
        },
        "11": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["28", 0], "shift": 3.0},
        },
        "27": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["30", 0], "text": prompt},
        },
        "33": {
            "class_type": "ConditioningZeroOut",
            "inputs": {"conditioning": ["27", 0]},
        },
        "13": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["11", 0],
                "positive": ["27", 0],
                "negative": ["33", 0],
                "latent_image": ["13", 0],
                "seed": seed,
                "steps": 8,
                "cfg": 1.0,
                "sampler_name": "res_multistep",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["29", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "azar"},
        },
    }


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    workflow = build_workflow(PROMPT, seed)

    with httpx.Client(timeout=600, trust_env=False) as c:
        # queue the prompt
        r = c.post(f"{COMFY}/prompt", json={"prompt": workflow}, timeout=30)
        r.raise_for_status()
        pid = r.json()["prompt_id"]
        print(f"queued prompt_id={pid} seed={seed}")

        # poll history (lowvram makes first run slow — model loads/offloads)
        deadline = time.time() + 540
        while time.time() < deadline:
            try:
                h = c.get(f"{COMFY}/history/{pid}", timeout=30).json()
            except Exception:
                h = {}
            if pid in h:
                outputs = h[pid].get("outputs", {})
                if "9" in outputs:
                    images = outputs["9"].get("images", [])
                    if images:
                        img = images[0]
                        fname, subfolder = img["filename"], img.get("subfolder", "")
                        url = f"{COMFY}/view?filename={fname}&subfolder={subfolder}&type=output"
                        data = c.get(url).content
                        OUT_DIR.mkdir(parents=True, exist_ok=True)
                        out_path = OUT_DIR / f"azar-seed{seed}.png"
                        out_path.write_bytes(data)
                        print(f"saved: {out_path} ({len(data)} bytes)")
                        return
            time.sleep(4)
        print("timeout waiting for image", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()