import base64, json, sys, urllib.request
from pathlib import Path
OUT = Path(__file__).parent / "gen"
P = {
 "seller": ("16:9", "Cinematic photo, 16:9. A young Iranian woman jewelry maker in her small home workshop, wearing a loose cream linen shirt and a light patterned headscarf, sitting at a wooden workbench and typing on a laptop, side profile facing left, calm focused expression. Warm golden late-afternoon window light from the left, shallow depth of field, soft warm peach and copper tones, silver rings and small tools blurred on the bench. Subject centered in frame. Film look, no text, no logos."),
 "hand": ("16:9", "Clean studio photo, 16:9. A woman's hand holding a modern black smartphone upright, screen facing the camera straight-on, the screen is a solid pure bright green (#00FF00) with no reflections. Soft warm cream to peach gradient background, soft shadow, phone centered in frame and occupying about 75 percent of the frame height. Minimal, premium tech ad style, no text, no logos."),
}
for name in sys.argv[1:] or P:
    ar, prompt = P[name]
    body = {"model": "google/gemini-3.1-flash-image", "modalities": ["image", "text"],
            "image_config": {"aspect_ratio": ar}, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer proxy-injected", "Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=240))
    url = d["choices"][0]["message"]["images"][0]["image_url"]["url"]
    (OUT / f"{name}.png").write_bytes(base64.b64decode(url.split(",", 1)[1]))
    print(name, d.get("usage", {}).get("cost"))
