from subs2cia.sources import AVSFile
from subs2cia.Common import Common, interactive_picker, chapter_timestamps
import subs2cia.subtools as subtools
from subs2cia.ffmpeg_tools import ffmpeg_trim_audio_clip_atrim_encode, ffmpeg_get_frame_fast, ffmpeg_trim_video_clip_directcopy

from typing import List, Union
from pathlib import Path
import concurrent.futures
import csv
import logging
import os
import tqdm
import unicodedata as ud
from collections import defaultdict

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

        self.subdata = None

        # This is set to True later if there aren't any usable subtitles
        self.insufficient = False

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

            audiolength = subtools.get_audiofile_duration(self.picked_streams['audio'].demux_file.filepath)
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
        # Cap at 4 workers — more rarely helps and can saturate disk on spinning
        # drives or cause ffmpeg processes to compete for decode bandwidth.
        audio_file = (
            self.picked_streams['audio'].demux_file.filepath if export_audio else None
        )
        video_file = (
            self.picked_streams['video'].file.filepath if (export_screenshot or export_video) else None
        )

        def export_card_media(row):
            group = row['_group']
            if export_audio:
                outpath = row['_audio_outpath']
                if outpath.exists():
                    logging.warning(f"Already exists: {outpath}")
                else:
                    ffmpeg_trim_audio_clip_atrim_encode(
                        input_file=audio_file,
                        stream_index=0,
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

        # Scale workers to available CPU cores. Override with SUBS2CIA_WORKERS env var.
        _env_workers = os.environ.get("SUBS2CIA_WORKERS", "")
        if _env_workers.isdigit():
            n_workers = min(int(_env_workers), len(rows)) if rows else 1
        else:
            n_workers = min(os.cpu_count() or 4, len(rows)) if rows else 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(export_card_media, row): i for i, row in enumerate(rows)}
            for future in tqdm.tqdm(concurrent.futures.as_completed(futures), total=len(rows), desc="Exporting cards"):
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
            for row in rows:
                csvw.writerow([row.get(col, '') for col in csv_columns])

