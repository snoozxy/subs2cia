# subs2cia (snoozxy fork)

Fork of [mattvsjapan/subs2cia](https://github.com/mattvsjapan/subs2cia). See upstream for full documentation.

Install this fork (required — upstream lacks these changes):
```bash
pip install git+https://github.com/snoozxy/subs2cia.git
```

## Changes vs upstream

### Parallel card export

`srs` export now runs all per-card ffmpeg calls concurrently instead of one at a time. For a 12-episode series this cuts export time by 3–4× on a typical machine.

Worker count scales to `os.cpu_count()` automatically. Override with:
```bash
SUBS2CIA_WORKERS=8 subs2cia srs ...
```

### Hardware-accelerated screenshot decode

For long files (movies, 10hr+ YouTube videos), seeking to a timestamp for a screenshot is the main bottleneck. Setting `SUBS2CIA_HWACCEL` enables GPU-accelerated decode for all screenshot seeks:

```bash
SUBS2CIA_HWACCEL=cuda subs2cia srs ...   # NVIDIA
SUBS2CIA_HWACCEL=d3d11va subs2cia srs ... # AMD / Intel (Windows)
```

If you use [dojo-prompts](https://github.com/snoozxy/dojo-prompts), run `hw_probe.py` once and both settings are picked up automatically from `~/.dojo_hw_cache.json` — no env vars needed.
