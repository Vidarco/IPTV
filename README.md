# Iranian / Persian IPTV Playlist

Auto-aggregated, validated, and categorized M3U playlist of Iranian and Persian-language
TV channels from public sources. Refreshed weekly via GitHub Actions.

## Use it on your Samsung TV

1. Install an M3U-capable IPTV app from the Samsung Tizen App Store.
2. Open the app and add a playlist with this URL:

   ```
   https://raw.githubusercontent.com/Vidarco/IPTV/main/output/iran-persian.m3u
   ```
3. Channels are grouped by category (News, Entertainment, Movies, Music, Sports,
   Kids, Religious, Local, General). The app reads `group-title` and shows them
   as folders.

### Which app to use

| App | Plays standard streams | Honors `#EXTVLCOPT:http-referrer` (needed for some channels via [manual.m3u](manual.m3u)) |
|---|---|---|
| **M3U IPTV** (free, basic) | ✅ | ❌ |
| **OTT Navigator** | ✅ | ✅ |
| **TiviMate** | ✅ | ✅ |
| **IPTV Smarters Pro** | ✅ | ✅ |
| **VLC for Samsung** | ✅ | ✅ |

If you want to play channels that need a Referer header (anything we add to
[manual.m3u](manual.m3u) for aparatchi-hosted streams), you need an app from the
second column. The basic "M3U IPTV" app is fine if you only use the auto-aggregated
upstream channels.

## How it works

```
sources.yml ──► fetch ──► filter ──► validate ──► categorize ──► output/iran-persian.m3u
                                  (HTTP + ffprobe)
```

- **fetch** pulls raw M3U files from a curated list of upstream sources (`sources.yml`).
- **filter** keeps only entries with country=IR, language=fas/per, or a Persian/Iranian
  channel name; then dedupes by stream URL.
- **validate** probes each URL with HTTP HEAD and `ffprobe` to confirm an actual A/V
  stream is being served. Dead links are dropped.
- **categorize** maps each channel into one of: News, Entertainment, Movies, Music,
  Sports, Kids, Religious, General — using rules in `categories.yml`.
- **build** writes the final `output/iran-persian.m3u` plus a JSON report.

## Run locally

Requires Python 3.11+ and (optionally) `ffmpeg` on PATH for stream-level validation.

```powershell
# install deps to a project-local folder (no venv needed)
python -m pip install --target .deps httpx pyyaml tqdm

# run the full pipeline
python run.py all
```

Individual stages: `python run.py fetch | filter | validate | build`.

The portable embeddable Python distribution is supported — `run.py` bootstraps `sys.path`
itself and picks up `.deps/` automatically.

## Updating

- **Weekly auto-refresh**: GitHub Actions runs `.github/workflows/refresh.yml` every
  Sunday at 04:00 UTC, regenerates the playlist, and commits it. The raw URL above
  always serves the latest version.
- **Manual refresh**: trigger the workflow from the Actions tab (`workflow_dispatch`),
  or run `python run.py all` locally and push.
- **Add/remove sources**: edit `sources.yml`. Set `enabled: false` to skip without
  deleting.
- **Tune categorization**: edit `categories.yml`. Rules are evaluated top-to-bottom;
  first match wins. Channels matching no rule fall into "General".

## Geo-blocked channels

This playlist is built and validated from a German GitHub Actions runner, so it only
includes channels reachable without a VPN from a European endpoint. Some Iranian state
broadcasters that geo-fence to Iran or to specific regions are deliberately excluded.

If you want to add geo-restricted channels, you'll need to either:
- run the validator from an exit in the relevant region (self-hosted runner), or
- build a proxy/restream layer (out of scope for this version).

## Repo layout

```
.
├── .github/workflows/refresh.yml   # weekly cron
├── sources.yml                      # upstream M3U URLs
├── categories.yml                   # category rules
├── run.py                           # pipeline entrypoint
├── src/
│   ├── m3u.py         # M3U parse/serialize
│   ├── fetch.py       # download upstream playlists
│   ├── filter.py      # keep IR/fas channels, dedupe
│   ├── validate.py    # HTTP + ffprobe probing
│   ├── categorize.py  # apply categories.yml rules
│   └── build.py       # write final output
└── output/
    ├── iran-persian.m3u   # the playlist your TV reads
    └── report.json        # per-channel metadata + counts
```

## License

The code in this repo is MIT. Channel availability and licensing are the responsibility
of the respective broadcasters; this project only redistributes publicly published M3U
URLs.
