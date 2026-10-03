"""Offline tests. Claude and Printify are faked, so these need no keys."""

import json
from types import SimpleNamespace

import pytest
from PIL import Image

import shop.claude
import shop.printify
import shop.store
from shop import compliance, pipeline
from shop.config import load_config
from shop.ideate import SAMPLE_CONCEPTS
from shop.printify import Printify, PrintifyError, publish_design
from shop.store import Concept, clean_concept, new_design


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(shop.store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(shop.printify, "DATA_DIR", tmp_path)
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "PRINTIFY_API_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    cfg = load_config()
    cfg["images"]["print_width"], cfg["images"]["print_height"] = 450, 540  # keep tests fast
    return cfg


def test_clean_concept_enforces_etsy_limits():
    concept = SAMPLE_CONCEPTS[0].model_copy(update={
        "title": "word " * 50,
        "tags": ["Good Tag", "good tag", "this tag is far too long", "emoji 🌿 tag"] + [f"t{i}" for i in range(20)],
    })
    cleaned = clean_concept(concept)
    assert len(cleaned.title) <= 140
    assert cleaned.tags[:2] == ["good tag", "emoji tag"]
    assert len(cleaned.tags) == 13
    assert all(len(t) <= 20 for t in cleaned.tags)


def test_blocklist_matches_whole_words_only():
    terms = ["stanley", "nfl"]
    risky = SAMPLE_CONCEPTS[0].model_copy(update={"slogan": "Stanley Cup Girlie"})
    safe = SAMPLE_CONCEPTS[0].model_copy(update={"slogan": "Stand Up Gardener"})
    assert compliance.blocklist_hits(risky, terms) == ["stanley"]
    assert compliance.blocklist_hits(safe, terms) == []


def test_offline_run_queues_designs_for_review(config):
    modes = pipeline.Modes(config, offline=True)
    designs = pipeline.run(config, 2, modes, log=lambda *_: None)
    assert [d.status for d in designs] == ["pending_review", "pending_review"]
    image = Image.open(designs[0].image_path)
    assert image.size == (450, 540) and image.mode == "RGBA"
    assert image.getpixel((0, 0))[3] == 0  # transparent background


def test_blocked_idea_is_rejected_before_artwork(config):
    config["blocked_terms"] = ["plant lady"]
    designs = pipeline.run(config, 1, pipeline.Modes(config, offline=True), log=lambda *_: None)
    assert designs[0].status == "rejected"
    assert not designs[0].image_path.exists()


# --- Claude wrapper ---------------------------------------------------------

def fake_response(stop_reason, text=None, category=None):
    content = [SimpleNamespace(type="text", text=text)] if text is not None else []
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content,
        stop_details=SimpleNamespace(category=category) if category else None,
    )


class FakeClaude:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs, default=str)))
        return self.responses.pop(0)


def ask(monkeypatch, responses, **kwargs):
    fake = FakeClaude(responses)
    monkeypatch.setattr(shop.claude, "_client", fake)
    result = shop.claude.ask_json(model="m", system="s", content="c", schema={}, **kwargs)
    return result, fake


def test_ask_json_resumes_paused_turns(monkeypatch):
    result, fake = ask(
        monkeypatch,
        [fake_response("pause_turn", "searching"), fake_response("end_turn", '{"ok": true}')],
        web_search=True,
    )
    assert result == {"ok": True}
    assert len(fake.calls) == 2
    assert fake.calls[1]["messages"][-1]["role"] == "assistant"
    assert fake.calls[0]["fallbacks"] == "default"
    assert fake.calls[0]["tools"][0]["type"] == "web_search_20260209"


def test_ask_json_reports_refusals(monkeypatch):
    with pytest.raises(shop.claude.ClaudeError, match="declined"):
        ask(monkeypatch, [fake_response("refusal", category="cyber")])


def test_live_pipeline_with_fake_claude(config, monkeypatch):
    concept = SAMPLE_CONCEPTS[1].model_dump()
    responses = [
        fake_response("end_turn", json.dumps({"concepts": [concept]})),               # ideas
        fake_response("end_turn", json.dumps({"risk": "low", "issues": []})),         # policy
        fake_response("end_turn", json.dumps({                                        # image QA
            "text_seen": "JUST ONE MORE CHAPTER", "text_matches": True,
            "print_ready": True, "problems": [],
        })),
    ]
    monkeypatch.setattr(shop.claude, "_client", FakeClaude(responses))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    modes = pipeline.Modes(config)
    assert modes.claude and modes.image_backend == "typography" and not modes.printify

    [design] = pipeline.run(config, 1, modes, log=lambda *_: None)
    assert design.status == "pending_review", design.notes


def test_image_qa_rejects_misspelled_art(config, monkeypatch):
    responses = [
        fake_response("end_turn", json.dumps({"risk": "low", "issues": []})),
        fake_response("end_turn", json.dumps({
            "text_seen": "JUST ONE MORE CHAPTR", "text_matches": False,
            "print_ready": True, "problems": ["misspelled CHAPTER"],
        })),
    ]
    monkeypatch.setattr(shop.claude, "_client", FakeClaude(responses))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    design = new_design(SAMPLE_CONCEPTS[1])
    pipeline.process(design, config, pipeline.Modes(config), log=lambda *_: None)
    assert design.status == "rejected"
    assert "CHAPTR" in design.notes[-1]


# --- Printify ---------------------------------------------------------------

class FakePrintify(Printify):
    """Answers the Printify endpoints the pipeline uses, from memory."""

    def __init__(self, fail_publish_once=False):
        super().__init__("token", "999")
        self.posts = []
        self.fail_publish_once = fail_publish_once

    def request(self, method, path, **kwargs):
        if path == "/catalog/blueprints.json":
            return [
                {"id": 12, "title": "Unisex Jersey Short Sleeve Tee", "brand": "Bella+Canvas", "model": "3001"},
                {"id": 13, "title": "Unisex Jersey Short Sleeve Tee with Pocket", "brand": "X", "model": "Y"},
                {"id": 68, "title": "Mug 11oz", "brand": "Generic", "model": "Mug"},
            ]
        if path.endswith("/print_providers.json"):
            return [{"id": 29, "title": "Monster Digital"}]
        if path.endswith("/variants.json"):
            if "/blueprints/68/" in path:
                return {"variants": [{"id": 500, "options": {"size": "11oz"}, "placeholders": [{"position": "front"}]}]}
            return {"variants": [
                {"id": 1, "options": {"color": "White", "size": "M"}, "placeholders": [{"position": "front"}, {"position": "back"}]},
                {"id": 2, "options": {"color": "Black", "size": "M"}, "placeholders": [{"position": "front"}]},
                {"id": 3, "options": {"color": "Natural", "size": "XS"}, "placeholders": [{"position": "front"}]},
            ]}
        self.posts.append((path, kwargs.get("json")))
        if path == "/uploads/images.json":
            return {"id": "img1"}
        if path.endswith("/products.json"):
            return {"id": f"prod{len(self.posts)}"}
        if path.endswith("/publish.json"):
            if self.fail_publish_once:
                self.fail_publish_once = False
                raise PrintifyError("publish failed")
            return {}
        raise AssertionError(path)


def approved_design(config):
    design = new_design(Concept(**{**SAMPLE_CONCEPTS[1].model_dump(), "products": ["tee", "mug"]}))
    Image.new("RGBA", (10, 10)).save(design.image_path)
    return design


def test_publish_builds_correct_printify_products(config):
    design = approved_design(config)
    printify = FakePrintify()
    publish_design(design, config, printify)

    products = [body for path, body in printify.posts if path.endswith("/products.json")]
    tee, mug = products
    assert tee["blueprint_id"] == 12  # exact title beats the pocket tee
    assert [v["id"] for v in tee["variants"]] == [1]  # Black isn't a configured color; XS isn't a size
    assert tee["variants"][0]["price"] == 2499
    assert tee["print_areas"][0]["placeholders"][0] == {
        "position": "front",
        "images": [{"id": "img1", "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}],
    }
    assert "AI" in tee["description"]
    assert mug["blueprint_id"] == 68 and [v["id"] for v in mug["variants"]] == [500]
    assert sum(path == "/uploads/images.json" for path, _ in printify.posts) == 1
    assert design.published_products == ["tee", "mug"]


def test_publish_retry_does_not_duplicate_products(config):
    design = approved_design(config)
    printify = FakePrintify(fail_publish_once=True)
    with pytest.raises(PrintifyError):
        publish_design(design, config, printify)
    assert design.printify_product_ids and not design.published_products

    publish_design(design, config, printify)
    created = [p for p, _ in printify.posts if p.endswith("/products.json")]
    assert len(created) == 2  # tee once, mug once
    assert design.published_products == ["tee", "mug"]
