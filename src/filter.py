"""Filter raw M3U entries down to Iranian/Persian channels and dedupe."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from src.fetch import Source, fetch_all, load_sources
from src.m3u import Channel


# Keyword cues that strongly imply a Persian/Iranian channel even when tvg
# metadata is missing. Mix of Latin-alphabet diaspora brands and Persian script.
_NAME_KEYWORDS = [
    # Latin
    "iran", "irani", "persia", "persian", "farsi",
    "irib", "manoto", "gem ", "gemtv", "iran international", "iranintl",
    "bbc persian", "voa farsi", "voa persian", "radio farda",
    "pmc", "tapesh", "didgah", "andisheh",
    # Persian script — broad enough to catch most Iranian channels
    "ایران", "فارس", "تهران", "خبر", "موسیقی", "ورزش", "کودک",
]

_NAME_KEYWORDS_LOWER = [k.lower() for k in _NAME_KEYWORDS]


def matches(channel: Channel, country_filter: list[str], language_filter: list[str]) -> bool:
    """True if the channel should be kept.

    If the source supplied no filters (empty lists), keep everything — the
    upstream is already pre-curated. Otherwise require a country/language hit
    or a keyword hit on the channel name.
    """
    if not country_filter and not language_filter:
        return True

    country = channel.tvg_country.lower()
    if country_filter:
        country_codes = {c.strip() for c in re.split(r"[;,\s]+", country) if c.strip()}
        if country_codes & set(country_filter):
            return True

    language = channel.tvg_language.lower()
    if language_filter:
        lang_codes = {l.strip() for l in re.split(r"[;,\s]+", language) if l.strip()}
        if lang_codes & set(language_filter):
            return True

    name_lower = channel.name.lower()
    return any(kw in name_lower for kw in _NAME_KEYWORDS_LOWER)


def dedupe(channels: list[Channel]) -> list[Channel]:
    """Dedupe by stream URL, preferring entries with richer metadata."""
    by_url: dict[str, Channel] = {}
    for ch in channels:
        existing = by_url.get(ch.url)
        if existing is None or _metadata_score(ch) > _metadata_score(existing):
            by_url[ch.url] = ch
    return list(by_url.values())


def _metadata_score(ch: Channel) -> int:
    score = 0
    if ch.tvg_id:
        score += 2
    if ch.tvg_language:
        score += 1
    if ch.tvg_country:
        score += 1
    if ch.group_title:
        score += 1
    if ch.attrs.get("tvg-logo"):
        score += 1
    return score


def filter_all(fetched: dict[str, list[Channel]], sources: list[Source]) -> list[Channel]:
    by_name = {s.name: s for s in sources}
    kept: list[Channel] = []
    for src_name, channels in fetched.items():
        src = by_name.get(src_name)
        if src is None:
            continue
        for ch in channels:
            if matches(ch, src.country_filter, src.language_filter):
                kept.append(ch)
        print(
            f"[filter] {src_name}: kept {sum(1 for c in kept if c.source == src_name)} "
            f"of {len(channels)}",
            file=sys.stderr,
        )
    deduped = dedupe(kept)
    print(
        f"[filter] total: {len(kept)} candidates -> {len(deduped)} after dedupe",
        file=sys.stderr,
    )
    return deduped


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    srcs = load_sources(root / "sources.yml")
    fetched = fetch_all(srcs)
    candidates = filter_all(fetched, srcs)

    cache_dir = root / "cache"
    cache_dir.mkdir(exist_ok=True)
    out = cache_dir / "candidates.m3u"
    from src.m3u import serialize
    out.write_text(serialize(candidates), encoding="utf-8")
    print(f"\n[filter] wrote {len(candidates)} candidates to {out}", file=sys.stderr)
