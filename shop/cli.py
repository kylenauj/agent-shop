"""Command line: python -m shop <command>"""

import argparse
import sys

from shop import pipeline
from shop.config import load_config
from shop.printify import Printify
from shop.store import STATUSES, all_designs, load_design


def cmd_run(args, config):
    modes = pipeline.Modes(config, offline=args.offline)
    print("\n".join(modes.describe()) + "\n")
    count = args.count or config["pipeline"].get("ideas_per_run", 5)
    designs = pipeline.run(config, count, modes)
    print("\nSummary:")
    for status in STATUSES:
        n = sum(d.status == status for d in designs)
        if n:
            print(f"  {status}: {n}")
    if any(d.status == "pending_review" for d in designs):
        print("\nLook at data/designs/<id>/preview.png, then approve or reject each one.")


def cmd_list(args, config):
    designs = all_designs(args.status)
    if not designs:
        print("No designs yet. Try: python -m shop run")
    for d in designs:
        print(f"{d.status:15} {d.id:50} {d.concept.slogan or d.concept.niche}")


def cmd_show(args, config):
    d = load_design(args.id)
    c = d.concept
    print(f"{d.id}\nstatus: {d.status}\nslogan: {c.slogan!r}\nniche: {c.niche}")
    print(f"products: {', '.join(c.products)}\ntitle: {c.title}\ntags: {', '.join(c.tags)}")
    print(f"why it sells: {c.why_it_sells}\n\n{c.description}\n")
    print(f"artwork: {d.image_path}\npreview: {d.preview_path}\n\nhistory:")
    for note in d.notes:
        print(f"  {note}")


def cmd_approve(args, config):
    modes = pipeline.Modes(config, offline=args.offline)
    for design_id in args.ids:
        d = load_design(design_id)
        if d.status not in ("pending_review", "approved", "failed"):
            print(f"{d.id}: status is '{d.status}', skipping")
            continue
        if not d.image_path.exists():
            print(f"{d.id}: no artwork yet, skipping")
            continue
        d.set_status("approved", "by you")
        d.save()
        print(f"{d.id}: approved")
        if not args.no_publish:
            try:
                pipeline.publish(d, config, modes)
            except Exception as e:
                print(f"  publish failed: {e}\n  Fix it and run: python -m shop publish {d.id}")


def cmd_reject(args, config):
    d = load_design(args.id)
    d.set_status("rejected", args.reason or "by you")
    d.save()
    print(f"{d.id}: rejected")


def cmd_publish(args, config):
    modes = pipeline.Modes(config, offline=args.offline)
    designs = all_designs("approved") if args.all_approved else [load_design(i) for i in args.ids]
    if not designs:
        print("Nothing to publish.")
    for d in designs:
        if d.status != "approved":
            print(f"{d.id}: status is '{d.status}'; approve it first")
            continue
        print(d.id)
        try:
            pipeline.publish(d, config, modes)
        except Exception as e:
            print(f"  publish failed: {e}")


def cmd_shops(args, config):
    for shop in Printify.from_env().shops():
        print(f"id {shop['id']:>10}  {shop['title']}  ({shop.get('sales_channel')})")
    print("\nPut the Etsy shop's id in .env as PRINTIFY_SHOP_ID")


def cmd_catalog(args, config):
    printify = Printify.from_env()
    matches = printify.search_blueprints(" ".join(args.words))
    for b in matches[:40]:
        print(f"blueprint_id {b['id']:>5}  {b['title']}  ({b.get('brand', '')} {b.get('model', '')})")
    if len(matches) == 1 or args.providers:
        for b in matches[:3]:
            print(f"\nPrint providers for {b['title']}:")
            for p in printify.providers(b["id"]):
                print(f"  print_provider_id {p['id']:>4}  {p['title']}")


def cmd_orders(args, config):
    data = Printify.from_env().orders()
    orders = data.get("data", [])
    if not orders:
        print("No orders yet.")
    for o in orders:
        total = sum(item.get("cost", 0) for item in o.get("line_items", []))
        print(f"{o.get('created_at', '')[:10]}  {o.get('status', ''):12}  "
              f"{len(o.get('line_items', []))} item(s)  cost ${total / 100:.2f}")


def cmd_status(args, config):
    print(f"config: {config['_path']}")
    print("\n".join(pipeline.Modes(config).describe()))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m shop", description=__doc__)
    parser.add_argument("--config", help="path to config.yaml")
    parser.add_argument("--offline", action="store_true", help="use free stand-ins for every stage")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="come up with ideas, make artwork, check them")
    p.add_argument("--count", type=int)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("list", help="list designs")
    p.add_argument("--status", choices=STATUSES)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="show one design")
    p.add_argument("id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("approve", help="approve designs and publish them")
    p.add_argument("ids", nargs="+")
    p.add_argument("--no-publish", action="store_true")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("reject", help="reject a design")
    p.add_argument("id")
    p.add_argument("reason", nargs="?")
    p.set_defaults(func=cmd_reject)

    p = sub.add_parser("publish", help="publish approved designs")
    p.add_argument("ids", nargs="*")
    p.add_argument("--all-approved", action="store_true")
    p.set_defaults(func=cmd_publish)

    sub.add_parser("shops", help="list your Printify shops").set_defaults(func=cmd_shops)

    p = sub.add_parser("catalog", help="search Printify's product catalog")
    p.add_argument("words", nargs="+")
    p.add_argument("--providers", action="store_true", help="also list print providers")
    p.set_defaults(func=cmd_catalog)

    sub.add_parser("orders", help="recent orders").set_defaults(func=cmd_orders)
    sub.add_parser("status", help="show which stages are live").set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    config = load_config(args.config)
    try:
        args.func(args, config)
    except KeyError as e:
        if e.args and str(e.args[0]).startswith("PRINTIFY"):
            sys.exit(f"Set {e.args[0]} in .env first")
        raise
