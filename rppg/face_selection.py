"""Provisional offline geometry continuity, not identity recognition."""
import math

MIN_IOU = .5
MAX_NORMALIZED_DISPLACEMENT = .2
MAX_SIZE_RATIO = 1.25
ACQUISITION_FRAMES = 3
MAX_PRIOR_GAP_SECONDS = .2
PARAMETERS = dict(min_iou=MIN_IOU, max_normalized_displacement=MAX_NORMALIZED_DISPLACEMENT,
                  max_size_ratio=MAX_SIZE_RATIO, acquisition_frames=ACQUISITION_FRAMES,
                  max_prior_gap_seconds=MAX_PRIOR_GAP_SECONDS, uniqueness='exactly_one_matching_candidate',
                  displacement_normalization='previous_box_diagonal', size_ratio='max_symmetric_width_height_ratio',
                  scope='Offline constant-FPS experiment; expiry uses validated actual decoder elapsed time. '
                        'Each decoder step must be finite, positive and within 20% of nominal. '
                        'Explicit FPS overrides are unsupported for continuity',
                  provenance='Fixed conservative engineering heuristics preselected for the offline experiment; '
                             'not fitted to UBFC coverage or validated for identity/physiological accuracy')


def continuous(previous, current):
    x, y, w, h = previous
    a, b, u, v = current
    intersection = max(0., min(x+w, a+u)-max(x, a)) * max(0., min(y+h, b+v)-max(y, b))
    iou = intersection / (w*h + u*v - intersection)
    displacement = math.hypot(a+u/2-x-w/2, b+v/2-y-h/2) / math.hypot(w, h)
    ratio = max(w/u, u/w, h/v, v/h)
    return iou >= MIN_IOU and displacement <= MAX_NORMALIZED_DISPLACEMENT and ratio <= MAX_SIZE_RATIO


class FaceSelector:
    """Replay select(candidates_xywh, timestamp_s) in strictly increasing time order.

    Returns only a current candidate, never an old box. Missing detections retain
    an acquired reference for at most .2 seconds; ambiguity/jumps clear it at once.
    """
    def __init__(self):
        self._prior = self._pending = None
        self._prior_time = self._pending_time = None
        self._count = 0
        self._last_time = None

    def select(self, candidates, timestamp_s):
        t = float(timestamp_s)
        if not math.isfinite(t) or (self._last_time is not None and t <= self._last_time):
            raise ValueError('Face selection requires finite strictly increasing timestamps')
        boxes = [tuple(map(float, box)) for box in candidates]
        if any(len(box) != 4 or not all(math.isfinite(v) for v in box) or min(box[2:]) <= 0 for box in boxes):
            raise ValueError('Face candidates require finite x,y and positive width,height')
        self._last_time = t
        if self._prior_time is not None and t-self._prior_time > MAX_PRIOR_GAP_SECONDS + 1e-9:
            self._prior = self._prior_time = None
        if self._pending_time is not None and t-self._pending_time > MAX_PRIOR_GAP_SECONDS + 1e-9:
            self._pending = self._pending_time = None
            self._count = 0
        selected = None
        if not boxes:
            self._pending = self._pending_time = None
            self._count = 0
            reason = 'no_face'
        elif self._prior is not None:
            matches = [box for box in boxes if continuous(self._prior, box)]
            if len(matches) == 1:
                selected = matches[0]
                reason = 'unique_continuous_candidate'
            else:
                self._prior = self._prior_time = None
                self._pending = self._pending_time = None
                self._count = 0
                reason = 'ambiguous_candidates' if len(matches) > 1 else 'position_or_size_jump'
        elif len(boxes) != 1:
            self._pending = self._pending_time = None
            self._count = 0
            reason = 'multiple_without_prior'
        else:
            box = boxes[0]
            if self._pending is not None and not continuous(self._pending, box):
                self._pending = self._pending_time = None
                self._count = 0
                reason = 'acquisition_jump'
            else:
                self._pending, self._pending_time = box, t
                self._count += 1
                reason = 'acquiring_single_face'
                if self._count >= ACQUISITION_FRAMES:
                    selected = box
                    reason = 'acquired_single_face'
        if selected is not None:
            self._prior, self._prior_time = selected, t
            self._pending = self._pending_time = None
            self._count = 0
        return dict(timestamp_s=t, face_count=len(boxes), candidates=boxes, selected_box=selected,
                    status='selected' if selected is not None else 'abstained', reason=reason)
