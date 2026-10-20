import json
import os
import subprocess
import sys

def run(*args):
    return subprocess.run([sys.executable, '-m', 'rppg', *map(str,args)], capture_output=True, text=True)

def test_help_demo_and_overwrite(tmp_path):
    assert run('--help').returncode == 0
    output = tmp_path / '<demo>'
    result = run('demo', '--output', output)
    assert result.returncode == 0, result.stderr
    report = json.loads((output/'report.json').read_text())
    assert report['provenance']['synthetic'] is True
    assert report['valid_windows'] > 0
    assert 'SYNTHETIC' in (output/'report.html').read_text()
    assert (output/'waveform.png').exists()
    assert run('demo', '--output', output).returncode != 0
    copied = tmp_path/'copy'
    assert run('analyze', '--rgb', output/'rgb.csv', '--output', copied).returncode == 0
    assert json.loads((copied/'report.json').read_text())['provenance']['synthetic'] is True

def test_evaluate_classify_and_html_escape(tmp_path):
    from rppg.report import summary_report
    predictions = tmp_path/'predictions.csv'
    reference = tmp_path/'reference.csv'
    features = tmp_path/'features.csv'
    predictions.write_text('timestamp_s,hr_bpm\n0,72\n1,73\n2,74\n')
    reference.write_text('timestamp_s,hr_bpm\n0,70\n1,71\n2,72\n')
    features.write_text('subject_id,label,hr_bpm\n'+''.join(f'{s},{c},{60+20*c+s}\n' for s in range(6) for c in range(2)))
    result = run('evaluate','--predictions',predictions,'--reference',reference,'--output',tmp_path/'evaluation','--synthetic')
    assert result.returncode == 0, result.stderr
    result = run('classify','--features',features,'--output',tmp_path/'classification','--synthetic')
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path/'classification'/'report.json').read_text())['provenance']['synthetic']
    output = tmp_path/'html'
    output.mkdir()
    summary_report(output, {'value':'<script>alert(1)</script>'}, '<script>')
    content = (output/'report.html').read_text()
    assert '<script>' not in content
    assert '&lt;script&gt;' in content

def test_capture_invalid_bound_rejected_without_device(tmp_path):
    assert run('capture','--duration','nan','--output',tmp_path/'camera').returncode != 0
    assert not (tmp_path/'camera').exists()

def test_explicit_fixture_provenance(tmp_path):
    from rppg.report import write_csv
    from rppg.signal import synthetic, FIELDS
    source = tmp_path/'fixture.csv'
    write_csv(source, synthetic(seconds=21), FIELDS)
    result = run('analyze','--rgb',source,'--synthetic','--output',tmp_path/'result')
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path/'result'/'report.json').read_text())['provenance']['synthetic']
