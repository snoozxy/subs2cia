# subs2cia (snoozxy fork)

Fork of [mattvsjapan/subs2cia](https://github.com/mattvsjapan/subs2cia). See upstream for full documentation.

Install this fork (required — upstream lacks these changes):

```bash
pip install git+https://github.com/snoozxy/subs2cia.git
```

## Changes vs upstream

### Fast audio clip export (`srs`)

Audio clips are trimmed with **input-side seek** (`-ss` before decode) instead of decoding from `t=0` on every card. Per-card cost drops from O(position-in-file) to O(clip-length). On a 24-minute episode with hundreds of cards this is the single largest speedup.

`srs` also **skips the serial full-audio FLAC demux** — clips are read directly from the source container using the real audio stream index (`-ai`). No large temp FLAC file, no upfront encode pass.

Seeking is packet-aligned (a few ms tolerance). Padding (`-p`) absorbs this in practice.

### Parallel card export

`srs` export runs all per-card ffmpeg calls concurrently (one thread per card, each spawning an ffmpeg subprocess).

Worker count defaults to `os.cpu_count()`. Override with:

```bash
SUBS2CIA_WORKERS=8 subs2cia srs ...
```

When processing multiple episodes in parallel (see below), per-episode card workers scale down automatically to avoid oversubscribing CPU.

### Episode-level batch parallelism

Both `condense` and `srs` can process multiple input groups (episodes) concurrently:

```bash
# 24-episode batch: 4 episodes at a time
subs2cia srs -b -j 4 -i "episodes/*.mkv" -ai 1 -p 500 -N -d out_srs/
```

Priority: `SUBS2CIA_JOBS` env var → `-j/--jobs` CLI flag → `SUBS2CIA_JOBS` in `~/.dojo_hw_cache.json` → heuristic (`min(cpu_count // 2, 4)`).

Interactive mode (`-ma`) always runs serially.

### Hardware-accelerated screenshot decode

For long files (movies, 10hr+ YouTube videos), seeking to a timestamp for a screenshot is a major bottleneck. `SUBS2CIA_HWACCEL` enables GPU-accelerated decode for screenshot seeks:

```bash
SUBS2CIA_HWACCEL=cuda subs2cia srs ...    # NVIDIA
SUBS2CIA_HWACCEL=d3d11va subs2cia srs ...  # AMD / Intel (Windows)
```

### dojo-prompts integration

If you use [dojo-prompts](https://github.com/snoozxy/dojo-prompts), run `hw_probe.py` once and settings are picked up automatically from `~/.dojo_hw_cache.json`:

| Cache key | Used for |
|---|---|
| `SUBS2CIA_HWACCEL` | GPU decode for screenshot seeks |
| `SUBS2CIA_WORKERS` | Per-episode card export parallelism |
| `SUBS2CIA_JOBS` | Cross-episode batch parallelism |

No env vars needed after probing. Re-run `hw_probe.py` after hardware changes or if the cache is older than 30 days.

### Example: full Anki deck pipeline

```bash
# 1. Hardware probe (once per machine)
python3 dojo-prompts/scripts/hw_probe.py --check || python3 dojo-prompts/scripts/hw_probe.py

# 2. Optional 480p transcode
python3 dojo-prompts/scripts/transcode_batch.py "$VIDEO_DIR" "$VIDEO_DIR/480p" --encoder auto

# 3. Sync subtitles, then export cards (batch mode, parallel episodes)
PYTHONUTF8=1 subs2cia srs -b -j 4 \
  -i "$VIDEO_DIR/480p/show_01.mkv" synced_subs/show_01.srt \
  -ai <jp_audio_index> -p 500 -N -d out_srs --export-header-row
```

On Windows, use the full path to `subs2cia.exe` and prefix with `PYTHONUTF8=1` (see dojo-prompts `CLAUDE.md`).

## Environment variables

| Variable | Effect | Default |
|---|---|---|
| `SUBS2CIA_WORKERS` | Max threads per episode for card export | `os.cpu_count()` |
| `SUBS2CIA_JOBS` | Max episodes processed in parallel (`-b` batch) | `min(cpu_count // 2, 4)` |
| `SUBS2CIA_HWACCEL` | Hardware decoder for screenshot seeks (`cuda`, `d3d11va`, `none`) | none |

CLI equivalents: `-j <count>` for episode jobs. Worker count has no CLI flag (env/cache only).

## Performance tips

- **Batch anime decks**: use `-b -j 4` (tune `-j` to your core count; 4 is a good starting point on 16-core machines).
- **Single long movie**: `-j 1` is fine; the per-card parallelism does the heavy lifting.
- **Condense many files**: `-b -j N` gives the biggest win since condense has no internal parallelism.
- **Re-run after probe**: if you upgrade subs2cia, re-run `hw_probe.py` so `SUBS2CIA_JOBS` is populated in the cache.
