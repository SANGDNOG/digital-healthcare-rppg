"""Explicit local CLI. Camera acquisition occurs only in the capture command."""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
from .signal import analyze, synthetic
from .report import (read_csv, read_rgb, make_output, pipeline, summary_report, fingerprint)
from .evaluation import evaluate, classify
from .video import extract


def roi_arg(value):
    try:
        parts = tuple(map(int, value.split(',')))
        if len(parts) != 4 or min(parts[:2]) < 0 or min(parts[2:]) <= 0: raise ValueError()
        return parts
    except ValueError: raise argparse.ArgumentTypeError('ROI must be x,y,width,height with nonnegative origin and positive size')


def parser():
    p = argparse.ArgumentParser(description='Local research POS rPPG; provisional quality, no medical/stress claim')
    commands = p.add_subparsers(dest='command', required=True)
    a = commands.add_parser('analyze', help='Analyze a video or timestamped RGB CSV')
    source = a.add_mutually_exclusive_group(required=True)
    source.add_argument('--video', type=Path)
    source.add_argument('--rgb', type=Path)
    a.add_argument('--max-seconds', type=float, default=300)
    a.add_argument('--fps', type=float, help='Explicit file FPS override; forces index/FPS timestamps')
    a.add_argument('--roi', type=roi_arg)
    a.add_argument('--face-policy', choices=('strict', 'continuity'), default='strict',
                   help='Offline video face selection; continuity uses provisional geometry history')
    a.add_argument('--synthetic', action='store_true', help='Label generated video/RGB fixtures as synthetic')
    c = commands.add_parser('capture', help='Explicit opt-in camera; no raw recording, maximum 3600 seconds')
    c.add_argument('--camera', type=int, default=0)
    c.add_argument('--duration', type=float, required=True)
    c.add_argument('--roi', type=roi_arg)
    d = commands.add_parser('demo', help='Deterministic SYNTHETIC mathematical fixture, not physiological validation')
    e = commands.add_parser('evaluate', help='Timestamped HR reference comparison; no raw BVP conversion/time shifting')
    e.add_argument('--predictions', type=Path, required=True)
    e.add_argument('--reference', type=Path, required=True)
    e.add_argument('--tolerance', type=float, default=.5)
    f = commands.add_parser('classify', help='Subject-disjoint HR-only baseline; user-supplied labels')
    f.add_argument('--features', type=Path, required=True)
    f.add_argument('--synthetic', action='store_true', help='Label fixture classification as synthetic')
    e.add_argument('--synthetic', action='store_true', help='Label fixture evaluation as synthetic')
    for sub in [a,c,d,e,f]: sub.add_argument('--output', type=Path, required=True)
    return p


def inherited_provenance(path):
    sidecar = path.with_suffix('.provenance.json')
    if not sidecar.exists(): return dict(synthetic=False, synthetic_status='unknown; no trusted sidecar supplied')
    provenance = json.loads(sidecar.read_text())
    if provenance.get('rgb_sha256') != fingerprint(path):
        raise ValueError('RGB provenance checksum mismatch')
    return provenance


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'capture' and (not np.isfinite(args.duration) or not 0 < args.duration <= 3600):
            raise ValueError('--duration must be in (0,3600]')
        if args.command == 'analyze' and args.rgb and (args.roi is not None or args.fps is not None):
            raise ValueError('--roi/--fps apply only to video input')
        if args.command == 'analyze' and args.face_policy == 'continuity' and (args.rgb or args.roi is not None or args.fps is not None):
            raise ValueError('--face-policy continuity requires video without --roi/--fps')
        output = make_output(args.output)
        if args.command in ('evaluate', 'classify'):
            if args.command == 'evaluate':
                report = evaluate(read_csv(args.predictions), read_csv(args.reference), args.tolerance)
                provenance = dict(predictions=str(args.predictions), reference=str(args.reference),
                                  predictions_sha256=fingerprint(args.predictions), reference_sha256=fingerprint(args.reference))
                sibling = args.predictions.parent/'report.json'
                inherited = json.loads(sibling.read_text()).get('provenance', {}).get('synthetic', False) if sibling.exists() else False
            else:
                report = classify(read_csv(args.features))
                provenance = dict(features_source=str(args.features), features_sha256=fingerprint(args.features))
                inherited = False
            report['provenance'] = dict(provenance, synthetic=args.synthetic or inherited,
                                        data_claim='user supplied; no dataset authenticity or timing alignment inferred')
            summary_report(output, report, args.command + ' research report')
        else:
            if args.command == 'demo':
                rows = synthetic()
                provenance = dict(synthetic=True, source_type='synthetic', source='deterministic 72 bpm mathematical RGB fixture',
                                  roi_mode='synthetic', timestamp_mode='synthetic_uniform', seed='deterministic_no_randomness')
            elif args.command == 'analyze' and args.rgb:
                rows = read_rgb(args.rgb)
                provenance = dict(inherited_provenance(args.rgb), source=str(args.rgb), source_type='rgb', input_sha256=fingerprint(args.rgb))
            else:
                last_status = [-1.]
                def status(buffer):
                    now = buffer[-1]['timestamp_s']
                    if now-last_status[0] >= 1:
                        last_status[0] = now
                        # Only last 21 seconds used for live feedback, baseline appears in final report.
                        tail = [r for r in buffer if r['timestamp_s'] >= now-21]
                        results = analyze(tail) if len(tail)>1 else []
                        latest = results[-1] if results else dict(hr_bpm=None, reasons=['collecting_20s'])
                        print(json.dumps(dict(elapsed_s=round(now,1), hr_bpm=latest['hr_bpm'], reasons=latest['reasons'])), flush=True)
                if args.command == 'capture':
                    rows, provenance = extract(camera=args.camera, duration=args.duration, roi=args.roi, status=status)
                else:
                    rows, provenance = extract(video=args.video, max_seconds=args.max_seconds, roi=args.roi, fps_override=args.fps, face_policy=args.face_policy)
                    provenance['input_sha256'] = fingerprint(args.video)
            if args.command == 'analyze' and args.synthetic:
                provenance['synthetic'] = True
                provenance['synthetic_label_source'] = 'explicit_user_flag'
            report = pipeline(rows, output, provenance)
        print(json.dumps(dict(output=str(output), status='complete', synthetic=report['provenance']['synthetic']), allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
