"""M3U parsing and serialization."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_DURATION_RE = re.compile(r"#EXTINF:(-?[\d.]+)")


@dataclass
class Channel:
    name: str
    url: str
    duration: float = -1.0
    attrs: dict[str, str] = field(default_factory=dict)
    extras: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def tvg_id(self) -> str:
        return self.attrs.get("tvg-id", "")

    @property
    def tvg_language(self) -> str:
        return self.attrs.get("tvg-language", "")

    @property
    def tvg_country(self) -> str:
        return self.attrs.get("tvg-country", "")

    @property
    def group_title(self) -> str:
        return self.attrs.get("group-title", "")

    def to_extinf(self) -> str:
        attr_str = " ".join(f'{k}="{v}"' for k, v in self.attrs.items())
        head = f"#EXTINF:{self.duration:g}"
        if attr_str:
            head += f" {attr_str}"
        head += f",{self.name}"
        return head


def parse(text: str, source: str = "") -> list[Channel]:
    """Parse an M3U/M3U8 playlist into Channel objects.

    Accepts the common #EXTINF / URL pairing. Lines starting with #EXTVLCOPT,
    #EXTGRP, etc. are preserved as 'extras' on the channel that follows.
    """
    channels: list[Channel] = []
    pending_extinf: str | None = None
    pending_extras: list[str] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            continue
        if line.startswith("#EXTINF"):
            pending_extinf = line
            pending_extras = []
            continue
        if line.startswith("#"):
            if pending_extinf is not None:
                pending_extras.append(line)
            continue
        if pending_extinf is None:
            continue
        ch = _parse_extinf(pending_extinf, line, source)
        if ch is not None:
            ch.extras = pending_extras
            channels.append(ch)
        pending_extinf = None
        pending_extras = []

    return channels


def _parse_extinf(extinf: str, url: str, source: str) -> Channel | None:
    duration = -1.0
    if m := _DURATION_RE.match(extinf):
        try:
            duration = float(m.group(1))
        except ValueError:
            pass

    attrs = dict(_ATTR_RE.findall(extinf))

    name = ""
    if "," in extinf:
        name = extinf.split(",", 1)[1].strip()
    if not name:
        name = attrs.get("tvg-name", "") or url
    return Channel(name=name, url=url, duration=duration, attrs=attrs, source=source)


def serialize(channels: list[Channel], header_extras: list[str] | None = None) -> str:
    """Render a list of channels back to an M3U string."""
    lines = ["#EXTM3U"]
    for extra in header_extras or []:
        lines.append(extra)
    for ch in channels:
        lines.append(ch.to_extinf())
        lines.extend(ch.extras)
        lines.append(ch.url)
    return "\n".join(lines) + "\n"
