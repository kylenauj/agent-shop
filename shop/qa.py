"""Stage 4: Claude looks at the finished artwork before anyone else does.

Image generators often misspell words or leave a background behind. Both
lead to returns and bad reviews, so they're caught here.
"""

import base64
import io

from PIL import Image

from shop.claude import ask_json
from shop.store import Design

QA_SCHEMA = {
    "type": "object",
    "properties": {
        "text_seen": {"type": "string"},
        "text_matches": {"type": "boolean"},
        "print_ready": {"type": "boolean"},
        "problems": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["text_seen", "text_matches", "print_ready", "problems"],
    "additionalProperties": False,
}

QA_PROMPT = """You inspect artwork before it is printed on shirts, mugs, and totes.
The image is shown on a checkerboard so you can see which parts are transparent.

Check:
1. text_seen: transcribe every word in the artwork exactly as drawn, including mistakes.
2. text_matches: true only if the words match the intended text exactly (ignore letter case).
   If the intended text is empty, true only if there is no text.
3. print_ready: false if any of these are true: a solid or partial background box behind
   the art, art cut off at the edges, garbled or extra letters, blurry or muddy areas,
   a watermark or signature, or anything a customer would see as a defect.
4. problems: each problem you found, or an empty list."""


def checkerboard_preview(path, size: int = 1024) -> str:
    art = Image.open(path).convert("RGBA")
    art.thumbnail((size, size))
    board = Image.new("RGBA", art.size, "white")
    tile = 32
    for y in range(0, art.height, tile):
        for x in range(0, art.width, tile):
            if (x // tile + y // tile) % 2:
                board.paste((220, 220, 220, 255), (x, y, x + tile, y + tile))
    board.alpha_composite(art)
    buffer = io.BytesIO()
    board.convert("RGB").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def inspect(design: Design, config: dict) -> tuple[bool, str]:
    result = ask_json(
        model=config["claude"]["model"],
        system=QA_PROMPT,
        content=[
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": checkerboard_preview(design.image_path),
                },
            },
            {"type": "text", "text": f"Intended text: {design.concept.slogan!r}"},
        ],
        schema=QA_SCHEMA,
        effort="medium",
        max_tokens=4000,
    )
    passed = result["text_matches"] and result["print_ready"]
    detail = f"saw {result['text_seen']!r}"
    if result["problems"]:
        detail += "; " + "; ".join(result["problems"])
    return passed, detail
