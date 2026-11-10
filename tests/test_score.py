import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from score import compose, extract, scroll_shift, staves, measure_labels_changed
from sources import parse_link, probe


def document(rows=8):
    image = np.full((rows * 140 + 500, 1280, 3), 250, np.uint8)
    for row in range(rows):
        top = 180 + row * 140
        cv2.putText(image, str(row * 4 + 1), (22, top - 20), cv2.FONT_HERSHEY_SIMPLEX, .45, (10, 10, 10), 1)
        for i in range(5):
            cv2.line(image, (30, top + i * 9), (1220, top + i * 9), (50, 50, 50), 1)
        for x in range(60, 1200, 65):
            cv2.ellipse(image, (x, top + 27), (6, 4), -25, 0, 360, (0, 0, 0), -1)
            cv2.line(image, (x + 6, top + 27), (x + 6, top - 23), (0, 0, 0), 2)
        for x in (30, 330, 630, 930, 1220):
            cv2.line(image, (x, top), (x, top + 36), (10, 10, 10), 1)
    return image


def melody_document(rows=8):
    """Synthetic pitched notation with accidentals, ledger lines and slurs."""
    image = np.full((rows * 140 + 500, 1280, 3), 250, np.uint8)
    for row in range(rows):
        top = 180 + row * 140
        cv2.putText(image, str(row + 1), (22, top - 20), cv2.FONT_HERSHEY_SIMPLEX, .45, (10, 10, 10), 1)
        for i in range(5):
            cv2.line(image, (30, top + i * 9), (1220, top + i * 9), (50, 50, 50), 1)
        for index, x in enumerate(range(100, 1200, 90)):
            pitch = (-18, 0, 9, 27, 45, 54)[(index + row) % 6]
            y = top + pitch
            cv2.ellipse(image, (x, y), (6, 4), -25, 0, 360, (0, 0, 0), -1)
            direction = 1 if pitch < 18 else -1
            stem_x = x - 6 if direction == 1 else x + 6
            cv2.line(image, (stem_x, y), (stem_x, y + direction * 30), (0, 0, 0), 2)
            for ledger in list(range(-9, pitch - 1, -9)) if pitch < 0 else list(range(45, pitch + 1, 9)):
                cv2.line(image, (x - 11, top + ledger), (x + 11, top + ledger), (0, 0, 0), 1)
            if index % 3 == 0:
                cv2.putText(image, '#' if index % 2 else 'b', (x - 25, y + 5), cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 0, 0), 1)
        cv2.ellipse(image, (250, top - 22), (65, 15), 0, 180, 360, (0, 0, 0), 1)
        for x in (30, 330, 630, 930, 1220):
            cv2.line(image, (x, top), (x, top + 36), (10, 10, 10), 1)
    return image


class ScoreTests(unittest.TestCase):
    def test_staff_detection(self):
        rows = staves(document()[:720])
        self.assertEqual(len(rows), 4)
        self.assertAlmostEqual(rows[0]['gap'], 9)

    def test_identical_grooves_choose_correct_scroll(self):
        d = document()
        shift, confidence = scroll_shift(d[:720, :, 0], d[86:806, :, 0])
        self.assertAlmostEqual(shift, 86, delta=2)
        self.assertGreater(confidence, .8)

    def test_scene_change_not_falsely_aligned(self):
        a = document()[:720, :, 0]
        b = np.random.default_rng(3).integers(0, 255, a.shape, dtype=np.uint8)
        shift, _ = scroll_shift(a, b)
        self.assertIsNone(shift)

    def test_page_number_changes_with_identical_rhythms(self):
        a = document()[:720]
        b = a.copy()
        for top in (180, 320, 460, 600):
            b[top - 32:top - 10, :60] = 250
            cv2.putText(b, '99', (22, top - 20), cv2.FONT_HERSHEY_SIMPLEX, .45, (10, 10, 10), 1)
        self.assertTrue(measure_labels_changed(a[:, :, 0], b[:, :, 0], staves(b)))
        self.assertFalse(measure_labels_changed(a[:, :, 0], a[:, :, 0], staves(a)))

    def test_selection_and_order(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            for i in range(3):
                Image.new('L', (500, 100), 200 + i * 10).save(folder / f'row-{i:03}.png')
            meta = {'title': 'Test', 'rows': [{'id': str(i), 'file': f'row-{i:03}.png'} for i in range(3)]}
            r = compose(folder, meta, ['2', '0'])
            self.assertEqual(r['selected'], ['2', '0'])
            self.assertEqual(len(r['rows']), 3)
            self.assertTrue((folder / 'score.png').exists())
            with self.assertRaises(ValueError):
                compose(folder, meta, ['0', '0'])
            with self.assertRaises(ValueError):
                compose(folder, meta, [])

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_repeated_rows_survive_full_video_pipeline(self):
        self.check_video_pipeline(document())

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_pitched_melody_survives_full_video_pipeline(self):
        self.check_video_pipeline(melody_document(), verify_symbols=True)

    def check_video_pipeline(self, doc, verify_symbols=False):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            source = folder / 'repeat.mp4'
            offsets = list(range(0, 700, 86)) + [700]
            p = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                                  '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '1280x720',
                                  '-r', '2', '-i', '-', '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                                  str(source)], stdin=subprocess.PIPE)
            for offset in offsets:
                for _ in range(2):
                    p.stdin.write(doc[offset:offset + 720].tobytes())
            p.stdin.close()
            self.assertEqual(p.wait(), 0)
            info = probe(source)
            out = folder / 'result'
            out.mkdir()
            result = extract(source, out, {'title': 'Repeated rhythms', 'video': info},
                             {'interval': .5, 'crop': [.01, 0, .99, 1]}, lambda *_: None, lambda: None)
            self.assertEqual(len(result['rows']), 8)
            self.assertEqual(result['page_breaks'], 0)
            with Image.open(out / 'score.png') as output:
                self.assertGreater(output.height, 1000)
            if verify_symbols:
                # Match every exported row against the original document, so
                # missing notes/ledger lines or reordered rows fail this check.
                expected = doc[:, 13:1267, 0]
                positions = []
                for row in result['rows']:
                    actual = np.asarray(Image.open(out / row['file']).convert('L'))
                    scores = cv2.matchTemplate(expected, actual, cv2.TM_CCOEFF_NORMED)
                    _, confidence, _, position = cv2.minMaxLoc(scores)
                    self.assertGreater(confidence, .9)
                    positions.append(position[1])
                self.assertEqual(positions, sorted(set(positions)))

    def test_bad_crop_and_range(self):
        meta = {'video': {'width': 1280, 'height': 720, 'duration': 10}}
        with tempfile.TemporaryDirectory() as d:
            for opts in ({'crop': [0, 0, .001, 1]}, {'start': 20}, {'interval': float('nan')}, {'end': -1}):
                with self.assertRaises(ValueError):
                    extract(Path('missing.mp4'), Path(d), meta, opts, lambda *_: None, lambda: None)


class LinkTests(unittest.TestCase):
    def test_bv_and_part(self):
        self.assertEqual(parse_link('BV1Le411i7Bp'), ('BV1Le411i7Bp', 1))
        self.assertEqual(parse_link('https://www.bilibili.com/video/BV1Le411i7Bp/?p=2&x=y'), ('BV1Le411i7Bp', 2))

    def test_non_bilibili_addresses_are_rejected(self):
        for link in ('file:///etc/passwd', 'http://127.0.0.1/',
                     'https://www.bilibili.com.evil.test/video/BV1Le411i7Bp/',
                     'https://user@www.bilibili.com/video/BV1Le411i7Bp/',
                     'https://www.bilibili.com:8888/video/BV1Le411i7Bp/'):
            with self.assertRaises(ValueError):
                parse_link(link)


if __name__ == '__main__':
    unittest.main()
