import numpy as np
import pytest
from rppg.signal import analyze, synthetic, validate_samples, pos

@pytest.mark.parametrize('bpm', [48, 72, 108, 156])
def test_frequency_and_common_illumination(bpm):
    rows = synthetic(seconds=85, bpm=bpm)
    result = analyze(rows)
    valid = [r for r in result if r['hr_bpm'] is not None]
    assert len(valid) > 50
    assert max(abs(r['hr_bpm'] - bpm) for r in valid) < 3
    assert valid[0]['delta_hr_bpm'] is None
    assert valid[-1]['delta_hr_bpm'] is not None

@pytest.mark.parametrize('mode', ['flat', 'invalid', 'gap', 'motion', 'light'])
def test_abstention(mode):
    rows = synthetic(seconds=25)
    if mode == 'flat':
        for r in rows: r.update(r=100., g=100., b=100.)
    elif mode == 'invalid':
        for r in rows: r['roi_valid'] = False
    elif mode == 'gap':
        rows = [r for r in rows if not 8 < r['timestamp_s'] < 9]
    elif mode == 'motion':
        for r in rows: r['motion_metric'] = 1.
    else:
        for r in rows: r['brightness_metric'] = 255.
    assert all(r['hr_bpm'] is None and r['reasons'] for r in analyze(rows))

@pytest.mark.parametrize('timestamps', [[0, 0], [1, 0], [0, float('nan')]])
def test_bad_timestamps(timestamps):
    rows = synthetic(seconds=1)[:2]
    for row, t in zip(rows, timestamps): row['timestamp_s'] = t
    with pytest.raises(ValueError): validate_samples(rows)

def test_low_fps_and_short_input():
    assert all(r['hr_bpm'] is None for r in analyze(synthetic(seconds=25, fps=4)))
    assert analyze(synthetic(seconds=5)) == []

def test_pos_guard():
    assert np.all(np.isfinite(pos(np.zeros((100, 3)), 30)))

def test_prefix_causality_and_fixed_calibration():
    rows = synthetic(seconds=90)
    full = analyze(rows)
    prefix = analyze([r for r in rows if r['timestamp_s'] <= 65])
    assert full[:len(prefix)] == prefix
    baselines = [r['baseline_hr_bpm'] for r in full if r['baseline_hr_bpm'] is not None]
    assert len(set(baselines)) == 1

def test_invalid_rgb_and_sparse_windows():
    rows = synthetic(seconds=25)
    rows[20]['r'] = float('inf')
    with pytest.raises(ValueError): analyze(rows)
    rows = synthetic(seconds=25)
    for i, r in enumerate(rows):
        if i % 3 == 0: r['roi_valid'] = False
    assert all('insufficient_valid_samples' in r['reasons'] for r in analyze(rows))
