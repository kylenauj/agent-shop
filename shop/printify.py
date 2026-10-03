"""Stage 5: create products on Printify and publish them to the linked Etsy shop.

Once your Etsy shop is connected inside Printify, Printify handles the rest:
orders sync from Etsy, Printify prints and ships them, and tracking goes back
to Etsy. That's what makes the store run itself after a design is published.

API reference: https://developers.printify.com/
"""

import base64
import json
import os
import time

import requests

from shop.config import DATA_DIR
from shop.store import Design, dump_json

API = "https://api.printify.com/v1"
MAX_VARIANTS = 100  # Printify's per-product limit


class PrintifyError(RuntimeError):
    pass


class Printify:
    def __init__(self, token: str, shop_id: str | None):
        self.shop_id = shop_id
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "User-Agent": "agent-shop",
            "Content-Type": "application/json",
        })

    @classmethod
    def from_env(cls) -> "Printify":
        return cls(os.environ["PRINTIFY_API_TOKEN"], os.environ.get("PRINTIFY_SHOP_ID"))

    def request(self, method: str, path: str, **kwargs):
        for attempt in range(5):
            response = self.session.request(method, f"{API}{path}", timeout=120, **kwargs)
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(int(response.headers.get("Retry-After", 2 ** (attempt + 1))))
                continue
            if not response.ok:
                raise PrintifyError(f"{method} {path} -> {response.status_code}: {response.text[:500]}")
            return response.json() if response.content else {}
        raise PrintifyError(f"{method} {path} kept failing; last status {response.status_code}")

    def require_shop(self) -> str:
        if not self.shop_id:
            raise PrintifyError("Set PRINTIFY_SHOP_ID (run `python -m shop shops` to find it)")
        return self.shop_id

    # --- catalog -----------------------------------------------------------

    def shops(self) -> list[dict]:
        return self.request("GET", "/shops.json")

    def blueprints(self) -> list[dict]:
        cache = DATA_DIR / "catalog" / "blueprints.json"
        if cache.exists() and time.time() - cache.stat().st_mtime < 7 * 86400:
            return json.loads(cache.read_text())
        blueprints = self.request("GET", "/catalog/blueprints.json")
        cache.parent.mkdir(parents=True, exist_ok=True)
        dump_json(cache, blueprints)
        return blueprints

    def search_blueprints(self, words: str) -> list[dict]:
        terms = words.lower().split()
        return [
            b for b in self.blueprints()
            if all(t in f"{b['title']} {b.get('brand', '')} {b.get('model', '')}".lower() for t in terms)
        ]

    def providers(self, blueprint_id: int) -> list[dict]:
        return self.request("GET", f"/catalog/blueprints/{blueprint_id}/print_providers.json")

    def variants(self, blueprint_id: int, provider_id: int) -> list[dict]:
        data = self.request(
            "GET", f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json"
        )
        return data["variants"]

    def resolve(self, name: str, template: dict) -> dict:
        """Work out blueprint, print provider, variants, and print position for a product."""
        blueprint_id = template.get("blueprint_id")
        if not blueprint_id:
            matches = self.search_blueprints(template["blueprint_search"])
            if not matches:
                raise PrintifyError(
                    f"No Printify product matches '{template['blueprint_search']}' for '{name}'. "
                    "Run `python -m shop catalog <words>` and set blueprint_id in config.yaml."
                )
            # Prefer an exact title match, then the shortest title (the plain version).
            wanted = template["blueprint_search"].lower()
            matches.sort(key=lambda b: (b["title"].lower() != wanted, len(b["title"])))
            blueprint_id = matches[0]["id"]

        provider_id = template.get("print_provider_id")
        if not provider_id:
            providers = self.providers(blueprint_id)
            if not providers:
                raise PrintifyError(f"No print providers for blueprint {blueprint_id}")
            provider_id = providers[0]["id"]

        def wanted(option_values: list[str], value: str | None) -> bool:
            return not option_values or (value or "").lower() in {v.lower() for v in option_values}

        all_variants = self.variants(blueprint_id, provider_id)
        chosen = [
            v for v in all_variants
            if wanted(template.get("colors") or [], v.get("options", {}).get("color"))
            and wanted(template.get("sizes") or [], v.get("options", {}).get("size"))
        ][:MAX_VARIANTS]
        if not chosen:
            colors = sorted({v.get("options", {}).get("color") or "-" for v in all_variants})
            sizes = sorted({v.get("options", {}).get("size") or "-" for v in all_variants})
            raise PrintifyError(
                f"No variants of '{name}' match your colors/sizes. "
                f"Available colors: {colors}. Sizes: {sizes}."
            )

        positions = [p["position"] for p in chosen[0].get("placeholders", [])]
        position = template.get("position") or ("front" if "front" in positions else positions[0])
        return {
            "blueprint_id": blueprint_id,
            "print_provider_id": provider_id,
            "variant_ids": [v["id"] for v in chosen],
            "position": position,
        }

    # --- products ----------------------------------------------------------

    def upload_image(self, path) -> str:
        contents = base64.b64encode(path.read_bytes()).decode()
        data = self.request(
            "POST", "/uploads/images.json", json={"file_name": path.name, "contents": contents}
        )
        return data["id"]

    def create_product(self, payload: dict) -> str:
        data = self.request("POST", f"/shops/{self.require_shop()}/products.json", json=payload)
        return data["id"]

    def publish(self, product_id: str) -> None:
        self.request(
            "POST",
            f"/shops/{self.require_shop()}/products/{product_id}/publish.json",
            json={
                "title": True, "description": True, "images": True, "variants": True,
                "tags": True, "keyFeatures": True, "shipping_template": True,
            },
        )

    def orders(self, page: int = 1) -> dict:
        return self.request("GET", f"/shops/{self.require_shop()}/orders.json", params={"page": page})


def product_payload(design: Design, config: dict, resolved: dict, image_id: str, price: int) -> dict:
    concept = design.concept
    description = concept.description.strip()
    disclosure = (config["shop"].get("disclosure") or "").strip()
    if disclosure:
        description += "\n\n" + disclosure
    return {
        "title": concept.title,
        "description": description,
        "tags": concept.tags,
        "blueprint_id": resolved["blueprint_id"],
        "print_provider_id": resolved["print_provider_id"],
        "variants": [
            {"id": vid, "price": price, "is_enabled": True} for vid in resolved["variant_ids"]
        ],
        "print_areas": [{
            "variant_ids": resolved["variant_ids"],
            "placeholders": [{
                "position": resolved["position"],
                "images": [{"id": image_id, "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}],
            }],
        }],
    }


def publish_design(design: Design, config: dict, printify: Printify | None) -> list[str]:
    """Create and publish one product per product type. Returns what happened.

    With printify=None (no token), saves the payloads instead so you can see
    exactly what would be sent.
    """
    results = []
    product_names = [p for p in design.concept.products if p in config["products"]]
    if not product_names:
        raise PrintifyError("Design has no products that exist in config.yaml")

    image_id = None
    for name in product_names:
        if name in design.published_products:
            results.append(f"{name}: already published")
            continue
        if name in design.printify_product_ids and printify is not None:
            # Created on an earlier run but publishing failed; just publish it.
            printify.publish(design.printify_product_ids[name])
            design.published_products.append(name)
            design.save()
            results.append(f"{name}: published (Printify product {design.printify_product_ids[name]})")
            continue
        template = config["products"][name]

        if printify is None:
            resolved = {
                "blueprint_id": template.get("blueprint_id") or f"<search: {template['blueprint_search']}>",
                "print_provider_id": template.get("print_provider_id") or "<first available>",
                "variant_ids": ["<matched from colors/sizes>"],
                "position": template.get("position") or "front",
            }
            payload = product_payload(design, config, resolved, "<uploaded image id>", template["price"])
            out = design.folder / f"printify_{name}.json"
            dump_json(out, payload)
            results.append(f"{name}: dry run, payload saved to {out.name}")
            continue

        resolved = printify.resolve(name, template)
        if image_id is None:
            image_id = printify.upload_image(design.image_path)
        payload = product_payload(design, config, resolved, image_id, template["price"])
        product_id = printify.create_product(payload)
        design.printify_product_ids[name] = product_id
        design.save()  # record each product as soon as it exists, so a retry won't duplicate it
        printify.publish(product_id)
        design.published_products.append(name)
        design.save()
        results.append(f"{name}: published (Printify product {product_id})")
    return results
