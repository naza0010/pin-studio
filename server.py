"""
Pin Studio server - Pinterest pin generator (free)
- Runs anywhere: Render / Koyeb free (no GPU, no Gradio). Only needs Pillow + httpx.
- Images: FLUX.1-schnell via Cloudflare Workers AI (free 10k neurons/day) -> always generated, never stock
- Or your own image URLs (Pexels / Unsplash / your photos)
- Text & design: rendered by code (perfect text every time)
- Output: 1000x1500 (2:3, Pinterest standard)
"""
import os
import time
import base64
import random
from io import BytesIO

import httpx


class PinError(Exception):
    pass
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ---------------- Settings ----------------
W, H = 1000, 1500          # final pin size (2:3)

STYLE_PRESETS = {
    "crochet": (
        "realistic handmade crochet made of soft cotton yarn, clearly visible crochet stitches "
        "and yarn texture, product photography, macro detail, soft natural window light, "
        "warm beige neutral background, shallow depth of field, sharp focus, photorealistic, 8k"
    ),
    "photo": (
        "high-end editorial lifestyle photography, soft natural light, "
        "shallow depth of field, rich textures, aesthetic, pinterest style, photorealistic"
    ),
    "food": (
        "professional food photography, appetizing, fresh ingredients, soft natural light, "
        "shallow depth of field, rustic styling, photorealistic, 8k"
    ),
    "home_decor": (
        "interior design photography, cozy aesthetic home decor, soft daylight, "
        "neutral warm tones, photorealistic, magazine quality"
    ),
}
NO_TEXT = "no text, no letters, no words, no watermark, no logo"

# ---------------- Image generation (Cloudflare Workers AI) ----------------
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "").strip()
CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "").strip()
CF_MODEL = "@cf/black-forest-labs/flux-1-schnell"


def cf_generate(prompts, seed, style="photo"):
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        raise PinError("Missing CF_ACCOUNT_ID / CF_API_TOKEN in Settings -> Variables and secrets")
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_MODEL}"
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}"}
    style_txt = STYLE_PRESETS.get(style, STYLE_PRESETS["photo"])

    images = []
    for i, p in enumerate(prompts):
        body = {
            "prompt": f"{p}, {style_txt}, {NO_TEXT}",
            "steps": 4,
            "seed": (int(seed) + i * 7919) % 2147483647,
        }
        last_err = None
        for attempt in range(3):
            try:
                r = httpx.post(url, headers=headers, json=body, timeout=120)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
                data = r.json()
                b64 = (data.get("result") or {}).get("image")
                if not b64:
                    raise RuntimeError(f"No image in response: {str(data)[:300]}")
                img = Image.open(BytesIO(base64.b64decode(b64)))
                img.load()
                images.append(img.convert("RGB"))
                break
            except Exception as e:
                last_err = e
                print(f"[cloudflare] image {i + 1} attempt {attempt + 1} failed:", e)
                time.sleep(3 * (attempt + 1))
        else:
            raise PinError(f"Cloudflare image failed: {last_err}")
    return images


# ---------------- Fonts ----------------
FONTS = {
    "sans": (
        "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
        "/tmp/Montserrat.ttf",
    ),
    "display": (
        "https://github.com/google/fonts/raw/main/ofl/bangers/Bangers-Regular.ttf",
        "/tmp/Bangers.ttf",
    ),
    "round": (
        "https://github.com/google/fonts/raw/main/apache/luckiestguy/LuckiestGuy-Regular.ttf",
        "/tmp/LuckiestGuy.ttf",
    ),
    "serif": (
        "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf",
        "/tmp/PlayfairDisplay.ttf",
    ),
}
_font_cache = {}


def ensure_font(key):
    url, path = FONTS[key]
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        return path
    try:
        r = httpx.get(url, follow_redirects=True, timeout=30)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
        return path
    except Exception as e:
        print(f"Font download failed ({key}):", e)
        return None


def font(key, size, weight="Bold"):
    k = (key, size, weight)
    if k in _font_cache:
        return _font_cache[k]
    path = ensure_font(key)
    if not path:
        f = ImageFont.load_default(size=size)
    else:
        f = ImageFont.truetype(path, size)
        for name in (weight, "Bold"):
            try:
                f.set_variation_by_name(name)
                break
            except Exception:
                continue
    _font_cache[k] = f
    return f


for _k in FONTS:
    ensure_font(_k)

# ---------------- Palettes ----------------
PALETTES = {
    "cream": dict(bg=(246, 239, 229), card=(255, 252, 247), text=(43, 34, 28),
                  accent=(184, 115, 70), on_accent=(255, 255, 255)),
    "classic": dict(bg=(244, 244, 244), card=(255, 255, 255), text=(17, 17, 17),
                    accent=(17, 17, 17), on_accent=(255, 255, 255)),
    "sage": dict(bg=(225, 231, 219), card=(250, 251, 247), text=(36, 51, 40),
                 accent=(107, 133, 99), on_accent=(255, 255, 255)),
    "blush": dict(bg=(247, 227, 224), card=(255, 250, 249), text=(66, 34, 40),
                  accent=(196, 104, 116), on_accent=(255, 255, 255)),
    "navy": dict(bg=(18, 26, 42), card=(24, 34, 54), text=(255, 255, 255),
                 accent=(230, 190, 105), on_accent=(24, 34, 54)),
}

# ---------------- Helpers ----------------
_scratch = ImageDraw.Draw(Image.new("RGB", (10, 10)))


def cover(img, w, h):
    img = img.convert("RGB")
    iw, ih = img.size
    target = w / h
    if iw / ih > target:
        nw = int(ih * target)
        left = (iw - nw) // 2
        img = img.crop((left, 0, left + nw, ih))
    else:
        nh = int(iw / target)
        top = (ih - nh) // 2
        img = img.crop((0, top, iw, top + nh))
    return img.resize((w, h), Image.LANCZOS)


def paste_rounded(canvas, img, box, radius):
    x0, y0, x1, y1 = box
    im = cover(img, x1 - x0, y1 - y0).convert("RGBA")
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, im.size[0] - 1, im.size[1] - 1], radius=radius, fill=255
    )
    canvas.paste(im, (x0, y0), mask)


def add_shadow(canvas, box, radius=20, offset=(0, 12), blur=18, alpha=90):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(layer).rounded_rectangle(
        [x0 + offset[0], y0 + offset[1], x1 + offset[0], y1 + offset[1]],
        radius=radius, fill=(0, 0, 0, alpha),
    )
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    return Image.alpha_composite(canvas, layer)


def wrap(text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for word in words:
        test = f"{cur} {word}".strip()
        if _scratch.textlength(test, font=f) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit_text(text, key, weight, max_w, max_h, start, minimum=28, max_lines=4, spacing=1.12):
    size = start
    while True:
        f = font(key, size, weight)
        lines = wrap(text, f, max_w)
        lh = int(size * spacing)
        ok = (
            len(lines) <= max_lines
            and lh * len(lines) <= max_h
            and all(_scratch.textlength(l, font=f) <= max_w for l in lines)
        )
        if ok or size <= minimum:
            return f, lines, lh
        size -= 4


def layout_text(title, subtitle, max_w, key="sans", weight="ExtraBold",
                start=90, max_h=380, max_lines=4, upper=True, sub_size=34):
    t = (title or "").strip()
    if upper:
        t = t.upper()
    if t:
        tf, tl, tlh = fit_text(t, key, weight, max_w, max_h, start, max_lines=max_lines)
    else:
        tf, tl, tlh = None, [], 0

    s = (subtitle or "").strip()
    sf = font("sans", sub_size, "Medium")
    sl = wrap(s, sf, max_w)[:2] if s else []
    slh = int(sub_size * 1.3)
    gap = 24 if (tl and sl) else 0
    h = tlh * len(tl) + gap + slh * len(sl)
    return dict(tf=tf, tl=tl, tlh=tlh, sf=sf, sl=sl, slh=slh, gap=gap, h=h)


def render_text(draw, L, cx, top, tcolor, scolor):
    y = top
    for line in L["tl"]:
        draw.text((cx, y + L["tlh"] / 2), line, font=L["tf"], fill=tcolor, anchor="mm")
        y += L["tlh"]
    y += L["gap"]
    for line in L["sl"]:
        draw.text((cx, y + L["slh"] / 2), line, font=L["sf"], fill=scolor, anchor="mm")
        y += L["slh"]


def draw_footer(canvas, footer, P, y=H - 62):
    t = (footer or "").strip()
    if not t:
        return
    f = font("sans", 26, "SemiBold")
    d = ImageDraw.Draw(canvas)
    tw = d.textlength(t, font=f)
    pw, ph = tw + 56, 50
    x0, y0 = (W - pw) / 2, y - ph / 2
    d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=25, fill=P["accent"])
    d.text((W / 2, y), t, font=f, fill=P["on_accent"], anchor="mm")


# ---------------- Templates ----------------
def _banner(c, title, subtitle, footer, P, radius=16):
    bw, pad = W - 120, 56
    L = layout_text(title, subtitle, bw - 2 * pad, start=92, max_h=420)
    bh = L["h"] + 2 * pad
    x0, y0 = (W - bw) // 2, (H - bh) // 2
    c = add_shadow(c, (x0, y0, x0 + bw, y0 + bh), radius)
    d = ImageDraw.Draw(c)
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=radius, fill=P["card"])
    d.rectangle([W // 2 - 40, y0 + pad // 2 - 3, W // 2 + 40, y0 + pad // 2 + 3], fill=P["accent"])
    render_text(d, L, W / 2, y0 + pad, P["text"], P["accent"])
    draw_footer(c, footer, P)
    return c


def t_banner_center(imgs, title, subtitle, footer, P):
    c = cover(imgs[0], W, H).convert("RGBA")
    return _banner(c, title, subtitle, footer, P)


def t_split_banner(imgs, title, subtitle, footer, P):
    c = Image.new("RGBA", (W, H), P["card"])
    half = H // 2
    c.paste(cover(imgs[0], W, half - 4).convert("RGBA"), (0, 0))
    c.paste(cover(imgs[1], W, H - half - 4).convert("RGBA"), (0, half + 4))
    return _banner(c, title, subtitle, footer, P, radius=0)


def t_top_title(imgs, title, subtitle, footer, P):
    c = Image.new("RGBA", (W, H), P["bg"])
    block_h, pad = 540, 70
    L = layout_text(title, subtitle, W - 2 * pad, key="serif", weight="Bold",
                    start=100, max_h=block_h - 2 * pad - 60, upper=False)
    d = ImageDraw.Draw(c)
    render_text(d, L, W / 2, (block_h - L["h"]) // 2, P["text"], P["accent"])
    paste_rounded(c, imgs[0], (40, block_h, W - 40, H - 40), 28)
    draw_footer(c, footer, P, y=H - 90)
    return c


def t_overlay_bottom(imgs, title, subtitle, footer, P):
    c = cover(imgs[0], W, H).convert("RGBA")
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(grad)
    start = int(H * 0.45)
    for y in range(start, H):
        a = int(215 * ((y - start) / (H - start)) ** 0.9)
        g.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    c = Image.alpha_composite(c, grad)
    pad = 70
    L = layout_text(title, subtitle, W - 2 * pad, start=96, max_h=420)
    bottom = H - (150 if (footer or "").strip() else 90)
    d = ImageDraw.Draw(c)
    render_text(d, L, W / 2, bottom - L["h"], (255, 255, 255), (240, 228, 210))
    draw_footer(c, footer, P)
    return c


def t_frame_card(imgs, title, subtitle, footer, P):
    c = Image.new("RGBA", (W, H), P["bg"])
    m, img_h = 50, 980
    paste_rounded(c, imgs[0], (m, m, W - m, m + img_h), 30)
    card_top = m + img_h - 90
    cw, pad = W - 2 * m - 60, 48
    has_footer = bool((footer or "").strip())
    L = layout_text(title, subtitle, cw - 2 * pad, key="serif", weight="Bold",
                    start=78, max_h=H - card_top - 2 * pad - (190 if has_footer else 130),
                    upper=False, sub_size=30)
    ch = L["h"] + 2 * pad
    x0 = (W - cw) // 2
    c = add_shadow(c, (x0, card_top, x0 + cw, card_top + ch), 24)
    d = ImageDraw.Draw(c)
    d.rounded_rectangle([x0, card_top, x0 + cw, card_top + ch], radius=24, fill=P["card"])
    render_text(d, L, W / 2, card_top + pad, P["text"], P["accent"])
    draw_footer(c, footer, P)
    return c


BLOG_COLORS = [(214, 30, 38), (150, 60, 190), (30, 140, 70), (230, 110, 20), (20, 110, 190), (205, 40, 120)]


def draw_search_pill(d, cx, cy, text, color, f):
    tw = d.textlength(text, font=f)
    icon = int(f.size * 0.9)
    pw, ph = tw + icon + 58, int(f.size * 1.75)
    x0, y0 = cx - pw / 2, cy - ph / 2
    d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=8, fill=color)
    # search icon
    ix, iy, r = x0 + 22 + icon / 2 - 4, cy - 3, icon / 2 - 5
    d.ellipse([ix - r, iy - r, ix + r, iy + r], outline="white", width=4)
    d.line([ix + r * 0.7, iy + r * 0.7, ix + r * 1.6, iy + r * 1.6], fill="white", width=5)
    d.text((x0 + 22 + icon + 12, cy), text, font=f, fill="white", anchor="lm")


def draw_badge(c, text, color):
    words = (text or "").split()
    if not words:
        return
    d = ImageDraw.Draw(c)
    top = words[0]
    rest = " ".join(words[1:])
    # triangle (tree) behind the badge
    bx, by = 40, H - 60
    d.polygon([(bx + 20, by), (bx + 170, by - 260), (bx + 320, by)], fill=(30, 140, 70))
    f1 = font("display", 72)
    f2 = font("display", 84)
    for txt, ff, y in ((top, f1, by - 150), (rest, f2, by - 60)):
        if txt:
            d.text((bx + 170, y), txt, font=ff, fill=color, anchor="mm",
                   stroke_width=6, stroke_fill="white")


def t_blog_style(imgs, title, subtitle, footer, P):
    bg = (220, 230, 240)
    color = random.choice(BLOG_COLORS)
    c = Image.new("RGBA", (W, H), bg)
    c.paste(cover(imgs[0], W, H - 330).convert("RGBA"), (0, 330))

    # soft fade between header and photo
    fade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fade)
    for i in range(90):
        fd.line([(0, 330 + i), (W, 330 + i)], fill=bg + (int(255 * (1 - i / 90)),))
    c = Image.alpha_composite(c, fade)

    d = ImageDraw.Draw(c)
    t = (title or "").strip()
    has_url = bool((footer or "").strip())
    if t:
        tf, lines, lh = fit_text(t, "display", "Regular", W - 80,
                                 250 if has_url else 300, 150, max_lines=2, spacing=1.0)
        y = 30
        for line in lines:
            d.text((W / 2, y + lh / 2), line, font=tf, fill=color, anchor="mm",
                   stroke_width=5, stroke_fill="white")
            y += lh
    else:
        y = 30
    if has_url:
        draw_search_pill(d, W / 2, y + 45, footer.strip(), color, font("sans", 30, "SemiBold"))

    draw_badge(c, subtitle, color)
    return c


BANNER_COLORS = [
    (92, 28, 110),    # purple
    (46, 110, 190),   # blue
    (20, 40, 90),     # navy
    (228, 164, 24),   # amber
    (168, 96, 112),   # mauve
    (40, 120, 90),    # green
]


def t_collage_pill(imgs, title, subtitle, footer, P):
    """1 big photo on top + 2 photos bottom + rounded colored banner in the middle."""
    gap = 8
    c = Image.new("RGBA", (W, H), (255, 255, 255))
    top_h = int(H * 0.56)
    c.paste(cover(imgs[0], W, top_h).convert("RGBA"), (0, 0))
    bw = (W - gap) // 2
    bh = H - top_h - gap
    c.paste(cover(imgs[1], bw, bh).convert("RGBA"), (0, top_h + gap))
    c.paste(cover(imgs[2], W - bw - gap, bh).convert("RGBA"), (bw + gap, top_h + gap))

    color = random.choice(BANNER_COLORS)
    box_w, pad_x, pad_y = W - 110, 50, 34
    t = (title or "").strip()
    tf, tl, tlh = fit_text(t, "sans", "Bold", box_w - 2 * pad_x, 260, 64,
                           max_lines=3, spacing=1.12) if t else (None, [], 0)
    s = (subtitle or "").strip()
    sf = font("sans", 30, "SemiBold")
    sh = 44 if s else 0
    box_h = tlh * len(tl) + sh + 2 * pad_y
    x0, y0 = (W - box_w) // 2, top_h - box_h // 2 - 40
    c = add_shadow(c, (x0, y0, x0 + box_w, y0 + box_h), radius=box_h // 3, alpha=70)
    d = ImageDraw.Draw(c)
    d.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=min(70, box_h // 3), fill=color)
    y = y0 + pad_y
    for line in tl:
        d.text((W / 2, y + tlh / 2), line, font=tf, fill="white", anchor="mm")
        y += tlh
    if s:
        d.text((W / 2, y + sh / 2), s, font=sf, fill=(255, 255, 255, 230), anchor="mm")
    draw_footer(c, footer, P)
    return c


def t_color_band(imgs, title, subtitle, footer, P):
    """Photo top + full-width colored band with big rounded title + photo bottom."""
    color = random.choice(BANNER_COLORS)
    t = (title or "").strip().upper()
    tf, tl, tlh = fit_text(t, "round", "Regular", W - 100, 330, 110,
                           max_lines=3, spacing=1.0) if t else (None, [], 0)
    s = (subtitle or "").strip()
    sf = font("sans", 32, "SemiBold")
    sh = 50 if s else 0
    band_h = tlh * len(tl) + sh + 70
    band_y = int(H * 0.47) - band_h // 2

    c = Image.new("RGBA", (W, H), color)
    c.paste(cover(imgs[0], W, band_y).convert("RGBA"), (0, 0))
    bottom_y = band_y + band_h
    c.paste(cover(imgs[1], W, H - bottom_y).convert("RGBA"), (0, bottom_y))

    d = ImageDraw.Draw(c)
    y = band_y + 35
    for line in tl:
        d.text((W / 2, y + tlh / 2), line, font=tf, fill="white", anchor="mm",
               stroke_width=3, stroke_fill=tuple(max(0, v - 60) for v in color))
        y += tlh
    if s:
        d.text((W / 2, y + sh / 2), s, font=sf, fill="white", anchor="mm")
    draw_footer(c, footer, P)
    return c


TEMPLATES = {
    "banner_center": (t_banner_center, 1),
    "split_banner": (t_split_banner, 2),
    "top_title": (t_top_title, 1),
    "overlay_bottom": (t_overlay_bottom, 1),
    "frame_card": (t_frame_card, 1),
    "blog_style": (t_blog_style, 1),
    "collage_pill": (t_collage_pill, 3),
    "color_band": (t_color_band, 2),
}


# ---------------- Main ----------------
def fetch_image(url):
    r = httpx.get(url, follow_redirects=True, timeout=30,
                  headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    img = Image.open(BytesIO(r.content))
    img.load()
    return img.convert("RGB")


def make_pin(scene, title, subtitle, footer, template, palette, image_url, seed, style="crochet"):
    try:
        seed = int(seed)
    except Exception:
        seed = -1
    if seed < 0:
        seed = random.randint(0, 2**31 - 1)

    if not template or template == "random":
        template = random.choice(list(TEMPLATES))
    if not palette or palette == "random":
        palette = random.choice(list(PALETTES))
    if template not in TEMPLATES:
        raise PinError(f"Template ghalet: {template}")
    if palette not in PALETTES:
        raise PinError(f"Palette ghalta: {palette}")

    fn, needed = TEMPLATES[template]
    P = PALETTES[palette]

    # 1) tswar mn URLs (ila kaynin) - separator: |
    imgs = []
    for u in [u.strip() for u in (image_url or "").split("|") if u.strip()][:needed]:
        try:
            imgs.append(fetch_image(u))
        except Exception as e:
            raise PinError(f"Ma9dertch njib tswira mn URL: {e}")

    # 2) l'b9iya b FLUX - 2 scenes separator: ||
    if len(imgs) < needed:
        scenes = [s.strip() for s in (scene or "").split("||") if s.strip()]
        if not scenes:
            raise PinError("Kteb scene wla 7et image_url")
        prompts = [scenes[min(i, len(scenes) - 1)] for i in range(len(imgs), needed)]
        imgs += cf_generate(prompts, seed, style or "photo")

    pin = fn(imgs, title, subtitle, footer, P).convert("RGB")
    out_path = f"/tmp/pin_{template}_{seed}.png"
    pin.save(out_path, "PNG", optimize=True)

    return out_path, {"template": template, "palette": palette, "style": style, "seed": seed}




# ---------------- HTTP server ----------------
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_KEY = os.environ.get("PIN_API_KEY", "").strip()

FORM_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Pin Studio</title>
<style>body{font-family:system-ui;background:#111;color:#eee;margin:0;padding:16px}
.w{max-width:1000px;margin:auto;display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media(max-width:700px){.w{grid-template-columns:1fr}}
label{display:block;margin:10px 0 4px;font-size:14px;color:#aaa}
input,select,textarea{width:100%;box-sizing:border-box;padding:10px;background:#222;color:#eee;border:1px solid #333;border-radius:8px}
button{margin-top:14px;width:100%;padding:12px;background:#e8590c;color:#fff;border:0;border-radius:8px;font-size:16px;cursor:pointer}
img{width:100%;border-radius:8px}#err{color:#ff6b6b}</style></head><body>
<h2>📌 Pin Studio</h2><div class="w"><div>
<label>API key (ila dertiha)</label><input id="key">
<label>Scene</label><textarea id="scene" rows="3">A purple and white crochet pansy flower with a yellow center</textarea>
<label>Title</label><input id="title" value="Whimsical Crochet Pansy Flowers">
<label>Subtitle</label><input id="subtitle" value="Free Pattern">
<label>Footer</label><input id="footer" value="">
<label>Template</label><select id="template"><option>random</option>TEMPLATE_OPTIONS</select>
<label>Style</label><select id="style">STYLE_OPTIONS</select>
<button onclick="go()">Generate</button><p id="err"></p></div>
<div><img id="out"></div></div>
<script>
async function go(){const $=i=>document.getElementById(i);$('err').textContent='Generating...';
const b={};['scene','title','subtitle','footer','template','style'].forEach(k=>b[k]=$(k).value);
const r=await fetch('/pin',{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':$('key').value},body:JSON.stringify(b)});
if(!r.ok){$('err').textContent=(await r.text());return}
$('out').src=URL.createObjectURL(await r.blob());$('err').textContent='';}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._send(200, '{"ok": true}')
        if self.path == "/" or self.path.startswith("/?"):
            html = FORM_HTML.replace(
                "TEMPLATE_OPTIONS", "".join(f"<option>{t}</option>" for t in TEMPLATES)
            ).replace(
                "STYLE_OPTIONS", "".join(f"<option>{s}</option>" for s in STYLE_PRESETS)
            )
            return self._send(200, html, "text/html; charset=utf-8")
        return self._send(404, '{"error": "not found"}')

    def do_POST(self):
        if not self.path.startswith("/pin"):
            return self._send(404, '{"error": "not found"}')
        if API_KEY and self.headers.get("X-API-Key", "") != API_KEY:
            return self._send(401, '{"error": "bad api key"}')
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(n) or b"{}")
            path, info = make_pin(
                req.get("scene", ""), req.get("title", ""), req.get("subtitle", ""),
                req.get("footer", ""), req.get("template", "random"), req.get("palette", "random"),
                req.get("image_url", ""), req.get("seed", -1), req.get("style", "crochet"),
            )
            with open(path, "rb") as f:
                data = f.read()
            return self._send(200, data, "image/png", {"X-Pin-Info": json.dumps(info)})
        except PinError as e:
            return self._send(400, json.dumps({"error": str(e)}))
        except Exception as e:
            print("ERROR:", repr(e))
            return self._send(500, json.dumps({"error": repr(e)}))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print(f"Pin Studio listening on :{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
