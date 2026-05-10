"""Fetch upstream M3U playlists listed in sources.yml."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

from src.m3u import Channel, parse


@dataclass
class Source:
    name: str
    url: str
    enabled: bool = True
    country_filter: list[str] = None
    language_filter: list[str] = None

    def __post_init__(self) -> None:
        self.country_filter = [c.lower() for c in (self.country_filter or [])]
        self.language_filter = [l.lower() for l in (self.language_filter or [])]


def load_sources(path: Path) -> list[Source]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Source(**s) for s in data.get("sources", []) if s.get("enabled", True)]


def fetch_all(sources: list[Source], timeout: float = 30.0) -> dict[str, list[Channel]]:
    """Fetch every enabled source. Returns {source_name: [Channel, ...]}.

    URLs starting with http(s):// are fetched over HTTP. Anything else is
    treated as a repo-relative path to a local M3U file (e.g. manual.m3u).
    Failures are logged but don't abort the run — one dead upstream shouldn't
    sink the whole pipeline.
    """
    repo_root = Path(__file__).resolve().parents[1]
    results: dict[str, list[Channel]] = {}
    headers = {"User-Agent": "iran-persian-iptv/0.1 (+https://github.com)"}
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        for src in sources:
            try:
                if src.url.startswith(("http://", "https://")):
                    resp = client.get(src.url)
                    resp.raise_for_status()
                    text = resp.text
                else:
                    rel = src.url.removeprefix("file://")
                    text = (repo_root / rel).read_text(encoding="utf-8")
                channels = parse(text, source=src.name)
                results[src.name] = channels
                print(f"[fetch] {src.name}: {len(channels)} entries", file=sys.stderr)
            except Exception as e:
                print(f"[fetch] {src.name}: FAILED ({e})", file=sys.stderr)
                results[src.name] = []
    return results


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    srcs = load_sources(root / "sources.yml")
    fetched = fetch_all(srcs)
    total = sum(len(v) for v in fetched.values())
    print(f"\n[fetch] total raw entries across all sources: {total}", file=sys.stderr)
