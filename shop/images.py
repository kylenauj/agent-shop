"""Stage 3: make the artwork and turn it into a print-ready file."""

import base64
import io
import os
import textwrap

from PIL import Image, ImageDraw, ImageFont

from shop.store import Design

# Colors for the typography backend, picked to read well on light shirts.
PALETTES = [
    ("#3E4A3D", "#C46A4A"),  # forest + terracotta
    ("#2F3E5C", "#C98B9B"),  # navy + dusty rose
    ("#5B3A29", "#D9A441"),  # brown + mustard
    ("#4A3B5C", "#8FAF9A"),  # plum + sage
]


def pick_backend(config: dict, has_openai: bool) -> str:
    backend = config["images"].get("backend", "auto")
    if backend == "auto":
        return "openai" if has_openai else "typography"
    return backend


def generate(design: Design, config: dict, backend: str) -> None:
    if backend == "openai":
        art = openai_art(design.concept.image_prompt, config)
    elif backend == "typography":
        art = typography_art(design, config)
    else:
        raise ValueError(f"Unknown image backend: {backend}")

    final = fit_to_print(art, config["images"]["print_width"], config["images"]["print_height"])
    final.save(design.image_path, optimize=True)
    preview = final.copy()
    preview.thumbnail((600, 720))
    preview.save(design.preview_path)


def openai_art(prompt: str, config: dict) -> Image.Image:
    from openai import OpenAI

    result = OpenAI().images.generate(
        model=config["images"].get("openai_model", "gpt-image-1"),
        prompt=prompt,
        size="1024x1536",
        background="transparent",
        quality=config["images"].get("openai_quality", "high"),
        output_format="png",
        n=1,
    )
    return Image.open(io.BytesIO(base64.b64decode(result.data[0].b64_json))).convert("RGBA")


def typography_art(design: Design, config: dict) -> Image.Image:
    """Clean lettering-only design. Free, fast, and the spelling is always right."""
    slogan = design.concept.slogan or design.concept.niche
    width, height = 1500, 1800
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    main_color, accent = PALETTES[sum(map(ord, design.id)) % len(PALETTES)]

    lines = textwrap.wrap(slogan.upper(), width=12) or [slogan.upper()]
    size = 260
    while size > 60:
        font = load_font(config, size)
        boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
        if max(b[2] - b[0] for b in boxes) <= width * 0.9:
            break
        size -= 10

    line_height = int(size * 1.15)
    block_height = line_height * len(lines)
    y = (height - block_height) // 2
    for i, line in enumerate(lines):
        box = draw.textbbox((0, 0), line, font=font)
        x = (width - (box[2] - box[0])) // 2 - box[0]
        draw.text((x, y), line, font=font, fill=accent if i % 2 else main_color)
        y += line_height

    # Simple accent rules above and below the text.
    pad = 60
    top = (height - block_height) // 2 - pad
    bottom = (height + block_height) // 2 + pad // 2
    for rule_y in (top, bottom):
        draw.rounded_rectangle(
            (width * 0.3, rule_y, width * 0.7, rule_y + 14), radius=7, fill=accent
        )
    return image.crop(image.getbbox())


def load_font(config: dict, size: int) -> ImageFont.FreeTypeFont:
    font_path = config["images"].get("font_path")
    if font_path and os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ):
        if os.path.exists(candidate):
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


def fit_to_print(art: Image.Image, width: int, height: int) -> Image.Image:
    """Center the art on a transparent canvas at the printer's size.

    AI images come out around 1024x1536, so this enlarges them. That's fine for
    flat, bold designs; for detailed art, run an AI upscaler first.
    """
    art = art.convert("RGBA")
    bbox = art.getbbox()
    if bbox:
        art = art.crop(bbox)
    margin = 0.92
    scale = min(width * margin / art.width, height * margin / art.height)
    art = art.resize((max(1, int(art.width * scale)), max(1, int(art.height * scale))), Image.LANCZOS)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.paste(art, ((width - art.width) // 2, (height - art.height) // 2), art)
    return canvas
