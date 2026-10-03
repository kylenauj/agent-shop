"""Stage 2: reject ideas likely to get the shop a trademark or IP strike.

Two layers: a fast blocklist from config, then a Claude review that catches
the things a word list misses (famous phrases, character references, lyrics).
"""

import re

from shop.claude import ask_json
from shop.store import Concept

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["risk", "issues"],
    "additionalProperties": False,
}

REVIEW_PROMPT = """You check Etsy print-on-demand listings for intellectual property and
policy risk before they go live. Be strict: a single takedown can get a new shop suspended.

Rate risk "high" if the slogan, image prompt, title, or tags contain or clearly refer to:
a brand or company name, a trademarked phrase, a sports team or league, a character,
a movie / TV show / book / game / song title, song lyrics, a celebrity or public figure,
or anything hateful, sexual, or medical-claim related.
Rate "medium" for phrases that might be trademarked for apparel (many common catchphrases
are registered) or close imitations of famous designs.
Rate "low" only for original, generic content.

List each concrete issue you found. Return an empty list if there are none."""


def blocklist_hits(concept: Concept, blocked_terms: list[str]) -> list[str]:
    text = " ".join(
        [concept.slogan, concept.image_prompt, concept.title, concept.description, *concept.tags]
    ).lower()
    return [
        term for term in blocked_terms
        if re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", text)
    ]


def review(concept: Concept, config: dict, use_claude: bool) -> tuple[bool, str]:
    """Returns (passed, reason)."""
    hits = blocklist_hits(concept, config.get("blocked_terms", []))
    if hits:
        return False, "blocked terms: " + ", ".join(hits)
    if not use_claude:
        return True, "blocklist only (no Claude key)"

    listing = (
        f"Slogan: {concept.slogan!r}\nImage prompt: {concept.image_prompt}\n"
        f"Title: {concept.title}\nTags: {', '.join(concept.tags)}\n"
        f"Description: {concept.description}"
    )
    result = ask_json(
        model=config["claude"]["model"],
        system=REVIEW_PROMPT,
        content=listing,
        schema=REVIEW_SCHEMA,
        effort="medium",
        max_tokens=4000,
    )
    reason = f"risk {result['risk']}" + (": " + "; ".join(result["issues"]) if result["issues"] else "")
    return result["risk"] == "low", reason
