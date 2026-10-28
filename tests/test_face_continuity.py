"""Offline continuity contract; fixtures are geometry, not identity validation."""
import json
import cv2
import numpy as np
import pytest
from rppg import video
from rppg.__main__ import main, parser

FACE = (20, 20, 80, 80)
SHIRT = (20, 160, 80, 80)


def selector():
    from rppg.face_selection import FaceSelector
    return FaceSelector()


def acquire(s):
    decisions = [s.select([FACE], t) for t in (0., .04, .08)]
    assert [d['selected_box'] for d in decisions] == [None, None, FACE]


def test_initial_multiple_abstains_and_requires_three_singles():
    s = selector()
    assert s.select([FACE, SHIRT], 0.)['selected_box'] is None
    assert [s.select([FACE], t)['selected_box'] for t in (.04, .08, .12)] == [None, None, FACE]


@pytest.mark.parametrize('reverse', [False, True])
def test_shirt_false_positive_unique_match_is_order_independent(reverse):
    s = selector()
    acquire(s)
    candidates = [SHIRT, (22, 20, 80, 80)]
    d = s.select(candidates[::-1] if reverse else candidates, .12)
    assert d['selected_box'] == (22, 20, 80, 80)
    assert d['face_count'] == 2
    assert d['status'] == 'selected'


def test_two_near_candidates_ambiguous_then_reacquire():
    s = selector()
    acquire(s)
    assert s.select([FACE, (22, 20, 80, 80)], .12)['selected_box'] is None
    assert [s.select([FACE], t)['selected_box'] for t in (.16, .20, .24)] == [None, None, FACE]


@pytest.mark.parametrize('jump', [(200, 20, 80, 80), (20, 20, 160, 160)])
def test_jump_frame_invalid_and_not_counted_for_reacquisition(jump):
    s = selector()
    acquire(s)
    assert s.select([jump], .12)['selected_box'] is None
    assert [s.select([jump], t)['selected_box'] for t in (.16, .20, .24)] == [None, None, jump]


def test_no_face_never_reuses_box_and_prior_expires():
    s = selector()
    acquire(s)
    assert s.select([], .12)['selected_box'] is None
    assert s.select([FACE, SHIRT], .16)['selected_box'] == FACE
    assert s.select([], .40)['selected_box'] is None
    assert s.select([FACE, SHIRT], .44)['selected_box'] is None
    assert [s.select([FACE], t)['selected_box'] for t in (.48, .52, .56)] == [None, None, FACE]


def test_acquisition_gap_and_out_of_order_timestamp_cannot_retain_history():
    s = selector()
    s.select([FACE], 0.)
    assert s.select([FACE], .3)['selected_box'] is None
    assert s.select([FACE], .34)['selected_box'] is None
    with pytest.raises(ValueError, match='timestamp'):
        s.select([FACE], .33)
    with pytest.raises(ValueError, match='timestamp'):
        s.select([FACE], float('nan'))


def fixture_video(tmp_path):
    path = tmp_path/'fixture.avi'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 25, (320, 260))
    for _ in range(5): writer.write(np.full((260, 320, 3), 100, dtype=np.uint8))
    writer.release()
    return path


def test_extract_strict_default_continuity_diagnostics_and_no_stale_rgb(tmp_path, monkeypatch):
    path = fixture_video(tmp_path)
    class Detector:
        def __init__(self): self.frames = iter([[FACE], [FACE], [FACE], [FACE, SHIRT], []])
        def detectMultiScale(self, *args, **kwargs): return next(self.frames)
    monkeypatch.setattr(cv2, 'CascadeClassifier', lambda *args: Detector())
    rows, meta = video.extract(video=path)
    assert [r['roi_valid'] for r in rows] == [True, True, True, False, False]
    rows, meta = video.extract(video=path, face_policy='continuity')
    assert [r['roi_valid'] for r in rows] == [False, False, True, True, False]
    assert rows[-1]['r'] is None
    diagnostics = meta['face_selection']['diagnostics']
    assert diagnostics[3]['face_count'] == 2
    assert diagnostics[3]['selected_box'] == FACE
    assert diagnostics[-1]['selected_box'] is None
    assert [d['timestamp_s'] for d in diagnostics] == [r['timestamp_s'] for r in rows]
    assert meta['face_selection']['parameters']['provenance']
    json.dumps(meta)


@pytest.mark.parametrize('kwargs', [dict(video='unused', roi=FACE), dict(camera=0)])
def test_continuity_conflicts_rejected_before_open(monkeypatch, kwargs):
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *args: pytest.fail('must validate before source open'))
    with pytest.raises(ValueError, match='continuity'):
        video.extract(face_policy='continuity', **kwargs)


def test_cli_strict_default_and_conflicts_before_output(tmp_path):
    assert parser().parse_args(['analyze', '--video', 'unused', '--output', 'unused']).face_policy == 'strict'
    output = tmp_path/'output'
    for source in (['--video', 'unused', '--roi', '0,0,10,10'], ['--rgb', 'unused'],
                   ['--video', 'unused', '--fps', '25']):
        assert main(['analyze', *source, '--face-policy', 'continuity', '--output', str(output)]) == 1
        assert not output.exists()
    with pytest.raises(SystemExit):
        parser().parse_args(['capture', '--duration', '1', '--face-policy', 'continuity', '--output', 'unused'])


@pytest.mark.parametrize('times', [
    [0., .04, .08, .50, .54],  # Median looks nominal but a real decoder gap exists.
    [0., .04, float('nan'), .12, .16],
    [0., .04, .04, .12, .16],
    [0., .04, .03, .12, .16],
    [0., .04, .09, .13, .17],  # 25% long step.
    [0., .04, .07, .11, .15],  # 25% short step.
])
def test_continuity_rejects_bad_decoder_steps_strict_unchanged_override_rejected(monkeypatch, times):
    devices = []
    class File:
        def __init__(self):
            self.index = 0
            self.released = False
            devices.append(self)
        def isOpened(self): return True
        def get(self, key):
            return 25. if key == cv2.CAP_PROP_FPS else times[self.index-1]*1000
        def read(self):
            if self.index == len(times): return False, None
            self.index += 1
            return True, np.zeros((64, 64, 3), dtype=np.uint8)
        def release(self): self.released = True
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *args: File())
    with pytest.raises(ValueError, match='continuity.*constant-FPS.*--fps'):
        video.extract(video='fixture', face_policy='continuity')
    assert devices[-1].released
    rows, _ = video.extract(video='fixture')
    assert len(rows) == 5 and devices[-1].released
    with pytest.raises(ValueError, match='continuity.*--fps'):
        video.extract(video='fixture', face_policy='continuity', fps_override=25.)


def test_decoder_drift_expires_prior_using_actual_elapsed_time(monkeypatch):
    class File:
        index = 0
        def isOpened(self): return True
        def get(self, key):
            return 25. if key == cv2.CAP_PROP_FPS else 1000 + (self.index-1)*47.
        def read(self):
            if self.index == 8: return False, None
            self.index += 1
            return True, np.zeros((260, 320, 3), dtype=np.uint8)
        def release(self): pass
    class Detector:
        def __init__(self): self.frames = iter([[FACE]]*3 + [[]]*4 + [[FACE, SHIRT]])
        def detectMultiScale(self, *args, **kwargs): return next(self.frames)
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *args: File())
    monkeypatch.setattr(cv2, 'CascadeClassifier', lambda *args: Detector())
    rows, metadata = video.extract(video='fixture', face_policy='continuity')
    assert rows[2]['roi_valid']
    assert not rows[-1]['roi_valid']  # .235 actual seconds, versus .2 nominal.
    diagnostics = metadata['face_selection']['diagnostics']
    assert diagnostics[-1]['selected_box'] is None
    assert diagnostics[-1]['selection_timestamp_s'] == pytest.approx(.329)
    assert metadata['face_selection']['selection_timestamp_mode'] == 'decoder_presentation_time'
