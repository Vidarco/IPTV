"""Filter raw M3U entries down to Iranian/Persian channels and dedupe."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from src.fetch import Source, fetch_all, load_sources
from src.m3u import Channel


# Word-boundary patterns. Latin keywords are matched as whole words to avoid
# substring traps (e.g. "iran" matching "Arirang"). Persian-script keywords are
# matched as substring — boundary semantics don't apply cleanly to non-Latin.
_LATIN_KEYWORDS = [
    # Strong brand names — unambiguous
    "manoto", "persiana", "irib", "ifilm", "tapesh", "andisheh",
    "didgah", "pmc", "azadi",
    # Phrasal brand names
    "iran international", "bbc persian", "voa farsi", "voa persian",
    "radio farda", "press tv", "hispan tv", "iran tv", "iran nama",
    "channel one persia", "pars tv", "mbc persia",
    # Diaspora music
    "bia2", "melody",
    # Generic terms (still word-boundary, so "iran" won't match "Arirang")
    "iran", "irani", "persia", "persian", "farsi", "iranian",
]

_PERSIAN_KEYWORDS = [
    "ایران", "فارس", "تهران", "خبر", "موسیقی", "ورزش", "کودک", "اخبار",
    "فیلم", "سریال", "سینما", "مذهبی", "قرآن",
]

# Compile a single regex with word boundaries. \b works for ASCII boundaries;
# good enough for our Latin-only set.
_LATIN_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _LATIN_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# tvg-country values that should NEVER match an Iranian/Persian channel.
# If a candidate has one of these and ALSO doesn't carry fas/per language,
# it's a false positive (e.g. Arirang TV with country=KR).
_FOREIGN_COUNTRIES = {
    "kr", "jp", "cn", "tw", "hk", "th", "vn", "id", "ph", "my", "sg",
    "in", "pk", "bd", "lk", "np",
    "br", "ar", "mx", "cl", "co", "pe", "ve",
    "ru", "ua", "kz", "uz", "az", "by", "ge",
    "fr", "de", "it", "es", "pt", "nl", "be", "se", "no", "fi", "dk",
    "pl", "cz", "ro", "gr", "tr", "il",
    "us", "ca", "gb", "au", "nz",
    "eg", "sa", "ae", "qa", "kw", "iq", "sy", "lb", "jo", "ma", "dz", "tn",
}

_PERSIAN_LANGS = {"fas", "per", "fa"}


# Hosts known to serve malformed HLS that strict TV players (e.g. Samsung's
# native player) reject with PLAYER_ERROR_NOT_SUPPORTED_FILE. ffprobe accepts
# the streams (it's lenient), so they pass our validation step but don't
# actually play. We drop them at the filter stage.
#
# telewebion.ir: serves "EXT-X-VERSION:6" without the leading '#' on the tag.
_BAD_HLS_HOSTS = {
    "telewebion.ir",
    "ncdn.telewebion.ir",
}


def _host_blocked(url: str) -> bool:
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    return host.lower() in _BAD_HLS_HOSTS


def _country_codes(channel: Channel) -> set[str]:
    return {
        c.strip()
        for c in re.split(r"[;,\s]+", channel.tvg_country.lower())
        if c.strip()
    }


def _language_codes(channel: Channel) -> set[str]:
    return {
        l.strip()
        for l in re.split(r"[;,\s]+", channel.tvg_language.lower())
        if l.strip()
    }


def _name_hits(name: str) -> bool:
    name_lower = name.lower()
    if _LATIN_RE.search(name_lower):
        return True
    return any(kw in name_lower for kw in _PERSIAN_KEYWORDS)


def matches(channel: Channel, country_filter: list[str], language_filter: list[str]) -> bool:
    """Decide whether to keep a channel.

    Logic:
        - Drop URLs from hosts known to serve malformed HLS (Samsung's
          strict player rejects these even though ffprobe accepts them).
        - If the channel's tvg-country is a known non-Persian country AND its
          language isn't fas/per/dari, drop it. (Kills Arirang from country=KR.)
        - If the source pre-filtered (e.g. iptv-org's ir.m3u with no filters
          configured), keep everything else.
        - For filtered sources (e.g. the master index), require either a
          country/language match OR a STRONG brand match. Generic keywords
          like "iran" or "pmc" are too loose for the broad firehose and
          let in noise (PMC Telugu, Melody FM Jordan, etc.).
    """
    if _host_blocked(channel.url):
        return False

    countries = _country_codes(channel)
    languages = _language_codes(channel)

    # Hard exclude: foreign country + non-Persian language (unless strong brand).
    if countries & _FOREIGN_COUNTRIES and not (languages & _PERSIAN_LANGS):
        if not _strong_brand_match(channel.name):
            return False

    if not country_filter and not language_filter:
        return True

    if country_filter and (countries & set(country_filter)):
        return True
    if language_filter and (languages & set(language_filter)):
        return True
    # Strict mode: only strong brands count for name-only matches.
    return _strong_brand_match(channel.name)


# Strong brands: kept even if the channel has a foreign country tag (some
# diaspora broadcasters license themselves under odd country codes).
_STRONG_BRANDS = [
    "manoto", "persiana", "irib", "ifilm", "tapesh", "andisheh",
    "didgah", "ganje hozoor", "ganj e hozour",
    "iran international", "bbc persian", "voa farsi", "voa persian",
    "radio farda", "press tv", "iran tv network", "iran nama", "pars tv",
    "mbc persia", "channel one persia", "hispan tv", "iran-e farda",
    "imam hussein", "esra tv", "icc tv", "al-alam", "ayeneh", "canada star",
    "gem usa", "gem junior", "gem kids",
]
_STRONG_BRAND_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _STRONG_BRANDS) + r")\b",
    re.IGNORECASE,
)


def _strong_brand_match(name: str) -> bool:
    return bool(_STRONG_BRAND_RE.search(name.lower()))


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
        before = len(kept)
        for ch in channels:
            if matches(ch, src.country_filter, src.language_filter):
                kept.append(ch)
        print(f"[filter] {src_name}: kept {len(kept) - before} of {len(channels)}", file=sys.stderr)
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
