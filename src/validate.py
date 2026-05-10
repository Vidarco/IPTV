"""Validate that each candidate stream URL is alive.

Strategy:
    1. HTTP HEAD/GET probe with a short timeout (cheap, kills obvious 404s).
    2. If ffprobe is on PATH, run it against the URL to confirm an actual
       audio/video stream is returned (not an HTML "offline" placeholder).
    3. Aggregate results into a JSON report and a list of alive Channels.

Designed to be re-run weekly; takes ~1-3 minutes for ~250 channels with
default concurrency.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from src.fetch import load_sources, fetch_all
from src.filter import filter_all
from src.m3u import Channel


_EXTVLCOPT_RE = re.compile(r"#EXTVLCOPT:http-([\w-]+)=(.+)$", re.IGNORECASE)
_HEADER_NAMES = {"referrer": "Referer", "user-agent": "User-Agent"}


def channel_headers(ch: Channel) -> dict[str, str]:
    """Pull per-channel HTTP headers out of #EXTVLCOPT lines preserved in extras.

    Supports http-referrer and http-user-agent — the two values most upstreams
    care about. Empty dict means "no special headers".
    """
    out: dict[str, str] = {}
    for line in ch.extras:
        m = _EXTVLCOPT_RE.match(line.strip())
        if not m:
            continue
        key = m.group(1).lower()
        val = m.group(2).strip()
        header_name = _HEADER_NAMES.get(key)
        if header_name:
            out[header_name] = val
    return out


HTTP_TIMEOUT = 10.0
HTTP_CONCURRENCY = 40
FFPROBE_TIMEOUT = 12  # seconds, passed to ffprobe via -timeout (microseconds * 1e6)
FFPROBE_CONCURRENCY = 12


@dataclass
class CheckResult:
    url: str
    name: str
    http_ok: bool
    http_status: int | None
    http_error: str
    ffprobe_ok: bool
    ffprobe_error: str
    elapsed_ms: int

    @property
    def alive(self) -> bool:
        # If ffprobe ran successfully, trust it. If ffprobe couldn't run
        # (binary missing or skipped), fall back to HTTP outcome.
        if self.ffprobe_ok:
            return True
        if self.ffprobe_error == "skipped":
            return self.http_ok
        return False


async def _http_probe(client: httpx.AsyncClient, ch: Channel) -> tuple[bool, int | None, str]:
    extra_headers = channel_headers(ch)
    try:
        r = await client.head(ch.url, headers=extra_headers)
        if r.status_code in (405, 501, 403):
            r = await client.get(ch.url, headers={**extra_headers, "Range": "bytes=0-1023"})
        if 200 <= r.status_code < 400:
            return True, r.status_code, ""
        return False, r.status_code, f"HTTP {r.status_code}"
    except httpx.TimeoutException:
        return False, None, "timeout"
    except httpx.HTTPError as e:
        return False, None, type(e).__name__
    except Exception as e:
        return False, None, f"{type(e).__name__}: {e}"


async def _http_probe_all(channels: list[Channel]) -> dict[str, tuple[bool, int | None, str]]:
    results: dict[str, tuple[bool, int | None, str]] = {}
    sem = asyncio.Semaphore(HTTP_CONCURRENCY)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; iran-persian-iptv/0.1)",
    }
    timeout = httpx.Timeout(HTTP_TIMEOUT, connect=HTTP_TIMEOUT)
    async with httpx.AsyncClient(
        timeout=timeout, headers=headers, follow_redirects=True, http2=False
    ) as client:
        async def worker(ch: Channel) -> None:
            async with sem:
                results[ch.url] = await _http_probe(client, ch)

        await asyncio.gather(*(worker(c) for c in channels))
    return results


def _ffprobe_one(url: str, headers: dict[str, str] | None = None) -> tuple[bool, str]:
    """Returns (ok, error_msg). ok=True means a video/audio stream was found."""
    cmd = ["ffprobe", "-v", "error"]
    if headers:
        # ffmpeg expects header lines separated by \r\n
        cmd += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
    cmd += [
        "-rw_timeout", str(FFPROBE_TIMEOUT * 1_000_000),
        "-show_entries", "stream=codec_type",
        "-of", "default=nw=1:nk=1",
        "-i", url,
    ]
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT + 5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "ffprobe timeout"
    except FileNotFoundError:
        return False, "skipped"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

    if out.returncode != 0:
        err = (out.stderr or "").strip().splitlines()[-1:] or [""]
        return False, err[0][:120]
    types = {line.strip() for line in out.stdout.splitlines() if line.strip()}
    if "video" in types or "audio" in types:
        return True, ""
    return False, "no av stream"


def _ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


async def _ffprobe_all(
    channels: list[Channel], http_results: dict[str, tuple[bool, int | None, str]]
) -> dict[str, tuple[bool, str]]:
    if not _ffprobe_available():
        print("[validate] ffprobe not on PATH — using HTTP-only validation", file=sys.stderr)
        return {ch.url: (False, "skipped") for ch in channels}

    sem = asyncio.Semaphore(FFPROBE_CONCURRENCY)
    loop = asyncio.get_running_loop()
    results: dict[str, tuple[bool, str]] = {}

    async def worker(ch: Channel) -> None:
        # Don't waste ffprobe on URLs that already failed HTTP.
        http_ok = http_results.get(ch.url, (False, None, ""))[0]
        if not http_ok:
            results[ch.url] = (False, "http failed")
            return
        async with sem:
            extra = channel_headers(ch) or None
            ok, err = await loop.run_in_executor(None, _ffprobe_one, ch.url, extra)
            results[ch.url] = (ok, err)

    await asyncio.gather(*(worker(c) for c in channels))
    return results


def validate_channels(channels: list[Channel]) -> list[Channel]:
    """Probe all channels and return the alive subset (in original order).

    Side effect: prints progress to stderr. The full per-channel report is
    written by `run()` to cache/validation_report.json.
    """
    print(f"[validate] probing {len(channels)} channels...", file=sys.stderr)
    t0 = time.time()
    http = asyncio.run(_http_probe_all(channels))
    t_http = time.time() - t0
    http_ok = sum(1 for v in http.values() if v[0])
    print(f"[validate] HTTP: {http_ok}/{len(channels)} reachable ({t_http:.1f}s)", file=sys.stderr)

    t0 = time.time()
    ff = asyncio.run(_ffprobe_all(channels, http))
    t_ff = time.time() - t0
    ff_ok = sum(1 for v in ff.values() if v[0])
    skipped = all(v[1] == "skipped" for v in ff.values())
    if skipped:
        print("[validate] ffprobe stage skipped (binary missing)", file=sys.stderr)
    else:
        print(
            f"[validate] ffprobe: {ff_ok}/{http_ok} streams confirmed ({t_ff:.1f}s)",
            file=sys.stderr,
        )

    results: list[CheckResult] = []
    for ch in channels:
        h_ok, h_status, h_err = http.get(ch.url, (False, None, "no result"))
        f_ok, f_err = ff.get(ch.url, (False, "no result"))
        results.append(
            CheckResult(
                url=ch.url,
                name=ch.name,
                http_ok=h_ok,
                http_status=h_status,
                http_error=h_err,
                ffprobe_ok=f_ok,
                ffprobe_error=f_err,
                elapsed_ms=0,
            )
        )

    alive_urls = {r.url for r in results if r.alive}
    alive = [c for c in channels if c.url in alive_urls]
    print(f"[validate] alive: {len(alive)}/{len(channels)}", file=sys.stderr)

    # Stash the report on a module-level for run() to pick up without re-probing.
    validate_channels._last_report = results  # type: ignore[attr-defined]
    return alive


def run(root: Path) -> None:
    srcs = load_sources(root / "sources.yml")
    fetched = fetch_all(srcs)
    candidates = filter_all(fetched, srcs)
    alive = validate_channels(candidates)

    cache = root / "cache"
    cache.mkdir(exist_ok=True)
    report = getattr(validate_channels, "_last_report", [])
    (cache / "validation_report.json").write_text(
        json.dumps([asdict(r) for r in report], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    from src.m3u import serialize
    (cache / "alive.m3u").write_text(serialize(alive), encoding="utf-8")
    print(f"[validate] wrote alive.m3u and validation_report.json to {cache}", file=sys.stderr)
