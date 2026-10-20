"""Bounded video extraction. No recording, GUI, landmark or skin-segmentation claim."""
import time
import cv2
import numpy as np


def extract(*, video=None, camera=None, duration=60., max_seconds=300., roi=None, fps_override=None, status=None):
    camera_mode = camera is not None
    limit = duration if camera_mode else max_seconds
    if not np.isfinite(limit) or not 0 < limit <= 3600:
        raise ValueError('duration/max-seconds must be in (0,3600]')
    if fps_override is not None and (not np.isfinite(fps_override) or not 0 < fps_override <= 240):
        raise ValueError('fps override must be in (0,240]')
    if roi is not None and (len(roi) != 4 or min(roi[:2]) < 0 or min(roi[2:]) <= 0):
        raise ValueError('ROI requires nonnegative x,y and positive width,height')
    cap = cv2.VideoCapture(camera if camera_mode else str(video))
    rows, raw_times = [], []
    fallback = False
    read_failure = False
    try:
        if not cap.isOpened(): raise ValueError('Cannot open source')
        fps = fps_override or cap.get(cv2.CAP_PROP_FPS)
        if not camera_mode and (not np.isfinite(fps) or not 0 < fps <= 240):
            raise ValueError('Unknown/unsupported FPS; supply --fps')
        detector = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        begun = time.monotonic()
        previous_gray = None
        previous_box = None
        while True:
            if camera_mode and time.monotonic() - begun >= limit: break
            ok, frame = cap.read()
            if not ok:
                read_failure = camera_mode
                break
            elapsed = time.monotonic() - begun
            index = len(rows)
            raw_t = float(cap.get(cv2.CAP_PROP_POS_MSEC))/1000 if not camera_mode else elapsed
            # File limit uses nominal FPS even when decoder timestamps are broken.
            if not camera_mode and index / fps > limit: break
            if camera_mode and elapsed > limit: break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            height, width = gray.shape
            box = roi
            if roi is None:
                faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
                box = tuple(faces[0]) if len(faces) == 1 else None
            patches = []
            if box is not None:
                x, y, w, h = map(int, box)
                if roi is not None and (x+w > width or y+h > height):
                    raise ValueError('Manual ROI extends outside frame')
                # Forehead and bilateral cheeks; no fixed fallback when face is missing.
                regions = [(x, y, w, h)] if roi is not None else [
                    (x+.25*w, y+.12*h, .5*w, .18*h),
                    (x+.15*w, y+.5*h, .25*w, .2*h),
                    (x+.6*w, y+.5*h, .25*w, .2*h)]
                for rx, ry, rw, rh in regions:
                    x1, y1 = max(0, int(rx)), max(0, int(ry))
                    x2, y2 = min(width, int(rx+rw)), min(height, int(ry+rh))
                    if x2 > x1 and y2 > y1: patches.append(frame[y1:y2, x1:x2].reshape(-1, 3))
            valid = bool(patches)
            # Global frame difference plus face box displacement: provisional motion proxy.
            small = cv2.resize(gray, (64, 64)).astype(float)
            motion = float(np.mean(np.abs(small-previous_gray))/255) if previous_gray is not None else 0.
            if box is not None and previous_box is not None:
                motion = max(motion, float(np.max(np.abs(np.array(box)-previous_box)))/max(1, box[2]))
            previous_gray, previous_box = small, np.array(box) if box is not None else None
            rgb = np.concatenate(patches).mean(axis=0)[::-1] if valid else [None]*3
            rows.append(dict(timestamp_s=elapsed if camera_mode else index/fps, r=rgb[0], g=rgb[1], b=rgb[2],
                             roi_valid=valid, motion_metric=motion, brightness_metric=float(np.mean(rgb)) if valid else None))
            raw_times.append(raw_t)
            if status and camera_mode: status(rows)
            # Avoid unbounded memory even on broken camera clocks/devices.
            if len(rows) >= 240 * limit + 1: break
        if not rows: raise ValueError('No frames decoded')
        if not camera_mode:
            raw = np.array(raw_times)
            differences = np.diff(raw)
            trustworthy = (fps_override is None and len(raw) > 1 and np.all(np.isfinite(raw))
                           and np.all(differences > 0) and abs(np.median(differences)*fps-1) < .2)
            if trustworthy:
                for row, t in zip(rows, raw-raw[0]): row['timestamp_s'] = float(t)
                rows = [r for r in rows if r['timestamp_s'] <= limit]
            else: fallback = True
        return rows, dict(source=str(camera if camera_mode else video), source_type='camera' if camera_mode else 'video',
                          synthetic=False, roi_mode='manual' if roi is not None else 'single_face_proxy',
                          timestamp_mode='monotonic' if camera_mode else ('frame_index_fps_fallback' if fallback else 'decoder_presentation_time'),
                          fps_override=fps_override, nominal_fps=float(fps) if np.isfinite(fps) else None,
                          decoded_frames=len(rows), invalid_frames=sum(not r['roi_valid'] for r in rows),
                          camera_read_failure=read_failure, limit_seconds=limit, raw_recording=False)
    finally:
        cap.release()
