"""Final assembly: categorize the alive channels and write output/iran-persian.m3u."""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.categorize import categorize_all, load_rules
from src.fetch import fetch_all, load_sources
from src.filter import filter_all
from src.m3u import Channel, serialize
from src.validate import validate_channels


CATEGORY_ORDER = [
    "News",
    "Entertainment",
    "Movies",
    "Music",
    "Sports",
    "Kids",
    "Religious",
    "General",
]


def build_outputs(root: Path, alive: list[Channel]) -> None:
    rules = load_rules(root / "categories.yml")
    categorized = categorize_all(alive, rules)

    def sort_key(ch: Channel) -> tuple[int, str]:
        cat = ch.attrs.get("group-title", "General")
        try:
            idx = CATEGORY_ORDER.index(cat)
        except ValueError:
            idx = len(CATEGORY_ORDER)
        return (idx, ch.name.lower())

    categorized.sort(key=sort_key)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    counts = Counter(c.attrs.get("group-title", "General") for c in categorized)
    summary = ", ".join(f"{cat}={counts[cat]}" for cat in CATEGORY_ORDER if counts[cat])
    header_extras = [
        f"# iran-persian.m3u  generated {timestamp}",
        f"# total: {len(categorized)} channels  ({summary})",
        "# source: https://github.com/Vidarco/IPTV",
    ]

    output = root / "output"
    output.mkdir(exist_ok=True)
    m3u_path = output / "iran-persian.m3u"
    m3u_path.write_text(serialize(categorized, header_extras=header_extras), encoding="utf-8")
    print(f"[build] wrote {len(categorized)} channels to {m3u_path}", file=sys.stderr)
    print(f"[build] breakdown: {summary}", file=sys.stderr)

    report = {
        "generated_at": timestamp,
        "total": len(categorized),
        "by_category": dict(counts),
        "channels": [
            {
                "name": ch.name,
                "category": ch.attrs.get("group-title", "General"),
                "url": ch.url,
                "source": ch.source,
                "tvg_id": ch.tvg_id,
                "language": ch.tvg_language,
                "country": ch.tvg_country,
            }
            for ch in categorized
        ],
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[build] wrote report.json to {output}", file=sys.stderr)


def run(root: Path) -> None:
    srcs = load_sources(root / "sources.yml")
    fetched = fetch_all(srcs)
    candidates = filter_all(fetched, srcs)
    alive = validate_channels(candidates)
    build_outputs(root, alive)
