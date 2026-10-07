"""Build a public, read-only dashboard for GitHub Pages (no server required)."""
from __future__ import annotations

import argparse
import copy
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from bot import ROOT, Tracker, eligible, now, sealed_english

PRODUCT_FIELDS = (
    "id", "source_id", "store", "title", "url", "image", "price_cents", "currency",
    "availability", "listed_at", "first_seen", "checked_at", "stale", "seller",
    "seller_verified", "reference_cents", "reference_kind", "reference_url", "qualifies",
)
SOURCE_FIELDS = ("name", "url", "status", "checked_at", "count", "message", "coverage")
RELEASE_FIELDS = ("id", "title", "url", "first_seen")
ALERT_FIELDS = ("id", "kind", "at", "title", "store", "url", "price_cents", "reference_cents", "reference_kind")
ASSETS = ("index.html", "app.js", "style.css", "favicon.svg")
OUTPUT_FILES = set(ASSETS) | {"hosting.js", "state.json", ".nojekyll"}


def pick(value, fields):
    return {key: value[key] for key in fields if key in value}


def public_snapshot(state, config):
    """Only configured public sources leave the checker; private watches do not."""
    interval = max(300, int(config.get("interval_seconds", 900)))
    allowed_sources = {source["id"] for source in config["sources"]}
    result = {
        "mode": "pages", "generated_at": now(), "last_scan": state.get("last_scan"),
        "interval_seconds": interval, "scanning": False, "next_check": None,
        "products": {}, "releases": {}, "sources": {}, "alerts": [],
    }
    private_refs = state.get("references", {})
    for key, raw in state.get("products", {}).items():
        if raw.get("source_id") not in allowed_sources or not sealed_english(raw.get("title", "")):
            continue
        item = copy.deepcopy(raw)
        # Personal limits and manually entered references stay in the local app.
        if key in private_refs or item.get("reference_kind") == "My price limit":
            for field in ("reference_cents", "reference_kind", "reference_url"):
                item[field] = None
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(item["checked_at"])).total_seconds()
            item["stale"] = bool(item.get("stale")) or not 0 <= age <= interval * 2
        except (KeyError, TypeError, ValueError):
            item["stale"] = True
        item["qualifies"] = eligible(item, interval * 2)
        result["products"][key] = pick(item, PRODUCT_FIELDS)
    result["sources"] = {key: pick(value, SOURCE_FIELDS) for key, value in state.get("sources", {}).items() if key in allowed_sources}
    if any(source["kind"] == "releases" for source in config["sources"]):
        result["releases"] = {key: pick(value, RELEASE_FIELDS) for key, value in state.get("releases", {}).items()}
    # Old alerts have no product ID. If a private watch shares a public URL,
    # omit all deal history for that URL rather than leak its personal reference.
    private_urls = {
        item.get("url") for key, item in state.get("products", {}).items()
        if item.get("source_id") not in allowed_sources or key in private_refs
        or item.get("reference_kind") == "My price limit"
    }
    public_urls = {item["url"] for item in result["products"].values()} - private_urls
    release_urls = {item["url"] for item in result["releases"].values()}
    for alert in state.get("alerts", [])[-500:]:
        if alert.get("reference_kind") == "My price limit":
            continue
        if ((alert.get("kind") == "release" and alert.get("url") in release_urls)
                or (alert.get("kind") == "deal" and alert.get("url") in public_urls and sealed_english(alert.get("title", "")))):
            result["alerts"].append(pick(alert, ALERT_FIELDS))
    return result


def write_site(snapshot, output):
    output = Path(output)
    if output.is_symlink():
        raise ValueError("Choose an ordinary output directory, not a symbolic link.")
    output.mkdir(parents=True, exist_ok=True)
    # Refuse to accidentally publish other files already in an output directory.
    for path in output.iterdir():
        if path.name not in OUTPUT_FILES or path.is_dir() or path.is_symlink():
            raise ValueError(f"Output contains an unrelated file: {path.name}. Choose a dedicated empty directory.")
    for asset in ASSETS:
        shutil.copyfile(ROOT / "static" / asset, output / asset)
    (output / "hosting.js").write_text('window.POKEWATCH_HOSTING = {mode: "pages", stateUrl: "./state.json"};\n', encoding="utf-8")
    (output / "state.json").write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (output / ".nojekyll").write_text("", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="store_true", help="Run a fresh public-source scan before building")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "pages", help="Dedicated cloud checker state")
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    config["interval_seconds"] = max(300, int(config.get("interval_seconds", 900)))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.scan:
        # The default is isolated from the running local checker. Never share writers.
        if args.data_dir.resolve() == (ROOT / "data").resolve():
            parser.error("Use a separate --data-dir for Pages scans; the local bot uses data/.")
        tracker = Tracker(config, args.data_dir)
        tracker.state["watches"] = []
        tracker.state["references"] = {}
        tracker.scan()
        state = tracker.state
    else:
        # Read-only preview: do not instantiate Tracker, which marks saved rows stale.
        state = json.loads((args.data_dir / "state.json").read_text(encoding="utf-8"))
    snapshot = public_snapshot(state, config)
    write_site(snapshot, args.output)
    print(json.dumps({"output": str(args.output), "products": len(snapshot["products"]),
                      "matches": sum(item["qualifies"] for item in snapshot["products"].values()),
                      "last_scan": snapshot["last_scan"], "public_sources": len(snapshot["sources"])}, indent=2))


if __name__ == "__main__":
    main()
