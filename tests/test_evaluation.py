import pytest
from rppg.evaluation import evaluate, classify

def test_reference_metrics():
    result = evaluate([{'timestamp_s': i, 'hr_bpm': 72+i} for i in range(4)],
                      [{'timestamp_s': i, 'hr_bpm': 70+i} for i in range(4)], .1)
    assert result['mae_bpm'] == result['rmse_bpm'] == 2
    assert result['matched_pairs'] == 4
    assert result['correlation'] == pytest.approx(1)

def test_no_overlap_and_duplicates():
    with pytest.raises(ValueError): evaluate([{'timestamp_s': 0, 'hr_bpm': 70}], [{'timestamp_s': 10, 'hr_bpm': 70}], .1)
    with pytest.raises(ValueError): evaluate([{'timestamp_s': 0, 'hr_bpm': 70}]*2, [{'timestamp_s': 0, 'hr_bpm': 70}], .1)

def features():
    return [{'subject_id': str(s), 'label': str(c), 'hr_bpm': 60+20*c+s} for s in range(6) for c in range(2)]

def test_subject_split_and_leakage():
    result = classify(features())
    for fold in result['folds']:
        assert not set(fold['train_subjects']) & set(fold['test_subjects'])
    assert result['features'] == ['hr_bpm']
    rows = features()
    for r in rows: r['eda'] = 123
    with pytest.raises(ValueError, match='columns'): classify(rows)
    with pytest.raises(ValueError): classify(features()[:2])

def test_single_class_training_fold_rejected():
    rows = [{'subject_id': str(i), 'label': 'rare' if i == 0 else 'common', 'hr_bpm':70} for i in range(3)]
    with pytest.raises(ValueError, match='training fold'): classify(rows)

def test_abstention_coverage_and_undefined_correlation():
    result = evaluate([{'timestamp_s':i, 'hr_bpm':None if i==0 else 70} for i in range(3)],
                      [{'timestamp_s':i,'hr_bpm':70} for i in range(3)])
    assert result['coverage_all_predictions'] == 2/3
    assert result['correlation'] is None

@pytest.mark.parametrize('nonfinite', ['NaN', float('nan'), 'inf', '-inf'])
def test_classify_explicit_nonfinite_excluded_but_blank_imputed(nonfinite):
    rows = features()
    rows += [{'subject_id': '0', 'label': '0', 'hr_bpm': value}
             for value in [nonfinite, '', None]]
    result = classify(rows)
    assert result['included_rows'] == 14
    assert result['excluded_rows'] == [{'row': 14, 'reason': 'invalid_hr'}]
