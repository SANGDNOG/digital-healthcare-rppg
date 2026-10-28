"""Bounded Windows packaging checks, without cameras or browser activation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('windows_builder', ROOT / 'packaging/windows/build_package.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


@pytest.fixture
def packaged(tmp_path, monkeypatch):
    repo = tmp_path / 'source with spaces'
    files = ('scripts/export_live_runtime.py', *(__import__('runpy').run_path(
        str(ROOT / 'scripts/export_live_runtime.py'))['FILES']),
        *(f'packaging/windows/{name}' for name in builder.TEMPLATES))
    for name in files:
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    for name in ('guide', 'results'):
        (repo / f'packaging/windows/{name}-fragment.html').write_text(f'<section id="{dict(guide="experiment-guide", results="project-results")[name]}"><h2>{name}</h2><p>Public text.</p></section>')
    # These must never be included by a recursive copy.
    (repo / '.env').write_text('PRIVATE=secret')
    (repo / 'rppg/private.txt').write_text('private')
    (repo / 'docs').mkdir()
    (repo / 'docs/public.html').write_text('<p>Public report</p>')
    (repo / 'docs/private.txt').write_text('private')
    uv = tmp_path / 'uv.exe'
    uv.write_bytes(b'MZ test binary, not executed')
    license = tmp_path / 'uv-LICENSE-MIT'
    license.write_text('test license')
    monkeypatch.setattr(builder.subprocess, 'check_output', lambda *args, **kwargs: 'a' * 40)
    output = tmp_path / 'package with spaces'
    manifest = builder.build(repo, output, uv, license, ['docs/public.html'])
    return repo, output, uv, license, manifest


def test_explicit_allowlist_hashes_and_source_identity(packaged):
    repo, output, _, _, manifest = packaged
    metadata = json.loads((output / 'package.json').read_text())
    assert metadata['source_commit'] == 'a' * 40
    assert metadata['uv_version'] == '0.13.6'
    assert metadata['uv_sha256'] == builder.digest((output / 'tools/uv.exe').read_bytes())
    for line in (output / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    actual = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
    assert actual == ({'runtime/' + name for name in manifest['files']} |
                      {'runtime/manifest.json', 'package.json', 'SHA256SUMS',
                       'tools/uv.exe', 'tools/uv-LICENSE-MIT', 'docs/public.html', *builder.TEMPLATES})
    unsigned = {key: manifest[key] for key in ('schema', 'runtime', 'files')}
    assert manifest['runtime_id'] == builder.digest(builder.canonical(unsigned))
    for name, expected in manifest['files'].items():
        data = (output / 'runtime' / name).read_bytes()
        assert builder.digest(data) == expected
        if name != 'rppg/live_web/index.html':
            assert data == (repo / name).read_bytes()
    index = (output / 'runtime/rppg/live_web/index.html').read_text()
    assert '127.0.0.1:8765' not in index
    assert 'href="#experiment-guide"' in index and 'id="experiment-guide"' in index
    assert 'href="#project-results"' in index and 'id="project-results"' in index
    assert '<h2>guide</h2>' in index and '<h2>results</h2>' in index
    combined = b'\n'.join(p.read_bytes() for p in output.rglob('*') if p.is_file())
    for forbidden in (b'ssh ', b'/home/', b'/Users/', b'PRIVATE=secret', b'sangdong'):
        assert forbidden not in combined


def test_launcher_quoted_local_paths_and_exact_dependencies(packaged):
    _, output, *_ = packaged
    launcher = (output / 'start.cmd').read_bytes().decode('ascii')
    assert 'DisableDelayedExpansion' in launcher
    assert 'cd /d "%~dp0"' in launcher
    assert 'set "UV_CACHE_DIR=%~dp0.cache\\uv"' in launcher
    assert 'set "UV_PYTHON_INSTALL_DIR=%~dp0.python"' in launcher
    venv = '"%~dp0tools\\uv.exe" venv --no-config --no-project --managed-python --python 3.11.17 "%~dp0.venv"'
    sync = '"%~dp0tools\\uv.exe" pip sync --no-config --python "%~dp0.venv\\Scripts\\python.exe" "%~dp0requirements.txt"'
    execute = '"%~dp0.venv\\Scripts\\python.exe" -B "%~dp0start.py" %*'
    assert launcher.index('set "PYTHONUTF8=1"') < launcher.index(venv) < launcher.index(sync) < launcher.index(execute)
    assert 'if exist "%~dp0.venv\\Scripts\\python.exe" goto sync' in launcher
    assert launcher.count('if errorlevel 1 goto finished') == 2
    assert '--with-requirements' not in launcher  # Avoid UTF-8 ephemeral .pth on Python 3.11 CP949.
    assert (output / 'requirements.txt').read_text().splitlines() == [
        'numpy==2.4.6', 'scipy==1.17.1', 'opencv-python-headless==4.11.0.86']
    assert 'powershell' not in launcher.lower()


def test_runtime_actual_validator_rejects_extra_and_hash_damage(packaged):
    _, output, *_ = packaged
    # Validator must reject these before any installed-version comparison.
    runner = """
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from rppg.live import validate_runtime_manifest
try:
    validate_runtime_manifest(Path(sys.argv[1]) / 'manifest.json')
except ValueError as exc:
    print(exc)
else:
    raise AssertionError('damaged runtime accepted')
"""
    runtime = output / 'runtime'
    extra = runtime / 'unlisted.txt'
    extra.write_text('extra')
    result = subprocess.run([sys.executable, '-B', '-c', runner, str(runtime)],
                            capture_output=True, text=True, check=True)
    assert 'unexpected release entry' in result.stdout
    extra.unlink()
    target = runtime / 'rppg/live_web/live.js'
    target.write_bytes(target.read_bytes() + b'\n')
    result = subprocess.run([sys.executable, '-B', '-c', runner, str(runtime)],
                            capture_output=True, text=True, check=True)
    assert 'file hash mismatch' in result.stdout


def test_no_overwrite_and_public_docs_paths(packaged, tmp_path):
    repo, output, uv, license, _ = packaged
    with pytest.raises(FileExistsError):
        builder.build(repo, output, uv, license)
    for name in ('../.env', '/tmp/private', 'rppg/live.py', 'docs/../.env', 'docs\\private.txt'):
        with pytest.raises(ValueError):
            builder.build(repo, tmp_path / 'rejected', uv, license, [name])
    (repo / 'docs/link').symlink_to(repo / '.env')
    with pytest.raises(ValueError, match='symlink'):
        builder.build(repo, tmp_path / 'rejected', uv, license, ['docs/link'])
    assert not (tmp_path / 'rejected').exists()


def test_missing_fragment_and_changed_index_fail_closed(packaged, tmp_path):
    repo, _, uv, license, _ = packaged
    index = repo / 'rppg/live_web/index.html'
    index.write_text(index.read_text().replace(builder.RESULTS_LINK, 'href="/changed"'))
    with pytest.raises(ValueError, match='index changed'):
        builder.build(repo, tmp_path / 'rejected', uv, license)
    (repo / 'packaging/windows/guide-fragment.html').unlink()
    with pytest.raises(ValueError):
        builder.build(repo, tmp_path / 'rejected', uv, license)


def test_check_no_bind_and_browser_after_bind(monkeypatch):
    spec = importlib.util.spec_from_file_location('windows_start', ROOT / 'packaging/windows/start.py')
    start = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(start)
    import rppg.live as live
    server = Mock()
    server.__enter__ = Mock(return_value=server)
    server.__exit__ = Mock(return_value=False)
    server.server_port = 12345
    events = []
    def bind(**kwargs):
        assert kwargs['port'] == 0
        assert kwargs['runtime_manifest'].name == 'manifest.json'
        events.append('bound')
        return server
    monkeypatch.setattr(live, 'LiveServer', Mock(side_effect=bind))
    monkeypatch.setattr(live, 'validate_runtime_manifest', Mock(return_value='verified'))
    monkeypatch.setattr(start.webbrowser, 'open', lambda url: events.append(url))
    monkeypatch.setattr(sys, 'path', sys.path.copy())
    assert start.main(['--check']) == 0
    live.LiveServer.assert_not_called()
    assert not events
    monkeypatch.delenv('RPPG_NO_BROWSER', raising=False)
    assert start.main([]) == 0
    assert events == ['bound', 'http://127.0.0.1:12345/']
    server.serve_forever.assert_called_once()
    events.clear()
    monkeypatch.setenv('RPPG_NO_BROWSER', '1')
    assert start.main([]) == 0
    assert events == ['bound']


def test_both_vendor_licenses_preserved(packaged, tmp_path):
    repo, _, uv, mit, _ = packaged
    apache = tmp_path / 'uv-LICENSE-APACHE'
    apache.write_text('Apache test license')
    output = tmp_path / 'both licenses'
    builder.build(repo, output, uv, [mit, apache])
    for license in (mit, apache):
        assert (output / 'tools' / license.name).read_bytes() == license.read_bytes()
