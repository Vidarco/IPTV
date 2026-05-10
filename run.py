"""Single entrypoint: bootstraps sys.path then dispatches to a pipeline stage.

Usage (from c:\\Projects\\IPTV):
    python run.py fetch
    python run.py filter
    python run.py validate
    python run.py build
    python run.py all       # fetch -> filter -> validate -> build

Designed to work with both a normal Python install and the embeddable Python
distribution (which ignores PYTHONPATH). If a local .deps/ folder exists,
it's added to sys.path so users can `pip install --target .deps ...` instead
of using a venv.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))
_DEPS = _ROOT / ".deps"
if _DEPS.is_dir():
    sys.path.insert(0, str(_DEPS))


def _usage() -> None:
    print(__doc__, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    if len(sys.argv) < 2:
        _usage()
    stage = sys.argv[1]

    if stage == "fetch":
        from src import fetch
        srcs = fetch.load_sources(_ROOT / "sources.yml")
        fetch.fetch_all(srcs)
        return

    if stage == "filter":
        from src import fetch, filter as filter_mod
        from src.m3u import serialize
        srcs = fetch.load_sources(_ROOT / "sources.yml")
        fetched = fetch.fetch_all(srcs)
        candidates = filter_mod.filter_all(fetched, srcs)
        cache_dir = _ROOT / "cache"
        cache_dir.mkdir(exist_ok=True)
        out = cache_dir / "candidates.m3u"
        out.write_text(serialize(candidates), encoding="utf-8")
        print(f"\n[filter] wrote {len(candidates)} candidates to {out}", file=sys.stderr)
        return

    if stage == "validate":
        from src import validate
        validate.run(_ROOT)
        return

    if stage == "build":
        from src import build
        build.run(_ROOT)
        return

    if stage == "all":
        from src import fetch, filter as filter_mod, validate, build
        from src.m3u import serialize
        srcs = fetch.load_sources(_ROOT / "sources.yml")
        fetched = fetch.fetch_all(srcs)
        candidates = filter_mod.filter_all(fetched, srcs)
        cache_dir = _ROOT / "cache"
        cache_dir.mkdir(exist_ok=True)
        (cache_dir / "candidates.m3u").write_text(serialize(candidates), encoding="utf-8")
        alive = validate.validate_channels(candidates)
        build.build_outputs(_ROOT, alive)
        return

    _usage()


if __name__ == "__main__":
    main()
