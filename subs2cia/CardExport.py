from subs2cia.sources import AVSFile
from subs2cia.Common import Common, interactive_picker, chapter_timestamps
import subs2cia.subtools as subtools
from subs2cia.ffmpeg_tools import (
    ffmpeg_trim_audio_clip_atrim_encode,
    ffmpeg_get_frame_fast,
    ffmpeg_trim_video_clip_directcopy,
    ffmpeg_batch_export_audio_clips,
    ffmpeg_batch_export_frames,
)

from typing import List, Union
from pathlib import Path
import concurrent.futures
import csv
import json
import logging
import os
import tqdm
import unicodedata as ud
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

_HW_CACHE_PATH = Path.home() / ".dojo_hw_cache.json"


def _load_hw_cache():
    """Return recommendations dict from ~/.dojo_hw_cache.json, or {}."""
    try:
        with open(_HW_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f).get("recommendations", {})
    except Exception:
        return {}


def _resolve_card_workers(hw_cache: dict, row_count: int, episode_jobs: int = 1) -> int:
    """Resolve per-episode card export worker count."""
    if row_count == 0:
        return 1

    env_workers = os.environ.get("SUBS2CIA_WORKERS", "")
    if env_workers.isdigit():
        base_workers = int(env_workers)
    else:
        cached_workers = hw_cache.get("SUBS2CIA_WORKERS", "")
        if str(cached_workers).isdigit():
            base_workers = int(cached_workers)
        else:
            base_workers = os.cpu_count() or 4

    if episode_jobs > 1:
        base_workers = max(1, base_workers // episode_jobs)

    return min(base_workers, row_count)


class CardExport(Common):
    def __init__(self, sources: List[AVSFile], outdir: Path, outstem: Union[str, None], condensed_video: bool, padding: int,
                 demux_overwrite_existing: bool, overwrite_existing_generated: bool,
                 keep_temporaries: bool, target_lang: str, out_audioext: str,
                 use_all_subs: bool, subtitle_regex_filter: str,
                 # subtitle_regex_substrfilter: str,
                 # subtitle_regex_substrfilter_nokeep: bool,
                 audio_stream_index: int, subtitle_stream_index: int,
                 ignore_range: Union[List[List[int]], None], ignore_chapters: Union[List[str], None],
                 bitrate: Union[int, None], mono_channel: bool, interactive: bool, out_audiocodec: str,

                 normalize_audio: bool,
                 media_dir: str|None,
                 no_export_audio: bool,
                 no_export_screenshot: bool,
                 export_video: bool,
                 export_header_row: bool,
<<<<<<< Updated upstream
                 episode_jobs: int = 1,
=======
                 workers: Union[int, None] = None,
                 batch_size: int = 50,
                 no_batch: bool = False,
>>>>>>> Stashed changes
                 ):
        super(CardExport, self).__init__(
            sources=sources,
            outdir=outdir,
            outstem=outstem,
            condensed_video=condensed_video,
            padding=padding,
            demux_overwrite_existing=demux_overwrite_existing,
            overwrite_existing_generated=overwrite_existing_generated,
            keep_temporaries=keep_temporaries,
            target_lang=target_lang,
            out_audioext=out_audioext,
            use_all_subs=use_all_subs,
            subtitle_regex_filter=subtitle_regex_filter,
            # subtitle_regex_substrfilter=subtitle_regex_substrfilter,
            # subtitle_regex_substrfilter_nokeep=subtitle_regex_substrfilter_nokeep,
            audio_stream_index=audio_stream_index,
            subtitle_stream_index=subtitle_stream_index,
            ignore_range=ignore_range,
            ignore_chapters=ignore_chapters,
            bitrate=bitrate,
            mono_channel=mono_channel,
            interactive=interactive,
            out_audiocodec=out_audiocodec
        )

        self.normalize_audio = normalize_audio

        self.media_dir = media_dir
        self.export_audio = not no_export_audio
        self.export_screenshot = not no_export_screenshot
        self.export_video = export_video
        self.export_header_row = export_header_row
<<<<<<< Updated upstream
        self.episode_jobs = max(1, episode_jobs)
=======
        self.workers = workers
        self.batch_size = max(1, batch_size)
        self.no_batch = no_batch
>>>>>>> Stashed changes

        self.subdata = None

        # This is set to True later if there aren't any usable subtitles
        self.insufficient = False

    def choose_audio(self, interactive: bool):
        """Pick audio without demuxing — srs clips read directly from the source container."""
        if len(self.partitioned_streams['audio']) == 0:
            logging.warning(f"Couldn't find audio streams in input files")
            return

        k = 'audio'
        while self.picked_streams[k] is None:
            if interactive and len(self.partitioned_streams['audio']) > 1:
                self.picked_streams['audio'] = interactive_picker(
                    self.sources, self.partitioned_streams, 'audio')
            else:
                try:
                    self.picked_streams[k] = next(self.pickers[k])
                except StopIteration:
                    logging.critical("Inputs don't contain usable audio")
                    self.insufficient = True
                    return

    def choose_subtitle(self, interactive):
        if len(self.partitioned_streams['subtitle']) == 0:
            logging.warning(f"Couldn't find audio streams in input files")
            return
        # if interactive and len(self.partitioned_streams['subtitle']) > 1:
        #     while self.picked_streams['subtitle'] is None:
        #         self.picked_streams['subtitle'] = interactive_picker(self.sources, self.partitioned_streams, 'subtitle')
        #     return

        k = 'subtitle'
        while self.picked_streams[k] is None:
            if interactive and len(self.partitioned_streams['subtitle']) > 1:
                self.picked_streams['subtitle'] = interactive_picker(self.sources, self.partitioned_streams,
                                                                     'subtitle')
            else:
                try:
                    self.picked_streams[k] = next(self.pickers[k])
                except StopIteration as s:
                    logging.critical(f"Input files {self.sources} don't contain usable subtitles")
                    self.insufficient = True
                    return
            subfile = self.picked_streams[k].demux(overwrite_existing=self.demux_overwrite_existing)
            ignore_range = (self.ignore_range or []) + chapter_timestamps(self.picked_streams[k].file, self.ignore_chapters or [])
            if subfile is None:
                logging.warning(f"Error while demuxing {self.picked_streams[k]}")
                self.picked_streams[k] = None

            audiolength = self.picked_streams['audio'].get_duration_ms()
            subdata = subtools.SubtitleManipulator(subfile.filepath,
                                                   threshold=0, padding=self.padding,
                                                   ignore_range=ignore_range, audio_length=audiolength)
            subdata.load(include_all=self.use_all_subs, regex=self.subtitle_regex_filter,
                         substrreplace_regex='', substrreplace_nokeepchanges=False,
                         srs_mode=True)
            if subdata.ssadata is None:
                logging.warning(f"Problem loading subtitle data from {self.picked_streams[k]}")
                self.picked_streams[k] = None
                continue

            self.subdata = subdata

    def _resolve_workers(self) -> int:
        if self.workers is not None:
            return max(1, self.workers)
        return min(8, os.cpu_count() or 4)

    @staticmethod
    def _chunks(items: list, size: int):
        for i in range(0, len(items), size):
            yield items[i:i + size]

    def _export_card_media(self, task: dict) -> None:
        """Per-card fallback export (audio, screenshot, optional video clip)."""
        if task.get('export_audio') and task['audio_outpath'] and not task['audio_outpath'].exists():
            ffmpeg_trim_audio_clip_atrim_encode(
                input_file=task['audio_input'],
                stream_index=0,
                timestamp_start=task['start'],
                timestamp_end=task['end'],
                quality=self.quality,
                to_mono=self.to_mono,
                normalize_audio=self.normalize_audio,
                outpath=task['audio_outpath'],
            )

        if task.get('export_screenshot') and task['screenshot_outpath'] and not task['screenshot_outpath'].exists():
            ffmpeg_get_frame_fast(
                task['video_input'],
                timestamp=task['screenshot_ts'],
                outpath=task['screenshot_outpath'],
                w=-1,
                h=-1,
            )

        if task.get('export_video') and task['video_outpath'] and not task['video_outpath'].exists():
            ffmpeg_trim_video_clip_directcopy(
                task['video_input'],
                timestamp_start=task['start'],
                timestamp_end=task['end'],
                quality=None,
                outpath=task['video_outpath'],
            )

    def _export_audio_batch(self, chunk: list) -> None:
        clips = [(t['start'], t['end'], t['audio_outpath']) for t in chunk]
        try:
            ffmpeg_batch_export_audio_clips(
                input_file=chunk[0]['audio_input'],
                stream_index=0,
                clips=clips,
                quality=self.quality,
                to_mono=self.to_mono,
                normalize_audio=self.normalize_audio,
            )
        except Exception as e:
            logging.warning(f"Batch audio export failed ({len(chunk)} clips), falling back per-card: {e}")
            for task in chunk:
                self._export_card_media({**task, 'export_screenshot': False, 'export_video': False})

    def _export_screenshot_batch(self, chunk: list) -> None:
        items = [(t['screenshot_ts'], t['screenshot_outpath']) for t in chunk]
        try:
            ffmpeg_batch_export_frames(
                videofile=chunk[0]['video_input'],
                items=items,
                w=-1,
                h=-1,
            )
        except Exception as e:
            logging.warning(f"Batch screenshot export failed ({len(chunk)} frames), falling back per-card: {e}")
            for task in chunk:
                self._export_card_media({**task, 'export_audio': False, 'export_video': False})

    def _export_media_batched(self, media_tasks: list, workers: int) -> None:
        """Export media using chunked ffmpeg batches, with parallel batch jobs."""
        audio_tasks = [t for t in media_tasks if t.get('export_audio')]
        screenshot_tasks = [t for t in media_tasks if t.get('export_screenshot')]
        video_tasks = [t for t in media_tasks if t.get('export_video')]

        jobs = []
        for chunk in self._chunks(audio_tasks, self.batch_size):
            jobs.append(('audio', chunk))
        for chunk in self._chunks(screenshot_tasks, self.batch_size):
            jobs.append(('screenshot', chunk))

        def run_batch(job):
            kind, chunk = job
            if kind == 'audio':
                self._export_audio_batch(chunk)
            else:
                self._export_screenshot_batch(chunk)

        if jobs:
            logging.info(
                f"Batch export: {len(audio_tasks)} audio + {len(screenshot_tasks)} screenshots "
                f"in {len(jobs)} ffmpeg jobs (batch_size={self.batch_size}, workers={workers})"
            )
            if workers == 1:
                for job in tqdm.tqdm(jobs, desc="Exporting batches"):
                    run_batch(job)
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(run_batch, job) for job in jobs]
                    for future in tqdm.tqdm(as_completed(futures), total=len(futures), desc="Exporting batches"):
                        future.result()

        if video_tasks:
            logging.info(f"Exporting {len(video_tasks)} video clips per-card")
            if workers == 1:
                for task in tqdm.tqdm(video_tasks, desc="Exporting video"):
                    self._export_card_media(task)
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(self._export_card_media, t) for t in video_tasks]
                    for future in tqdm.tqdm(as_completed(futures), total=len(futures), desc="Exporting video"):
                        future.result()

    def export(self):

        # expose these as options at some point
        # will need to rename these if they are going to become cli switches so they don't conflict
        forbidden_chars = ['[' , ']' , '<' , '>' , ':' , '"' , '/' , '?' , '*' , '^' , '\\' , '|']  # see fn disallowed_char in https://github.com/ankitects/anki/blob/main/rslib/src/media/files.rs
        forbidden_chars = {ord(c): '' for c in forbidden_chars}

        csv_columns = [
            'text',
            'timestamps',
            'audioclip',
            'screenclip',
            'videoclip',
            'sources',
            'context',
        ]

        export_audio = self.export_audio and self.picked_streams['audio'] is not None
        export_screenshot = self.export_screenshot and self.picked_streams['video'] is not None
        export_video = self.export_video and self.picked_streams['video'] is not None
        export_header_row = self.export_header_row

        # path to write the csv (or tsv) file to
        csv_outpath = self.outdir / (self.outstem + ".tsv")

        # path to write media files to (exported screenshots, audio clips, video clips)
        if self.media_dir is not None:
            media_dir = Path(self.media_dir)
        else:
            media_dir = self.outdir

        # where to get screenshot. 0=start, 1=end, 0.5=middle
        lbda = 0.0

        # we only need to worry about creating the media dir if we are exporting any media
        if export_audio or export_screenshot or export_video:
            if not media_dir.exists():
                media_dir.mkdir(exist_ok=True)
            if not media_dir.is_dir():
                raise RuntimeError(f"Not a directory: {media_dir}")

        # ── Pass 1: collect groups and pre-compute all row metadata ───────────
        non_ephemeral_groups = [g for g in self.subdata.groups if not g.contains_only_ephemeral]
        group_texts = [g.events[0].plaintext for g in non_ephemeral_groups]

        rows = []
        for i, group in enumerate(non_ephemeral_groups):
            media_stem = media_dir / (
                ud.normalize('NFC', self.outstem).translate(forbidden_chars)
                + f"_{group.group_range[0]}-{group.group_range[1]}"
            )
            start_idx = max(0, i - 15)
            end_idx = min(len(group_texts), i + 16)
            row = {
                'text': group.events[0].plaintext,
                'timestamps': f"{group.group_range[0]}-{group.group_range[1]}",
                'sources': ",".join([s.filepath.name for s in self.sources]),
                'context': 'Sentence context: ' + ' | '.join(group_texts[start_idx:end_idx]),
                '_group': group,
                '_media_stem': media_stem,
            }
            if export_audio:
                outpath = Path(str(media_stem) + '.mp3')
                row['audioclip'] = f"[sound:{outpath.name}]"
                row['_audio_outpath'] = outpath
            if export_screenshot:
                outpath = Path(str(media_stem) + '.jpg')
                row['screenclip'] = f"<img src='{outpath.name}'>"
                row['_screenshot_outpath'] = outpath
            if export_video:
                outpath = Path(str(media_stem) + '.mp4')
                row['videoclip'] = f"[sound:{outpath.name}]"
                row['_video_outpath'] = outpath
            rows.append(row)

        # ── Pass 2: export media in parallel (one thread per card) ────────────
        # ffmpeg subprocesses are I/O-bound relative to Python; threads work well.
        hw_cache = _load_hw_cache()
        audio_file = (
            self.picked_streams['audio'].get_source_path() if export_audio else None
        )
        audio_stream_index = (
            self.picked_streams['audio'].get_ffmpeg_stream_index() if export_audio else 0
        )
        video_file = (
            self.picked_streams['video'].file.filepath if (export_screenshot or export_video) else None
        )

        # Resolve hwaccel: env var > hw cache > none
        _hw_accel = os.environ.get("SUBS2CIA_HWACCEL") or hw_cache.get("SUBS2CIA_HWACCEL", "")
        _hwaccel = _hw_accel if _hw_accel and _hw_accel.lower() not in ("", "none", "off") else None

        def export_card_media(row):
            group = row['_group']
            if export_audio:
                outpath = row['_audio_outpath']
                if outpath.exists():
                    logging.warning(f"Already exists: {outpath}")
                else:
                    ffmpeg_trim_audio_clip_atrim_encode(
                        input_file=audio_file,
                        stream_index=audio_stream_index,
                        timestamp_start=group.group_range[0],
                        timestamp_end=group.group_range[1],
                        quality=self.quality,
                        to_mono=self.to_mono,
                        normalize_audio=self.normalize_audio,
                        outpath=outpath,
                    )
            if export_screenshot:
                outpath = row['_screenshot_outpath']
                if outpath.exists():
                    logging.info(f"Already exists: {outpath}")
                else:
                    ffmpeg_get_frame_fast(
                        video_file,
                        timestamp=(1 - lbda) * group.group_range[0] + lbda * group.group_range[1],
                        outpath=outpath,
                        w=-1,
                        h=-1,
                        hwaccel=_hwaccel,
                    )
            if export_video:
                outpath = row['_video_outpath']
                if outpath.exists():
                    logging.info(f"Already exists: {outpath}")
                else:
                    ffmpeg_trim_video_clip_directcopy(
                        video_file,
                        timestamp_start=group.group_range[0],
                        timestamp_end=group.group_range[1],
                        quality=None,
                        outpath=outpath,
                    )

        n_workers = _resolve_card_workers(hw_cache, len(rows), self.episode_jobs)
        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(export_card_media, row): i for i, row in enumerate(rows)}
            desc = f"Exporting cards ({self.outstem})"
            for future in tqdm.tqdm(concurrent.futures.as_completed(futures), total=len(rows), desc=desc):
                try:
                    future.result()
                except Exception as e:
                    logging.error(f"Card export failed: {e}")

        # ── Pass 3: write TSV in original card order ───────────────────────────
        private_keys = {'_group', '_media_stem', '_audio_outpath', '_screenshot_outpath', '_video_outpath'}
        with open(csv_outpath, 'w', encoding='utf-8', newline='') as f:
            csvw = csv.writer(f, delimiter='\t')
            if export_header_row:
                csvw.writerow(csv_columns)
<<<<<<< Updated upstream
            for row in rows:
                csvw.writerow([row.get(col, '') for col in csv_columns])

=======

            group_texts = [
                g.events[0].plaintext
                for g in self.subdata.groups
                if not g.contains_only_ephemeral
            ]

            rows = []
            media_tasks = []
            non_ephemeral_idx = 0
            audio_input = (
                self.picked_streams['audio'].demux_file.filepath
                if export_audio else None
            )
            video_input = (
                self.picked_streams['video'].file.filepath
                if (export_screenshot or export_video) else None
            )

            for group in self.subdata.groups:
                if group.contains_only_ephemeral:
                    continue

                start_ms, end_ms = group.group_range[0], group.group_range[1]
                media_file_stem = media_dir / (
                    ud.normalize('NFC', self.outstem).translate(forbidden_chars)
                    + f"_{start_ms}-{end_ms}"
                )

                row = {
                    'text': group.events[0].plaintext,
                    'timestamps': f"{start_ms}-{end_ms}",
                    'sources': ",".join([s.filepath.name for s in self.sources]),
                }

                if export_audio:
                    audio_outpath = Path(str(media_file_stem) + '.mp3')
                    row['audioclip'] = f"[sound:{audio_outpath.name}]"
                else:
                    audio_outpath = None

                if export_screenshot:
                    screenshot_outpath = Path(str(media_file_stem) + '.jpg')
                    row['screenclip'] = f"<img src='{screenshot_outpath.name}'>"
                else:
                    screenshot_outpath = None

                if export_video:
                    video_outpath = Path(str(media_file_stem) + '.mp4')
                    row['videoclip'] = f"[sound:{video_outpath.name}]"
                else:
                    video_outpath = None

                start_idx = max(0, non_ephemeral_idx - 15)
                end_idx = min(len(group_texts), non_ephemeral_idx + 16)
                row['context'] = 'Sentence context: ' + ' | '.join(group_texts[start_idx:end_idx])
                rows.append(row)

                if export_audio or export_screenshot or export_video:
                    media_tasks.append({
                        'export_audio': export_audio,
                        'export_screenshot': export_screenshot,
                        'export_video': export_video,
                        'start': start_ms,
                        'end': end_ms,
                        'audio_input': audio_input,
                        'video_input': video_input,
                        'audio_outpath': audio_outpath,
                        'screenshot_outpath': screenshot_outpath,
                        'video_outpath': video_outpath,
                        'screenshot_ts': (1 - lbda) * start_ms + lbda * end_ms,
                    })

                non_ephemeral_idx += 1

            workers = self._resolve_workers()
            if media_tasks:
                if self.no_batch:
                    logging.info(f"Per-card export: {len(media_tasks)} cards, {workers} workers")
                    if workers == 1:
                        for task in tqdm.tqdm(media_tasks, desc="Exporting media"):
                            self._export_card_media(task)
                    else:
                        with ThreadPoolExecutor(max_workers=workers) as pool:
                            futures = [pool.submit(self._export_card_media, t) for t in media_tasks]
                            for future in tqdm.tqdm(
                                as_completed(futures), total=len(futures), desc="Exporting media"
                            ):
                                future.result()
                else:
                    self._export_media_batched(media_tasks, workers)

            for row in rows:
                csvw.writerow([row.get(col, '') for col in csv_columns])

>>>>>>> Stashed changes
