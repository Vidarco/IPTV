"""Bucket channels into a fixed set of categories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from src.m3u import Channel


DEFAULT_CATEGORY = "General"


@dataclass
class Rule:
    category: str
    keywords: list[str]


def load_rules(path: Path) -> list[Rule]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        Rule(category=r["category"], keywords=[k.lower() for k in r.get("keywords", [])])
        for r in data.get("rules", [])
    ]


def categorize(channel: Channel, rules: list[Rule]) -> str:
    haystack = f"{channel.group_title} {channel.name}".lower()
    for rule in rules:
        if any(kw in haystack for kw in rule.keywords):
            return rule.category
    return DEFAULT_CATEGORY


def categorize_all(channels: list[Channel], rules: list[Rule]) -> list[Channel]:
    """Return channels with their `attrs['group-title']` overwritten with our
    chosen category. Original is kept in `attrs['source-group-title']` for trace.
    """
    out: list[Channel] = []
    for ch in channels:
        cat = categorize(ch, rules)
        new_attrs = dict(ch.attrs)
        if "group-title" in new_attrs and new_attrs["group-title"] != cat:
            new_attrs["source-group-title"] = new_attrs["group-title"]
        new_attrs["group-title"] = cat
        out.append(
            Channel(
                name=ch.name,
                url=ch.url,
                duration=ch.duration,
                attrs=new_attrs,
                extras=ch.extras,
                source=ch.source,
            )
        )
    return out
