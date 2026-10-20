"""Independent contract tests; deterministic fixtures are not physiological evidence."""
import csv
import json
import subprocess
import sys

import cv2
import numpy as np
import pytest

from rppg.evaluation import classify, evaluate
from rppg.report import read_rgb, write_csv
from rppg.signal import FIELDS, analyze
from rppg.video import extract


def rgb_fixture(bpm=83, seconds=24, fps=24):
    t = np.arange(round(seconds * fps) + 1) / fps
    pulse = np.sin(2 * np.pi * bpm / 60 * t + .41)
    light = 1 + .06 * np.cos(2 * np.pi * .31 * t)
    rgb = np.array([128., 104., 88.])[None, :] * (
        1 + pulse[:, None] * np.array([.002, .014, .004])[None, :]) * light[:, None]
    return [dict(timestamp_s=float(time), r=float(c[0]), g=float(c[1]), b=float(c[2]),
                 roi_valid=True, motion_metric=0., brightness_metric=float(c.mean()))
            for time, c in zip(t, rgb)]


def feature_fixture():
    return [dict(subject_id=f's{s}', label=f'c{c}', hr_bpm=45 + s * 15 + c * 3)
            for s in range(6) for c in range(2)]


def cli(*args):
    return subprocess.run([sys.executable, '-m', 'rppg', *map(str, args)],
                          capture_output=True, text=True, timeout=45)


@pytest.mark.parametrize('fps,bpm', [(12, 43), (24, 59), (30, 83), (24, 137), (60, 177)])
def test_independent_frequency_and_illumination(fps, bpm):
    windows = analyze(rgb_fixture(bpm=bpm, fps=fps))
    assert len(windows) == 5
    assert all(w['hr_bpm'] is not None and abs(w['hr_bpm'] - bpm) < 3 for w in windows)


@pytest.mark.parametrize('kind,reason', [
    ('flat', 'flat_or_low_signal'), ('invalid', 'insufficient_valid_samples'),
    ('sparse', 'insufficient_valid_samples'), ('leading', 'long_gap'),
    ('trailing', 'long_gap'), ('internal', 'long_gap'),
    ('motion', 'motion'), ('illumination', 'illumination'),
    ('low_fps', 'sampling_rate_too_low')])
def test_independent_quality_abstention(kind, reason):
    rows = rgb_fixture(fps=6 if kind == 'low_fps' else 24)
    for i, row in enumerate(rows):
        t = row['timestamp_s']
        if kind == 'flat': row.update(r=100., g=100., b=100.)
        if kind == 'invalid' or (kind == 'sparse' and i % 4 == 0):
            row.update(roi_valid=False, r=None, g=None, b=None)
        if kind == 'leading' and t < 1 or kind == 'trailing' and t > 19:
            row.update(roi_valid=False, r=None, g=None, b=None)
        if kind == 'motion': row['motion_metric'] = .4
        if kind == 'illumination': row['brightness_metric'] = 250.
    if kind == 'internal': rows = [r for r in rows if not 9 < r['timestamp_s'] < 10]
    windows = analyze(rows)
    inspected = windows[:1] if kind == 'leading' else windows
    assert inspected and all(w['hr_bpm'] is None and reason in w['reasons'] for w in inspected)


def test_short_missing_run_interpolates_without_future_data():
    rows = rgb_fixture()
    for i in [200, 201]: rows[i].update(roi_valid=False, r=None, g=None, b=None)
    windows = analyze(rows)
    assert all(w['hr_bpm'] is not None and abs(w['hr_bpm'] - 83) < 3 for w in windows)


def test_diffuse_noise_and_pure_common_mode_abstain():
    rng = np.random.default_rng(49281)
    rows = rgb_fixture()
    for row in rows:
        row.update(zip(['r', 'g', 'b'], 100 + rng.normal(0, 1, 3)))
        row['brightness_metric'] = 100.
    assert all(w['hr_bpm'] is None and 'diffuse_spectrum' in w['reasons'] for w in analyze(rows))
    rows = rgb_fixture()
    for row in rows:
        light = 1 + .05 * np.sin(2 * np.pi * 1.2 * row['timestamp_s'])
        row.update(r=120*light, g=100*light, b=80*light)
    assert all(w['hr_bpm'] is None and 'flat_or_low_signal' in w['reasons'] for w in analyze(rows))


def test_changing_rate_prefix_and_baseline_are_causal():
    rows = rgb_fixture(bpm=67, seconds=100)
    future = rgb_fixture(bpm=131, seconds=100)
    changed = [a if a['timestamp_s'] <= 60 else b for a, b in zip(rows, future)]
    full = analyze(changed)
    prefix = analyze([r for r in changed if r['timestamp_s'] <= 60])
    assert full[:len(prefix)] == prefix
    baseline = np.median([w['hr_bpm'] for w in prefix if w['hr_bpm'] is not None])
    ready = [w for w in full if w['timestamp_s'] > 60]
    assert all(w['baseline_hr_bpm'] == baseline for w in ready)
    assert all(abs(w['hr_bpm'] - 131) < 3 and abs(w['delta_hr_bpm'] - 64) < 3
               for w in ready if w['timestamp_s'] >= 81)
    assert all(w['delta_hr_bpm'] is None and w['baseline_status'] == 'collecting' for w in prefix)


def test_inadequate_first_minute_never_uses_later_calibration():
    rows = rgb_fixture(seconds=100)
    for r in rows:
        if r['timestamp_s'] < 55: r.update(roi_valid=False, r=None, g=None, b=None)
    windows = analyze(rows)
    later = [w for w in windows if w['timestamp_s'] > 80]
    assert later and all(w['hr_bpm'] is not None for w in later)
    assert all(w['baseline_status'] == 'insufficient_calibration' and w['delta_hr_bpm'] is None for w in later)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf'), 0., -.1])
def test_timestamp_rejection(bad):
    rows = rgb_fixture()
    rows[1]['timestamp_s'] = bad
    with pytest.raises(ValueError, match='timestamp'): analyze(rows)


def test_file_no_face_and_manual_pulsatile_video(tmp_path):
    path = tmp_path / 'independent-synthetic.avi'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 24, (64, 64))
    assert writer.isOpened()
    try:
        for row in rgb_fixture(bpm=83):
            bgr = [row[k] for k in ['b', 'g', 'r']]
            writer.write(np.tile(np.rint(bgr).astype('uint8'), (64, 64, 1)))
    finally:
        writer.release()
    rows, metadata = extract(video=path)
    assert metadata['invalid_frames'] == len(rows) and metadata['roi_mode'] == 'single_face_proxy'
    assert all(w['hr_bpm'] is None for w in analyze(rows))
    rows, metadata = extract(video=path, roi=(8, 8, 40, 40), fps_override=24)
    assert metadata['roi_mode'] == 'manual' and metadata['timestamp_mode'] == 'frame_index_fps_fallback'
    assert metadata['raw_recording'] is False
    assert all(abs(w['hr_bpm'] - 83) < 3 for w in analyze(rows))
    with pytest.raises(ValueError, match='outside'): extract(video=path, roi=(40, 40, 40, 40))


def test_multiple_faces_invalid_and_file_timestamp_fallback(monkeypatch):
    class File:
        released = False
        n = 0
        def isOpened(self): return True
        def get(self, key): return 30 if key == cv2.CAP_PROP_FPS else 0
        def read(self):
            self.n += 1
            return (True, np.full((64, 64, 3), 100, dtype='uint8')) if self.n <= 31 else (False, None)
        def release(self): self.released = True
    class Faces:
        def detectMultiScale(self, *a, **kw): return [(0, 0, 30, 30), (32, 32, 30, 30)]
    device = File()
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *a: device)
    monkeypatch.setattr(cv2, 'CascadeClassifier', lambda *a: Faces())
    rows, metadata = extract(video='stub-not-a-real-device')
    assert device.released and not any(r['roi_valid'] for r in rows)
    assert metadata['timestamp_mode'] == 'frame_index_fps_fallback'
    assert rows[-1]['timestamp_s'] == 1


def test_camera_read_false_is_bounded_and_releases_stub(monkeypatch):
    class Camera:
        released = False
        n = 0
        def isOpened(self): return True
        def get(self, key): return 30
        def read(self):
            self.n += 1
            return (True, np.full((64, 64, 3), 100, dtype='uint8')) if self.n < 3 else (False, None)
        def release(self): self.released = True
    device = Camera()
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *a: device)
    rows, metadata = extract(camera=0, duration=1, roi=(0, 0, 32, 32))
    assert device.released and len(rows) == 2 and metadata['camera_read_failure']
    assert metadata['timestamp_mode'] == 'monotonic' and metadata['raw_recording'] is False


def test_evaluation_independent_oracle_and_tolerance():
    predictions = [dict(timestamp_s=t, hr_bpm=h) for t, h in [(0, None), (1, 80), (2, 100), (3, 120)]]
    reference = [dict(timestamp_s=t, hr_bpm=h) for t, h in [(0, 60), (1.1, 70), (2.1, 80), (3, 90)]]
    report = evaluate(predictions, reference, tolerance=.11)
    assert report['matched_pairs'] == 3
    assert report['mae_bpm'] == 20
    assert report['rmse_bpm'] == pytest.approx(np.sqrt(1400 / 3))
    assert report['coverage_all_predictions'] == .75 and report['coverage_valid_predictions'] == 1
    assert report['correlation'] == pytest.approx(1)
    strict = evaluate(predictions, reference, tolerance=.01)
    assert strict['matched_pairs'] == 1 and strict['correlation'] is None
    with pytest.raises(ValueError, match='matched pairs'):
        evaluate(predictions[1:3], reference, tolerance=.01)


@pytest.mark.parametrize('bad', ['NaN', 'Infinity', '-Infinity'])
def test_classify_nonfinite_hr_excluded_with_reason(bad):
    rows = feature_fixture() + [dict(subject_id='s0', label='c0', hr_bpm=bad)]
    report = classify(rows)
    assert report['included_rows'] == 12
    assert report['excluded_rows'] == [dict(row=14, reason='invalid_hr')]


def test_grouped_preprocessing_fits_train_only(monkeypatch):
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    traces, scalers = [], []
    original = SimpleImputer.fit
    original_scaler = StandardScaler.fit
    def fit(self, x, *args, **kwargs):
        traces.append(np.array(x, copy=True))
        return original(self, x, *args, **kwargs)
    def fit_scaler(self, x, *args, **kwargs):
        scalers.append(np.array(x, copy=True))
        return original_scaler(self, x, *args, **kwargs)
    monkeypatch.setattr(SimpleImputer, 'fit', fit)
    monkeypatch.setattr(StandardScaler, 'fit', fit_scaler)
    rows = feature_fixture()
    rows[0]['hr_bpm'] = ''
    report = classify(rows)
    tested = []
    assert len(traces) == len(scalers) == 2 * len(report['folds'])
    for i, fold in enumerate(report['folds']):
        assert not set(fold['train_subjects']) & set(fold['test_subjects'])
        tested.extend(fold['test_subjects'])
        expected = np.array([np.nan if r['hr_bpm'] == '' else r['hr_bpm']
                             for r in rows if r['subject_id'] in fold['train_subjects']])[:, None]
        for index in [2*i, 2*i+1]:
            np.testing.assert_equal(traces[index], expected)
            np.testing.assert_equal(scalers[index], np.where(np.isnan(expected), np.nanmedian(expected), expected))
    assert sorted(tested) == sorted({r['subject_id'] for r in rows})
    for metrics in report['metrics'].values():
        assert np.sum(metrics['confusion_matrix']) == len(rows)
        assert metrics['balanced_accuracy'] == pytest.approx(np.mean(list(metrics['per_class_recall'].values())))


@pytest.mark.parametrize('column', ['task', 'scenario', 'BVP', 'EDA', 'delta_hr_bpm', 'file_path'])
def test_unapproved_features_rejected(column):
    rows = feature_fixture()
    rows[-1][column] = 'leak'
    with pytest.raises(ValueError, match='Unapproved'): classify(rows)


@pytest.mark.parametrize('case', ['too_few_subjects', 'one_class', 'class_missing_from_train', 'all_blank'])
def test_grouped_classification_support_guards(case):
    rows = feature_fixture()
    if case == 'too_few_subjects': rows = [r for r in rows if r['subject_id'] in ['s0', 's1']]
    if case == 'one_class':
        for r in rows: r['label'] = 'only'
    if case == 'class_missing_from_train':
        for r in rows: r['label'] = 'rare' if r['subject_id'] == 's0' else 'common'
    if case == 'all_blank':
        for r in rows: r['hr_bpm'] = ''
    with pytest.raises(ValueError): classify(rows)


def test_cli_provenance_checksum_escape_overwrite_and_unknown(tmp_path):
    source = tmp_path / '<script>fixture.csv'
    write_csv(source, rgb_fixture(), FIELDS)
    output = tmp_path / 'synthetic'
    result = cli('analyze', '--rgb', source, '--synthetic', '--output', output)
    assert result.returncode == 0, result.stderr
    report = json.loads((output / 'report.json').read_text(), parse_constant=lambda x: pytest.fail(x))
    assert report['provenance']['synthetic'] is True and report['valid_windows'] == 5
    html = (output / 'report.html').read_text()
    assert '<script>' not in html and '&lt;script&gt;' in html and 'SYNTHETIC' in html
    assert report['parameters']['quality_status'].startswith('provisional')
    copied = tmp_path / 'copy'
    assert cli('analyze', '--rgb', output / 'rgb.csv', '--output', copied).returncode == 0
    assert json.loads((copied / 'report.json').read_text())['provenance']['synthetic'] is True
    before = (output / 'report.json').read_bytes()
    assert cli('demo', '--output', output).returncode != 0
    assert (output / 'report.json').read_bytes() == before
    with (output / 'rgb.csv').open('a') as stream: stream.write('\n')
    corrupt = cli('analyze', '--rgb', output / 'rgb.csv', '--output', tmp_path / 'corrupt')
    assert corrupt.returncode != 0 and 'checksum mismatch' in corrupt.stderr
    unknown = tmp_path / 'unknown'
    assert cli('analyze', '--rgb', source, '--output', unknown).returncode == 0
    provenance = json.loads((unknown / 'report.json').read_text())['provenance']
    assert provenance['synthetic'] is False and 'unknown' in provenance['synthetic_status']


def test_cli_evaluation_and_grouped_classification_reports(tmp_path):
    predictions = tmp_path / 'predictions.csv'
    reference = tmp_path / 'reference.csv'
    predictions.write_text('timestamp_s,hr_bpm\n0,\n1,80\n2,100\n3,120\n')
    reference.write_text('timestamp_s,hr_bpm\n0,60\n1,70\n2,80\n3,90\n')
    # Simulate predictions from an existing synthetic run; check inherited label.
    (tmp_path / 'report.json').write_text(json.dumps({'provenance': {'synthetic': True}}))
    evaluation = tmp_path / 'evaluation'
    result = cli('evaluate', '--predictions', predictions, '--reference', reference,
                 '--tolerance', '0', '--output', evaluation)
    assert result.returncode == 0, result.stderr
    report = json.loads((evaluation / 'report.json').read_text())
    assert report['mae_bpm'] == 20 and report['matched_pairs'] == 3
    assert report['coverage_all_predictions'] == .75
    assert report['provenance']['synthetic'] is True
    assert 'SYNTHETIC' in (evaluation / 'report.html').read_text()
    from rppg.report import fingerprint
    assert report['provenance']['predictions_sha256'] == fingerprint(predictions)
    assert report['provenance']['reference_sha256'] == fingerprint(reference)
    features = tmp_path / 'features.csv'
    with features.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['subject_id', 'label', 'hr_bpm'])
        writer.writeheader()
        writer.writerows(feature_fixture())
    classification = tmp_path / 'classification'
    result = cli('classify', '--features', features, '--synthetic', '--output', classification)
    assert result.returncode == 0, result.stderr
    report = json.loads((classification / 'report.json').read_text())
    assert report['features'] == ['hr_bpm'] and report['included_rows'] == 12
    assert report['provenance']['features_sha256'] == fingerprint(features)
    assert report['provenance']['synthetic'] is True
    assert 'SYNTHETIC' in (classification / 'report.html').read_text()
    assert set(report['metrics']) == {'dummy', 'random_forest'}
    assert all(not set(f['train_subjects']) & set(f['test_subjects']) for f in report['folds'])


@pytest.mark.parametrize('bad_reference', [
    'timestamp_s,hr_bpm\n0,70\n0,80\n',
    'timestamp_s,hr_bpm\n1,70\n0,80\n',
    'timestamp_s,hr_bpm\n0,nan\n1,80\n',
    'timestamp_s,hr_bpm\n0,70\nnan,80\n',
    'timestamp_s,hr_bpm\n10,70\n11,80\n'])
def test_cli_evaluation_rejects_invalid_reference(tmp_path, bad_reference):
    predictions = tmp_path / 'predictions.csv'
    reference = tmp_path / 'reference.csv'
    predictions.write_text('timestamp_s,hr_bpm\n0,70\n1,80\n')
    reference.write_text(bad_reference)
    output = tmp_path / 'rejected'
    result = cli('evaluate', '--predictions', predictions, '--reference', reference, '--output', output)
    assert result.returncode == 1 and 'error:' in result.stderr
    assert not (output / 'report.json').exists()


@pytest.mark.parametrize('duration', ['0', '-1', '3601', 'nan', 'inf'])
def test_invalid_camera_limits_do_not_open_device(tmp_path, monkeypatch, duration):
    from rppg.__main__ import main
    def forbidden(*a): pytest.fail('VideoCapture must not be called')
    monkeypatch.setattr(cv2, 'VideoCapture', forbidden)
    output = tmp_path / 'never-created'
    assert main(['capture', '--duration', duration, '--output', str(output)]) != 0
    assert not output.exists()


@pytest.mark.parametrize('text', [
    'timestamp_s,timestamp_s\n0,0\n',
    'timestamp_s,r,g,b,roi_valid,motion_metric,brightness_metric\n0,1,2,3,true,0\n',
    'timestamp_s,r,g,b,roi_valid,motion_metric,brightness_metric\n0,1,2,3,maybe,0,100\n'])
def test_malformed_interchange_rejected(tmp_path, text):
    source = tmp_path / 'bad.csv'
    source.write_text(text)
    with pytest.raises(ValueError): read_rgb(source)
