"""Stage 1: research trends and come up with design ideas plus listing copy."""

from shop.claude import ask_json
from shop.store import Concept


def concept_schema(product_names: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "concepts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "niche": {"type": "string"},
                        "slogan": {"type": "string"},
                        "design_style": {"type": "string"},
                        "image_prompt": {"type": "string"},
                        "products": {
                            "type": "array",
                            "items": {"type": "string", "enum": product_names},
                        },
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "why_it_sells": {"type": "string"},
                    },
                    "required": [
                        "niche", "slogan", "design_style", "image_prompt", "products",
                        "title", "description", "tags", "why_it_sells",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["concepts"],
        "additionalProperties": False,
    }


SYSTEM_PROMPT = """You are the product designer for a print-on-demand Etsy shop.
You come up with designs that sell, and you write the Etsy listing for each one.

Who the shop sells to:
{audience}

Design style:
{style}

What makes a design work here:
- One clear idea a customer gets in two seconds. Short slogans (2 to 8 words) beat long ones.
- Gift appeal: the buyer is often shopping for a friend, a mom, a grandma, or a coworker.
- It prints well: bold shapes, a few flat colors, readable from across a room, on a
  transparent background, with nothing touching the edges.

Things that get Etsy shops shut down, which you must never do:
- Brands, trademarks, sports teams, or company names, including in tags.
- Characters, movies, TV shows, books, songs, lyrics, or celebrities, even as a reference.
- Famous trademarked phrases. If you are not sure whether a phrase is trademarked, skip it.

For each idea, write:
- slogan: the exact words to print, spelled correctly. Use "" for a design with no text.
- image_prompt: a full prompt for an image generator. Say "isolated on a transparent
  background", name the style and colors, and if there is text, quote it exactly and
  say it must be spelled exactly like that.
- products: which of these it suits: {products}.
- title: an Etsy title under 140 characters. Lead with what a buyer would search for,
  e.g. "Funny Gardening Shirt for Women, Plant Lady Gift, ...".
- description: 3 short paragraphs. What it is, who it's a great gift for, and a line
  inviting them to pick their size and color. Don't list sizes, materials, or care
  instructions; those come from the product page.
- tags: exactly 13 Etsy tags, each 20 characters or fewer, phrases buyers type in.
- why_it_sells: one or two sentences."""


def generate_concepts(config: dict, count: int, avoid: list[str]) -> list[Concept]:
    shop = config["shop"]
    product_names = list(config["products"].keys())
    niches = shop.get("niches") or []

    request = [f"Come up with {count} new, different design ideas."]
    if niches:
        request.append("Spread them across these niches: " + ", ".join(niches) + ".")
    if config["pipeline"].get("research_with_web", True):
        request.append(
            "First search the web for what is selling and trending right now for this "
            "audience: upcoming holidays and seasons, gift occasions, and popular phrases. "
            "Use what you find."
        )
    if avoid:
        request.append(
            "The shop already has these slogans, so don't repeat them or make close copies:\n"
            + "\n".join(f"- {s}" for s in avoid[-200:])
        )

    result = ask_json(
        model=config["claude"]["model"],
        system=SYSTEM_PROMPT.format(
            audience=shop["audience"].strip(),
            style=shop["style"].strip(),
            products=", ".join(product_names),
        ),
        content="\n\n".join(request),
        schema=concept_schema(product_names),
        effort="high",
        web_search=config["pipeline"].get("research_with_web", True),
    )
    return [Concept(**c) for c in result["concepts"]][:count]


# Used when no Claude key is set, so you can try the whole pipeline for free.
SAMPLE_CONCEPTS = [
    Concept(
        niche="gardening",
        slogan="Plant Lady Era",
        design_style="retro groovy lettering with a small potted monstera, sage and terracotta",
        image_prompt=(
            'Retro 70s groovy lettering that says exactly "Plant Lady Era" above a small '
            "potted monstera, sage green and terracotta, flat vector style, isolated on a "
            "transparent background"
        ),
        products=["tee", "sweatshirt", "tote"],
        title="Plant Lady Era Shirt, Funny Gardening Gift for Women, Retro Plant Mom Tee",
        description=(
            "Show off your green thumb with this retro Plant Lady Era design.\n\n"
            "A great gift for the gardener, plant mom, or houseplant collector in your life.\n\n"
            "Pick your size and color to get started."
        ),
        tags=[
            "plant lady shirt", "gardening gift", "plant mom", "retro plant shirt",
            "gardener gift", "houseplant lover", "plant lady era", "gift for her",
            "garden shirt women", "boho plant tee", "monstera shirt", "mom gift",
            "plant lover gift",
        ],
        why_it_sells="Plant-mom identity plus the popular 'era' phrasing; strong gift appeal.",
    ),
    Concept(
        niche="book club",
        slogan="Just One More Chapter",
        design_style="hand-lettered script over a small stack of books, dusty rose and navy",
        image_prompt=(
            'Hand-lettered script text that says exactly "Just One More Chapter" over a '
            "small stack of books with a coffee cup, dusty rose and navy, flat illustration, "
            "isolated on a transparent background"
        ),
        products=["tee", "mug", "tote"],
        title="Just One More Chapter Shirt, Book Lover Gift for Women, Reading Tee",
        description=(
            "For the reader who always says one more chapter at midnight.\n\n"
            "A thoughtful gift for book club friends, librarians, and anyone who loves to read.\n\n"
            "Choose your size and color to make it yours."
        ),
        tags=[
            "book lover gift", "reading shirt", "book club gift", "bookish shirt",
            "librarian gift", "one more chapter", "book lover shirt", "gift for reader",
            "bookworm gift", "teacher gift", "reading tote", "gift for her", "book mug",
        ],
        why_it_sells="Readers buy bookish merch for themselves and as easy friend gifts.",
    ),
]
