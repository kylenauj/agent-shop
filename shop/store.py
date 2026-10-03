"""Design records on disk.

Each design lives in data/designs/<id>/ with:
  design.json  - the idea, listing copy, status, and history
  design.png   - the print-ready file
  preview.png  - a small copy for quick review
"""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from shop.config import DATA_DIR

ETSY_TITLE_MAX = 140
ETSY_TAG_MAX_COUNT = 13
ETSY_TAG_MAX_LEN = 20

# ideated -> designed -> pending_review -> approved -> published
#        \-> rejected (policy check, image QA, or by you)
STATUSES = ["ideated", "designed", "pending_review", "approved", "published", "rejected", "failed"]


class Concept(BaseModel):
    niche: str
    slogan: str = Field(description="Exact text printed on the item. Empty string for no text.")
    design_style: str
    image_prompt: str
    products: list[str]
    title: str
    description: str
    tags: list[str]
    why_it_sells: str


class Design(BaseModel):
    id: str
    created_at: str
    status: str = "ideated"
    concept: Concept
    notes: list[str] = []
    printify_product_ids: dict[str, str] = {}
    published_products: list[str] = []

    @property
    def folder(self) -> Path:
        return designs_dir() / self.id

    @property
    def image_path(self) -> Path:
        return self.folder / "design.png"

    @property
    def preview_path(self) -> Path:
        return self.folder / "preview.png"

    def note(self, message: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        self.notes.append(f"[{stamp}] {message}")

    def set_status(self, status: str, reason: str = "") -> None:
        assert status in STATUSES, status
        self.status = status
        self.note(f"{status}" + (f": {reason}" if reason else ""))

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "design.json").write_text(self.model_dump_json(indent=2))


def designs_dir() -> Path:
    return DATA_DIR / "designs"


def new_design(concept: Concept) -> Design:
    slug = re.sub(r"[^a-z0-9]+", "-", (concept.slogan or concept.niche).lower()).strip("-")[:40]
    design = Design(
        id=f"{datetime.now(timezone.utc).strftime('%Y%m%d')}-{slug or 'design'}-{uuid.uuid4().hex[:6]}",
        created_at=datetime.now(timezone.utc).isoformat(),
        concept=clean_concept(concept),
    )
    design.note("ideated")
    design.save()
    return design


def load_design(design_id: str) -> Design:
    path = designs_dir() / design_id / "design.json"
    if not path.exists():
        # Allow a unique prefix so you don't have to type the full id.
        matches = [p for p in designs_dir().glob(f"{design_id}*") if p.is_dir()]
        if len(matches) != 1:
            raise SystemExit(f"No single design matches '{design_id}'")
        path = matches[0] / "design.json"
    return Design.model_validate_json(path.read_text())


def all_designs(status: str | None = None) -> list[Design]:
    if not designs_dir().exists():
        return []
    designs = [
        Design.model_validate_json(p.read_text())
        for p in sorted(designs_dir().glob("*/design.json"))
    ]
    return [d for d in designs if status is None or d.status == status]


def clean_concept(concept: Concept) -> Concept:
    """Enforce Etsy's listing limits so publishing never fails on them."""
    title = " ".join(concept.title.split())
    if len(title) > ETSY_TITLE_MAX:
        title = title[:ETSY_TITLE_MAX].rsplit(" ", 1)[0]

    tags: list[str] = []
    for tag in concept.tags:
        tag = " ".join(re.sub(r"[^A-Za-z0-9 '\-]", "", tag).split()).lower()
        if tag and len(tag) <= ETSY_TAG_MAX_LEN and tag not in tags:
            tags.append(tag)
    return concept.model_copy(update={"title": title, "tags": tags[:ETSY_TAG_MAX_COUNT]})


def existing_slogans() -> list[str]:
    return [d.concept.slogan for d in all_designs() if d.concept.slogan]


def dump_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2))
