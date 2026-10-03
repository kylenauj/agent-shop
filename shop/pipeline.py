"""Runs the stages in order and moves each design through its statuses."""

from shop import compliance, images, qa
from shop.config import has_anthropic_credentials, has_openai_credentials, has_printify_credentials
from shop.ideate import SAMPLE_CONCEPTS, generate_concepts
from shop.printify import Printify, publish_design
from shop.store import Design, existing_slogans, new_design


class Modes:
    """Which stages run for real and which use their free stand-ins."""

    def __init__(self, config: dict, offline: bool = False):
        self.claude = has_anthropic_credentials() and not offline
        self.image_backend = images.pick_backend(config, has_openai_credentials() and not offline)
        self.printify = has_printify_credentials() and not offline

    def describe(self) -> list[str]:
        return [
            f"Ideas + listings: {'Claude' if self.claude else 'built-in samples (no Claude key)'}",
            f"Policy check:     {'blocklist + Claude' if self.claude else 'blocklist only'}",
            f"Artwork:          {self.image_backend}",
            f"Image QA:         {'Claude' if self.claude else 'skipped (no Claude key)'}",
            f"Publishing:       {'Printify -> Etsy' if self.printify else 'dry run (no Printify token)'}",
        ]


def run(config: dict, count: int, modes: Modes, log=print) -> list[Design]:
    log(f"Coming up with {count} ideas...")
    if modes.claude:
        concepts = generate_concepts(config, count, avoid=existing_slogans())
    else:
        concepts = SAMPLE_CONCEPTS[:count]

    designs = []
    for concept in concepts:
        design = new_design(concept)
        designs.append(design)
        log(f"\n- {concept.slogan or concept.niche}  [{design.id}]")
        try:
            process(design, config, modes, log)
        except Exception as e:  # keep going with the other designs
            design.set_status("failed", f"{type(e).__name__}: {e}")
            design.save()
            log(f"  failed: {e}")
    return designs


def process(design: Design, config: dict, modes: Modes, log) -> None:
    passed, reason = compliance.review(design.concept, config, use_claude=modes.claude)
    if not passed:
        design.set_status("rejected", f"policy check: {reason}")
        design.save()
        log(f"  rejected by policy check: {reason}")
        return
    design.note(f"policy check passed ({reason})")
    log("  policy check passed")

    images.generate(design, config, modes.image_backend)
    design.set_status("designed", f"artwork by {modes.image_backend}")
    design.save()
    log(f"  artwork saved: {design.image_path}")

    if modes.claude:
        passed, detail = qa.inspect(design, config)
        if not passed:
            design.set_status("rejected", f"image QA: {detail}")
            design.save()
            log(f"  rejected by image QA: {detail}")
            return
        design.note(f"image QA passed ({detail})")
        log("  image QA passed")

    if config["pipeline"].get("auto_publish"):
        design.set_status("approved", "auto_publish is on")
        design.save()
        publish(design, config, modes, log)
    else:
        design.set_status("pending_review")
        design.save()
        log("  waiting for your review: python -m shop approve " + design.id)


def publish(design: Design, config: dict, modes: Modes, log=print) -> None:
    printify = Printify.from_env() if modes.printify else None
    try:
        results = publish_design(design, config, printify)
    except Exception as e:
        design.note(f"publish failed: {type(e).__name__}: {e}")
        design.save()
        raise
    for line in results:
        design.note(line)
        log(f"  {line}")
    if printify is not None:
        design.set_status("published")
    design.save()
