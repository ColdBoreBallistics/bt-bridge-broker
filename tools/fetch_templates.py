#!/usr/bin/env python3
"""Fetch BT Bridge templates from the catalog into the broker's templates/ dir.

Examples:
    python3 tools/fetch_templates.py list
    python3 tools/fetch_templates.py search weatherflow
    python3 tools/fetch_templates.py install builtin.weatherflow-tactical-device
    python3 tools/fetch_templates.py install --all-builtin

Configuration:
    --catalog-url URL   override base URL (default: GitHub raw; or file://<path>)
    BT_CATALOG_BASE_URL env var (same as --catalog-url)
    BT_CATALOG_TOKEN    env var: GitHub token for the private repo
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

# Allow running as a script: ensure the repo root is importable.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from broker.catalog import CatalogClient, CatalogError, DEFAULT_BASE_URL

TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent.parent / "templates"


def _client(args) -> CatalogClient:
    base = args.catalog_url or os.environ.get("BT_CATALOG_BASE_URL") or DEFAULT_BASE_URL
    token = os.environ.get("BT_CATALOG_TOKEN")
    return CatalogClient(base_url=base, token=token)


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch BT Bridge templates from the catalog.")
    p.add_argument("--catalog-url", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("search")
    s.add_argument("query")
    i = sub.add_parser("install")
    i.add_argument("ids", nargs="*")
    i.add_argument("--all-builtin", action="store_true")
    args = p.parse_args()

    client = _client(args)
    try:
        index = client.fetch_index()
    except CatalogError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.cmd == "list":
        for e in sorted(index["templates"], key=lambda x: x["id"]):
            print(f"{e['id']:50s} {e['version']:10s} {e.get('type','?'):10s} {e.get('name','')}")
    elif args.cmd == "search":
        q = args.query.lower()
        for e in index["templates"]:
            blob = f"{e['id']} {e.get('name','')} {e.get('description','')}".lower()
            if q in blob:
                print(f"{e['id']:50s} {e['version']:10s} {e.get('name','')}")
    elif args.cmd == "install":
        ids = list(args.ids)
        if args.all_builtin:
            ids += [e["id"] for e in index["templates"] if e.get("namespace") == "builtin"]
        if not ids:
            print("ERROR: nothing to install (give IDs or --all-builtin)", file=sys.stderr)
            sys.exit(1)
        try:
            written = client.install(ids, dest_dir=TEMPLATES_DIR, index=index)
        except CatalogError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"Installed {len(written)} template(s) into {TEMPLATES_DIR}:")
        for w in written:
            print(f"  {w.name}")


if __name__ == "__main__":
    main()
