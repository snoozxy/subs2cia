import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ffmpeg

from subs2cia.CardExport import _resolve_card_workers
from subs2cia.main import resolve_episode_jobs
from subs2cia.sources import AVSFile, Stream
from subs2cia.subtools import duration_ms_from_stream_info, get_compression_ratio


class PerformanceHelpersTest(unittest.TestCase):
    def test_duration_ms_from_stream_info_time_base(self):
        info = {'time_base': '1/48000', 'duration_ts': 480000}
        self.assertEqual(duration_ms_from_stream_info(info), 10000)

    def test_duration_ms_from_stream_info_duration_field(self):
        info = {'duration': '12.5'}
        self.assertEqual(duration_ms_from_stream_info(info), 12500)

    def test_stream_get_duration_ms_from_probe(self):
        with tempfile.NamedTemporaryFile(suffix='.mkv', delete=False) as fp:
            dummy = Path(fp.name)
        try:
            avs = AVSFile(dummy)
            avs.info = {
                'streams': [
                    {'codec_type': 'audio', 'time_base': '1/48000', 'duration_ts': 48000}
                ]
            }
            stream = Stream(file=avs, type='audio', stream_info=avs.info['streams'][0], index=0)
            self.assertEqual(stream.get_duration_ms(), 1000)
        finally:
            dummy.unlink(missing_ok=True)

    def test_resolve_card_workers_scales_with_episode_jobs(self):
        with mock.patch.dict(os.environ, {'SUBS2CIA_WORKERS': '8'}, clear=False):
            solo = _resolve_card_workers({}, 20, episode_jobs=1)
            parallel = _resolve_card_workers({}, 20, episode_jobs=4)
        self.assertEqual(solo, 8)
        self.assertEqual(parallel, 2)

    def test_resolve_episode_jobs_cli_override(self):
        args = {'jobs': 3}
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_episode_jobs(args), 3)

    def test_get_compression_ratio_uses_cached_duration(self):
        sub_times = [[[(0, 1000)]]]
        ratio = get_compression_ratio(sub_times, Path('unused.flac'), verbose=False, duration_ms=10000)
        self.assertAlmostEqual(ratio, 0.1)

    def test_audio_trim_uses_input_seek_and_duration(self):
        from subs2cia.ffmpeg_tools import ffmpeg_trim_audio_clip_atrim_encode

        input_file = Path('episode.mkv')
        outpath = Path('clip.mp3')
        stream = ffmpeg.input(str(input_file), ss=5.0)
        stream = stream['2']
        stream = ffmpeg.output(stream, str(outpath), t=3.0, audio_bitrate='320k', ac=1)
        args = ffmpeg.get_args(stream)
        self.assertIn('-ss', args)
        self.assertIn('5.0', args)
        self.assertIn('-t', args)
        self.assertIn('3.0', args)


if __name__ == '__main__':
    unittest.main()
