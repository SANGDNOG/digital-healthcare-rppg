"""Reference HR comparison and deliberately small subject-disjoint baseline."""
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import balanced_accuracy_score, f1_score, confusion_matrix, recall_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def timed(rows):
    ts = np.array([float(r['timestamp_s']) for r in rows])
    if not len(ts) or not np.all(np.isfinite(ts)) or np.any(np.diff(ts) <= 0):
        raise ValueError('timestamps must be finite, unique and increasing')
    for r in rows:
        if r.get('hr_bpm') not in (None, '') and not np.isfinite(float(r['hr_bpm'])):
            raise ValueError('nonfinite HR')
    return ts


def evaluate(predictions, reference, tolerance=.5):
    if not np.isfinite(tolerance) or tolerance < 0: raise ValueError('invalid tolerance')
    pt, rt = timed(predictions), timed(reference)
    if pt[-1] < rt[0] or rt[-1] < pt[0]: raise ValueError('No timestamp overlap')
    pairs = []
    valid_predictions = sum(r.get('hr_bpm') not in (None, '') for r in predictions)
    for t, p in zip(pt, predictions):
        if p.get('hr_bpm') in (None, ''): continue
        i = int(np.searchsorted(rt, t))
        candidates = [j for j in [i-1, i] if 0 <= j < len(rt)]
        j = min(candidates, key=lambda j: abs(rt[j]-t))
        if abs(rt[j]-t) <= tolerance and reference[j].get('hr_bpm') not in (None, ''):
            pairs.append((float(p['hr_bpm']), float(reference[j]['hr_bpm'])))
    if not pairs: raise ValueError('No valid matched pairs within tolerance')
    p, r = np.array(pairs).T
    return dict(prediction_rows=len(predictions), reference_rows=len(reference), valid_predictions=valid_predictions,
                matched_pairs=len(p), coverage_all_predictions=len(p)/len(predictions),
                coverage_valid_predictions=len(p)/valid_predictions, tolerance_seconds=tolerance,
                matching='nearest timestamp, reference reuse allowed, no time shift',
                mae_bpm=float(np.mean(abs(p-r))), rmse_bpm=float(np.sqrt(np.mean((p-r)**2))),
                correlation=float(np.corrcoef(p,r)[0,1]) if len(p)>1 and np.std(p)>0 and np.std(r)>0 else None)


def classify(rows):
    required = {'subject_id', 'label', 'hr_bpm'}
    if not rows or not required <= rows[0].keys(): raise ValueError('Required columns: subject_id,label,hr_bpm')
    # Delta intentionally excluded: provenance cannot be established from a feature column.
    extra = set().union(*(r.keys() for r in rows)) - required
    if extra: raise ValueError('Unapproved feature columns: ' + ', '.join(sorted(extra)))
    kept, excluded = [], []
    for i, row in enumerate(rows):
        if not str(row['subject_id']).strip() or not str(row['label']).strip():
            excluded.append(dict(row=i+2, reason='missing_subject_or_label')); continue
        value = row['hr_bpm']
        missing = value in ('', None)
        try: value = np.nan if missing else float(value)
        except (TypeError, ValueError): raise ValueError('HR must be numeric or blank')
        if not missing and (not np.isfinite(value) or not 30 <= value <= 220):
            excluded.append(dict(row=i+2, reason='invalid_hr')); continue
        kept.append((str(row['subject_id']), str(row['label']), value))
    if not kept: raise ValueError('No usable rows')
    groups, y, values = zip(*kept)
    groups, y, x = np.array(groups), np.array(y), np.array(values)[:, None]
    subjects, labels = np.unique(groups), np.unique(y)
    if len(subjects)<3 or len(labels)<2: raise ValueError('Need >=3 subjects and >=2 classes')
    models = {'dummy': DummyClassifier(strategy='most_frequent'),
              'random_forest': RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42, n_jobs=1)}
    predictions = {name: np.empty(len(y), dtype=y.dtype) for name in models}
    folds = []
    for train, test in GroupKFold(n_splits=min(5, len(subjects))).split(x, y, groups):
        if set(y[train]) != set(labels): raise ValueError('Every training fold must contain all classes')
        if np.all(np.isnan(x[train])): raise ValueError('Training fold has no HR values')
        folds.append(dict(train_subjects=sorted(set(groups[train])), test_subjects=sorted(set(groups[test]))))
        for name, model in models.items():
            pipeline = make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), model)
            pipeline.fit(x[train], y[train])
            predictions[name][test] = pipeline.predict(x[test])
    metrics = {}
    for name, pred in predictions.items():
        metrics[name] = dict(balanced_accuracy=float(balanced_accuracy_score(y, pred)),
                             macro_f1=float(f1_score(y, pred, average='macro', zero_division=0)),
                             confusion_matrix=confusion_matrix(y,pred,labels=labels).tolist(),
                             per_class_recall=dict(zip(labels, recall_score(y,pred,labels=labels,average=None,zero_division=0).tolist())))
    return dict(features=['hr_bpm'], labels=labels.tolist(), folds=folds, metrics=metrics,
                included_rows=len(y), excluded_rows=excluded, seed=42,
                limitation='HR-only research baseline; labels supplied by user; no stress measurement claim')
