"""CSV interchange and self-contained local research reports."""
import csv
import hashlib
import html
import json
from pathlib import Path
import numpy as np
from .signal import FIELDS, PARAMETERS, analyze, validate_samples, window_signal


def read_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError('Missing or duplicate CSV headers')
        rows = list(reader)
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError('Malformed CSV row length')
    return rows


def read_rgb(path):
    rows = read_csv(path)
    for row in rows:
        if not set(FIELDS) <= row.keys(): raise ValueError('Missing RGB interchange fields')
        token = row['roi_valid'].lower()
        if token not in ('true', 'false', '1', '0'): raise ValueError('roi_valid must be true/false/1/0')
        row['roi_valid'] = token in ('true', '1')
        for key in FIELDS:
            if key != 'roi_valid': row[key] = float(row[key]) if row[key] != '' else None
    return validate_samples(rows)


def write_csv(path, rows, fields):
    with open(path, 'w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k,v in row.items() if k in fields})


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False, ensure_ascii=False) + '\n', encoding='utf-8')


def fingerprint(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): digest.update(block)
    return digest.hexdigest()


def make_output(path):
    path = Path(path)
    # Atomic mkdir refuses any existing output, including empty directories.
    path.mkdir(parents=True, exist_ok=False)
    return path


def summary_report(output, report, title):
    write_json(output/'report.json', report)
    marker = 'SYNTHETIC — mathematical fixture only' if report.get('provenance', {}).get('synthetic') else 'RESEARCH — unvalidated physiological accuracy'
    text = html.escape(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    title = html.escape(title)
    plot = '<img src="waveform.png" alt="POS relative waveform and HR">' if (output/'waveform.png').exists() else ''
    (output/'report.html').write_text(f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{title}</title>'
                                     '<style>body{max-width:1100px;margin:2em auto;font:16px sans-serif}pre{white-space:pre-wrap;overflow-wrap:anywhere}img{width:100%}.notice{padding:1em;background:#fff0ba}</style>'
                                     f'<h1>{title}</h1><p class="notice">{marker}</p>'
                                     '<p>Provisional quality gates. No medical or psychological stress claim. Waveform in relative units.</p>'
                                     f'{plot}<pre>{text}</pre></html>', encoding='utf-8')


def pipeline(rows, output, provenance):
    windows = analyze(rows)
    valid = [w for w in windows if w['hr_bpm'] is not None]
    write_csv(output/'rgb.csv', rows, FIELDS)
    write_json(output/'rgb.provenance.json', dict(provenance, rgb_sha256=fingerprint(output/'rgb.csv')))
    fields = list(windows[0]) if windows else ['timestamp_s', 'hr_bpm', 'delta_hr_bpm', 'reasons']
    write_csv(output/'windows.csv', windows, fields)
    times = np.array([r['timestamp_s'] for r in rows])
    gaps = [dict(start_s=float(times[i]), end_s=float(times[i+1]), gap_seconds=float(g))
            for i,g in enumerate(np.diff(times)) if g > PARAMETERS['max_gap_seconds'] + 1e-8]
    report = dict(provenance=provenance, parameters=PARAMETERS, total_samples=len(rows),
                  invalid_samples=sum(not r['roi_valid'] for r in rows),
                  total_windows=len(windows), valid_windows=len(valid),
                  last_valid_timestamp_s=valid[-1]['timestamp_s'] if valid else None,
                  time_gaps=gaps, windows=windows, failures=[dict(timestamp_s=w['timestamp_s'], reasons=w['reasons']) for w in windows if w['reasons']],
                  limitations=['Not validated against real physiological reference data',
                               'Face rectangles and forehead/cheek proxies are not skin segmentation',
                               'POS alone and synthetic tests do not establish physiological validity',
                               'No PRV or psychological stress score'],
                  status='processed' if windows else 'insufficient_duration_for_20s_window')
    # Plot each accepted trailing window separately; never bridge rejected gaps.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), constrained_layout=True)
    # Latest accepted waveform is enough to inspect; HR plot includes all windows with NaN gaps.
    if valid:
        end = valid[-1]['timestamp_s']
        subset = rows[np.searchsorted(times,end-20):np.searchsorted(times,end,side='right')]
        t, wave, _, _ = window_signal(subset,end-20,end)
        axes[0].plot(t, wave, linewidth=.7)
    axes[0].set(ylabel='POS (relative units)', xlabel='Time (s)', title='Latest accepted trailing window')
    axes[1].plot([w['timestamp_s'] for w in windows], [w['hr_bpm'] if w['hr_bpm'] is not None else np.nan for w in windows])
    axes[1].set(ylabel='HR (bpm)', xlabel='Time (s)')
    if valid:
        values = [w['hr_bpm'] for w in valid]
        axes[1].set_ylim(min(values)-3, max(values)+3)
    axes[1].ticklabel_format(axis='y', style='plain', useOffset=False)
    fig.suptitle('SYNTHETIC — not physiological validation' if provenance.get('synthetic') else 'Research baseline — provisional quality')
    fig.savefig(output/'waveform.png', dpi=130)
    plt.close(fig)
    summary_report(output, report, 'Local POS rPPG report')
    return report
