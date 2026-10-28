"""POS (Wang et al., 2017) and provisional trailing-window quality gates."""
import numpy as np
from scipy.signal import detrend, welch

PARAMETERS = dict(window_seconds=20., hop_seconds=1., pos_seconds=1.6,
                  band_hz=[.7, 3.], min_fs_hz=10., min_valid_fraction=.9,
                  max_gap_seconds=.2, max_motion=.12, brightness_range=[10., 245.],
                  max_brightness_span=40.,
                  min_relative_signal_std=1e-5, min_peak_concentration=.35,
                  baseline_seconds=60., baseline_min_windows=30,
                  quality_status='provisional thresholds; not physiologically validated')
FIELDS = ['timestamp_s', 'r', 'g', 'b', 'roi_valid', 'motion_metric', 'brightness_metric']


def validate_samples(rows):
    if not rows:
        raise ValueError('No RGB samples')
    previous = -np.inf
    for row in rows:
        t = float(row['timestamp_s'])
        if not np.isfinite(t) or t <= previous:
            raise ValueError('timestamps must be finite and strictly increasing')
        previous = t
        if row['roi_valid']:
            if not all(np.isfinite(float(row[k])) for k in FIELDS[1:4] + FIELDS[5:]):
                raise ValueError('valid ROI requires finite RGB, motion and brightness')
            if not all(0 <= float(row[k]) <= 255 for k in ['r', 'g', 'b', 'brightness_metric']):
                raise ValueError('RGB and brightness must be in [0,255]')
            if float(row['motion_metric']) < 0:
                raise ValueError('motion must be nonnegative')
    return rows


def pos(rgb, fs):
    """Mean-normalized POS; demean each 1.6 s segment, normalized overlap add."""
    rgb = np.asarray(rgb, dtype=float)
    result = np.zeros(len(rgb))
    counts = np.zeros(len(rgb))
    length = max(2, round(1.6 * fs))
    for start in range(len(rgb) - length + 1):
        segment = rgb[start:start + length]
        means = segment.mean(axis=0)
        if not np.all(np.isfinite(segment)) or np.any(np.abs(means) < 1e-9):
            continue
        normalized = segment / means - 1
        r, g, b = normalized.T
        s1, s2 = g - b, g + b - 2*r
        denominator = np.std(s2)
        if denominator < 1e-12:
            continue
        h = s1 + np.std(s1) / denominator * s2
        result[start:start + length] += h - h.mean()
        counts[start:start + length] += 1
    return np.divide(result, counts, out=np.zeros_like(result), where=counts > 0)


def window_signal(rows, start, end):
    t = np.array([r['timestamp_s'] for r in rows], dtype=float)
    valid = np.array([bool(r['roi_valid']) for r in rows])
    dt = np.diff(t)
    fs = 1 / np.median(dt) if len(dt) else 0
    fraction = float(valid.mean()) if len(valid) else 0.
    good_t = t[valid]
    # Boundaries are part of gap accounting, including missing leading/trailing samples.
    gap = float(np.max(np.diff(np.r_[start, good_t, end]))) if len(good_t) else end-start
    reasons = []
    expected = (end-start)*fs
    if fs < PARAMETERS['min_fs_hz']: reasons.append('sampling_rate_too_low')
    if fraction < .9 or len(t) < expected*.9: reasons.append('insufficient_valid_samples')
    if gap > .2 + 1e-8: reasons.append('long_gap')
    info = dict(valid_fraction=fraction, max_gap_seconds=gap, sampling_rate_hz=float(fs))
    if not len(good_t):
        return None, None, reasons, info
    good = [r for r in rows if r['roi_valid']]
    motion = float(np.quantile([r['motion_metric'] for r in good], .95))
    brightness = np.array([r['brightness_metric'] for r in good])
    if motion > .12: reasons.append('motion')
    if np.min(brightness) < 10 or np.max(brightness) > 245 or np.ptp(brightness) > 40:
        reasons.append('illumination')
    info.update(motion_p95=motion, brightness_min=float(brightness.min()), brightness_max=float(brightness.max()))
    if reasons: return None, None, reasons, info
    uniform_t = np.arange(good_t[0], good_t[-1] + .1/fs, 1/fs)
    rgb = np.array([[r[k] for k in ('r', 'g', 'b')] for r in good])
    uniform_rgb = np.column_stack([np.interp(uniform_t, good_t, rgb[:, i]) for i in range(3)])
    waveform = pos(uniform_rgb, fs)
    if np.std(waveform) < PARAMETERS['min_relative_signal_std']:
        reasons.append('flat_or_low_signal')
    return uniform_t, waveform, reasons, info


def analyze_window(rows, start, end):
    """Analyze one fixed window without offline baseline/calibration state."""
    _, wave, reasons, info = window_signal(rows, start, end)
    hr, concentration = None, None
    if not reasons:
        fs = info['sampling_rate_hz']
        freq, power = welch(detrend(wave), fs=fs, nperseg=len(wave), nfft=max(4096, len(wave)))
        band = (freq >= .7) & (freq <= 3.)
        f, p = freq[band], power[band]
        peak = int(np.argmax(p))
        concentration = float(p[np.abs(f-f[peak]) <= .1].sum() / max(p.sum(), 1e-30))
        if concentration < .35: reasons.append('diffuse_spectrum')
        else: hr = float(f[peak]*60)
    return dict(timestamp_s=float(end), hr_bpm=hr, reasons=reasons,
                peak_concentration=concentration, **info)


def analyze(rows):
    validate_samples(rows)
    times = np.array([r['timestamp_s'] for r in rows])
    first = times[0]
    results, calibration = [], []
    for end in np.arange(first + 20, times[-1] + 1e-7, 1.):
        start = end - 20
        subset = rows[np.searchsorted(times, start):np.searchsorted(times, end, side='right')]
        result = analyze_window(subset, start, end)
        hr = result['hr_bpm']
        # Calibration is fixed to first 60 seconds, never uses later windows.
        if end <= first + 60 and hr is not None: calibration.append(hr)
        ready = end > first + 60 and len(calibration) >= 30
        baseline = float(np.median(calibration)) if ready else None
        result.update(delta_hr_bpm=hr-baseline if hr is not None and ready else None,
                      baseline_hr_bpm=baseline,
                      baseline_status='ready' if ready else ('collecting' if end <= first+60 else 'insufficient_calibration'))
        results.append(result)
    return results


def synthetic(seconds=85, fps=30, bpm=72):
    """Deterministic mathematical fixture, not simulated physiological validity."""
    t = np.arange(0, seconds + .1/fps, 1/fps)
    pulse = np.sin(2*np.pi*bpm/60*t)
    light = 1 + .025*np.sin(2*np.pi*.17*t)
    rgb = np.column_stack([120*(1+.001*pulse), 100*(1+.006*pulse), 80*(1+.002*pulse)]) * light[:, None]
    return [dict(timestamp_s=float(s), r=float(c[0]), g=float(c[1]), b=float(c[2]), roi_valid=True,
                 motion_metric=0., brightness_metric=float(c.mean())) for s, c in zip(t, rgb)]
