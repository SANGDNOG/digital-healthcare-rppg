"""No camera access: fake clocks/detectors and in-memory PNG HTTP requests."""
import http.client
import json
import struct
import threading
import uuid

import cv2
import numpy as np
import pytest
from rppg.live import Failure, LiveServer, LiveState, Sampler, decode_png
from rppg.signal import analyze, analyze_window, synthetic


class Clock:
    value = 0.
    def __call__(self): return self.value


class Detector:
    faces = [(10, 5, 60, 70)]
    def detectMultiScale(self, *_args, **_kwargs): return self.faces


def png(frame=None):
    frame = np.full((80, 100, 3), 100, np.uint8) if frame is None else frame
    return cv2.imencode('.png', frame)[1].tobytes()


def state_session():
    clock, detector = Clock(), Detector()
    state = LiveState(clock, lambda: Sampler(detector))
    sid = state.start(str(uuid.uuid4()))['session_id']
    return state, sid, clock, detector


@pytest.fixture
def api():
    clock = Clock()
    state = LiveState(clock, lambda: Sampler(Detector()))
    server = LiveServer(0, state)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    host = f'127.0.0.1:{server.server_port}'

    def request(path, body=None, headers=None, method=None):
        method = method or ('GET' if body is None else 'POST')
        h = {'Host': host, 'Origin': 'http://'+host, 'X-RPPG-Token': state.token,
             'Content-Type': 'application/json'}
        h.update(headers or {})
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        conn.request(method, path, body=body, headers=h)
        response = conn.getresponse()
        data = response.read()
        result = response.status, json.loads(data), dict(response.getheaders())
        conn.close()
        return result

    yield request, state, clock, server
    server.shutdown()
    server.server_close()
    worker.join()


def session(request):
    return request('/api/session', json.dumps({'client_id': str(uuid.uuid4())}))[1]['session_id']


def test_health_config_and_headers(api):
    request, state, _, server = api
    status, health, headers = request('/api/health')
    assert status == 200 and health == dict(service='rppg-live', protocol=1, boot_id=state.boot_id,
                                                 execution_mode='remote', runtime_id=None, active_session=False)
    assert server.server_address[0] == '127.0.0.1'
    assert headers['Cache-Control'] == 'no-store'
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert "frame-ancestors 'none'" in headers['Content-Security-Policy']
    assert request('/api/config')[1]['token'] == state.token
    for path in ['/../signal.py', '/rppg/signal.py', '/%2e%2e/signal.py', '/api/config?token=x']:
        assert request(path)[0] == 404


@pytest.mark.parametrize('headers,code', [({'Host':'evil.test'}, 'host_rejected'),
    ({'Origin':'http://evil.test'}, 'origin_rejected'), ({'Origin':''}, 'origin_rejected'),
    ({'Sec-Fetch-Site':'cross-site'}, 'cross_site'), ({'X-RPPG-Token':'bad'}, 'token_rejected')])
def test_security(api, headers, code):
    response = api[0]('/api/session', '{}', headers)
    assert response[0] == 403 and response[1]['error'] == code
    assert 'Access-Control-Allow-Origin' not in response[2]


def test_config_foreign_origin_and_duplicate_host(api):
    request, _, _, server = api
    assert request('/api/config', headers={'Origin':'null'})[0] == 403
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
    conn.putrequest('GET', '/api/config')
    conn.putheader('Host', f'127.0.0.1:{server.server_port}')
    conn.endheaders()
    response = conn.getresponse()
    assert response.status == 400
    assert json.loads(response.read())['error'] == 'duplicate_header'
    conn.close()


@pytest.mark.parametrize('body', ['[]','null','{', '{}', '{"client_id":1}', '{"client_id":"not-a-uuid"}'])
def test_bad_json_and_clients(api, body):
    assert api[0]('/api/session', body)[0] == 400


def test_lifecycle_and_expiry(api):
    request, state, clock, server = api
    client = str(uuid.uuid4())
    body = json.dumps({'client_id':client})
    sid = request('/api/session', body)[1]['session_id']
    assert request('/api/session', body)[1]['session_id'] == sid
    assert request('/api/session', json.dumps({'client_id':str(uuid.uuid4())}))[0] == 409
    assert request('/api/stop', '{"session_id":"other"}')[0] == 409
    assert state.session['id'] == sid
    clock.value = 10
    server.service_actions()
    assert state.session is None
    assert request('/api/stop', json.dumps({'session_id':sid}))[1] == {'stopped': True}
    new = request('/api/session', body)[1]['session_id']
    assert new != sid
    assert request('/api/stop', json.dumps({'session_id':sid}))[0] == 200
    assert state.session['id'] == new
    clock.value = 310
    state.session['last'] = 309
    server.service_actions()
    assert state.session is None


def test_png_http_bounds_and_processing_lock(api):
    request, state, _, _ = api
    sid = session(request)
    h = {'Content-Type':'image/png', 'X-Session-ID':sid, 'X-Frame-Seq':'0', 'X-Capture-Time':'100'}
    for data, code in [(b'bad','invalid_png'), (png(np.zeros((481, 10, 3), np.uint8)),'image_dimensions')]:
        response = request('/api/frame', data, h)
        assert response[1]['error'] == code and state.session['seq'] == -1
    assert request('/api/frame', png(), {**h,'Content-Length':str(2*1024*1024+1)})[0] == 413
    assert request('/api/frame', png(), {**h,'Transfer-Encoding':'chunked'})[0] == 400
    assert request('/api/frame', png(), {**h,'Content-Type':'image/jpeg'})[0] == 415
    state.lock.acquire()
    try: assert request('/api/frame', png(), h)[1]['error'] == 'processing_busy'
    finally: state.lock.release()
    status, result, _ = request('/api/frame', png(), h)
    assert status == 200 and result['seq'] == 0 and result['face_count'] == 1
    assert result['face_box'] == [10,5,60,70] and result['analysis'] is None
    assert result['frame_width'] == 100 and result['sample_count'] == 1


@pytest.mark.parametrize('seq,capture,code', [('0','101','sequence_order'), ('1','nan','invalid_timestamp'),
    ('1','inf','invalid_timestamp'), ('1','99','capture_order_or_rate'), ('1','100.001','capture_order_or_rate'),
    ('1','103','capture_drift'), ('-1','101','invalid_sequence'), ('1','-1','invalid_timestamp')])
def test_timestamps_do_not_mutate(seq, capture, code):
    state, sid, clock, _ = state_session()
    state.frame(sid, '0', '100', png())
    clock.value = 1/15
    with pytest.raises(Failure) as exc: state.frame(sid, seq, capture, png())
    assert exc.value.code == code
    assert state.session['seq'] == 0 and len(state.session['sampler'].rows) == 1
    result = state.frame(sid, '1', str(100+1/15), png())
    assert result['server_receive_lag_s'] == pytest.approx(0)


def test_capture_clock_not_arrival_clock():
    state, sid, clock, _ = state_session()
    for i in range(31):
        clock.value = i/15 + (0.04 if i%2 else 0)
        result = state.frame(sid, str(i), str(500+i/15), png())
    assert result['elapsed_s'] == 2
    rows = state.session['sampler'].rows
    assert np.diff([r['timestamp_s'] for r in rows]) == pytest.approx(np.full(30,1/15))
    clock.value = 5
    with pytest.raises(Failure) as exc: state.frame(sid, '31', str(500+31/15), png())
    assert exc.value.code == 'capture_drift'


def test_same_rois_motion_and_immediate_reasons():
    detector = Detector()
    sampler = Sampler(detector)
    frame = np.zeros((80,100,3), np.uint8)
    frame[:40] = (60,100,140)
    frame[40:] = (90,110,130)
    result = sampler.extract(frame, 0)
    # video.py's exact integer-truncated forehead and bilateral cheek masks.
    patches = [frame[13:26,25:55], frame[40:54,19:34], frame[40:54,46:61]]
    expected = np.concatenate([p.reshape(-1,3) for p in patches]).mean(axis=0)[::-1]
    assert [sampler.rows[-1][k] for k in ('r','g','b')] == pytest.approx(expected)
    assert not result['frame_reasons']
    detector.faces = [(30,5,60,70)]
    assert 'motion' in sampler.extract(frame, 1/15)['frame_reasons']
    detector.faces = []
    assert sampler.extract(frame, 2/15)['frame_reasons'] == ['no_face']
    detector.faces = [(10,5,60,70)]
    assert 'illumination' in sampler.extract(np.zeros_like(frame), 3/15)['frame_reasons']


def test_synthetic_fixed_windows_bounds_and_resets():
    sampler = Sampler(Detector())
    events = []
    for row in synthetic(seconds=80, fps=15):
        sampler.add(row, [])
        if sampler.analysis and (not events or events[-1]['event_id'] != sampler.analysis['event_id']):
            events.append(sampler.analysis)
    assert len(events) == 61
    assert [e['timestamp_s'] for e in events] == list(range(20,81))
    assert events[0]['event_id'] == '1:0' and events[-1]['event_id'] == '1:60'
    assert all(abs(e['hr_bpm']-72) < 1 for e in events)
    assert all('baseline_hr_bpm' not in e and 'delta_hr_bpm' not in e for e in events)
    assert len(sampler.rows) <= 331 and sampler.rows[-1]['timestamp_s']-sampler.rows[0]['timestamp_s'] <= 22
    row = dict(sampler.rows[-1], timestamp_s=80.3)
    sampler.add(row, [])
    assert sampler.segment_id == 2 and sampler.analysis is None and len(sampler.rows) == 1
    sampler.add(dict(row,timestamp_s=80.4,roi_valid=False), ['multiple_faces'])
    assert sampler.segment_id == 3 and not sampler.rows and sampler.analysis is None
    sampler.add(dict(row,timestamp_s=80.5), [])
    assert sampler.start == 80.5
    sampler.add(dict(row,timestamp_s=80.71,roi_valid=False), ['no_face'])
    assert sampler.analysis is None and not sampler.rows


def test_shared_window_output_matches_offline_without_baseline():
    rows = synthetic(seconds=21, fps=15)
    result = analyze_window([r for r in rows if r['timestamp_s'] <= 20], 0, 20)
    offline = analyze(rows)[0]
    assert result == {k:v for k,v in offline.items() if k not in ('baseline_hr_bpm','baseline_status','delta_hr_bpm')}


def test_png_ihdr_checked_before_decode(monkeypatch):
    def forbidden(*_args): raise AssertionError('Decoder must not run')
    monkeypatch.setattr(cv2, 'imdecode', forbidden)
    data = b'\x89PNG\r\n\x1a\n'+struct.pack('!I',13)+b'IHDR'+struct.pack('!II',100000,100000)+b'\0'*9
    with pytest.raises(Failure) as exc: decode_png(data)
    assert exc.value.code == 'image_dimensions'


def test_stop_clears_buffers_and_new_boot_ids(api):
    request, state, _, _ = api
    sid = session(request)
    h = {'Content-Type':'image/png','X-Session-ID':sid,'X-Frame-Seq':'0','X-Capture-Time':'0'}
    assert request('/api/frame', png(), h)[0] == 200
    assert request('/api/stop', json.dumps({'session_id':sid}))[0] == 200
    assert state.session is None
    assert request('/api/stop', json.dumps({'session_id':sid}))[0] == 200
    assert request('/api/frame', png(), h)[0] == 409
    other = LiveState()
    assert state.boot_id != other.boot_id and state.token != other.token


@pytest.mark.parametrize('length', ['-1','bad','0','99999999999'])
def test_malformed_lengths(api, length):
    response = api[0]('/api/session', '{}', {'Content-Length':length})
    assert response[0] in (400,413)


def test_truncated_socket_body(api):
    import socket
    _, state, _, server = api
    with socket.create_connection(('127.0.0.1',server.server_port),timeout=5) as sock:
        host = f'127.0.0.1:{server.server_port}'
        message = (f'POST /api/session HTTP/1.1\r\nHost: {host}\r\nOrigin: http://{host}\r\n'
                   f'X-RPPG-Token: {state.token}\r\nContent-Type: application/json\r\nContent-Length: 10\r\n\r\n{{}}')
        sock.sendall(message.encode())
        sock.shutdown(socket.SHUT_WR)
        output = b''
        while True:
            chunk = sock.recv(4096)
            if not chunk: break
            output += chunk
    assert b'400 Bad Request' in output and b'truncated_body' in output


def test_receive_origin_precedes_processing():
    state, sid, clock, detector = state_session()
    def detect(*_args, **_kwargs):
        clock.value += .04
        return [(10,5,60,70)]
    detector.detectMultiScale = detect
    state.frame(sid, '0', '50', png())
    assert state.session['receive'] == 0
    clock.value = 1/15
    result = state.frame(sid, '1', str(50+1/15), png())
    assert result['server_receive_lag_s'] == pytest.approx(0, abs=1e-10)


# Real isolated snapshots exercise the same formula and import layout as the launcher.
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from rppg.live import RUNTIME_FILES, RUNTIME_VERSIONS


@pytest.fixture
def release(tmp_path):
    source = Path(__file__).resolve().parents[1]
    files = {}
    for name in RUNTIME_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
        files[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = dict(schema=1, runtime=dict(RUNTIME_VERSIONS), files=files)
    manifest['runtime_id'] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest))
    return path, manifest


def release_python(path, script):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PYTHONPATH=str(path.parent))
    return subprocess.run([sys.executable, '-B', '-c', script], cwd=path.parent, env=env,
                          capture_output=True, text=True, timeout=20)


def save_manifest(path, manifest, resign=False):
    if resign:
        identity = {key: manifest[key] for key in ('schema', 'runtime', 'files')}
        manifest['runtime_id'] = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    path.write_text(json.dumps(manifest))


def test_local_snapshot_actual_versions_and_health(release):
    path, manifest = release
    result = release_python(path, """
import http.client, json, threading
from rppg.live import LiveServer
with LiveServer(0, runtime_manifest=str(__import__('pathlib').Path('manifest.json').resolve())) as server:
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        replies = []
        for path in ['/api/health', '/api/config']:
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
            connection.request('GET', path)
            response = connection.getresponse()
            assert response.status == 200
            replies.append(json.loads(response.read()))
            connection.close()
        print(json.dumps(replies))
    finally:
        server.shutdown()
        thread.join()
""")
    assert result.returncode == 0, result.stderr
    health, config = json.loads(result.stdout)
    assert health == dict(service='rppg-live', protocol=1, boot_id=config['boot_id'],
                         execution_mode='local', runtime_id=manifest['runtime_id'], active_session=False)
    assert config['execution_mode'] == 'local' and config['runtime_id'] == manifest['runtime_id']
    assert config['active_session'] is False and config['target_fps'] == 15
    assert 'token' not in health and config['token']


@pytest.mark.parametrize('damage', ['identity', 'hash', 'missing', 'extra', 'traversal', 'absolute',
    'file_symlink', 'directory_symlink', 'manifest_symlink', 'relative', 'foreign_package',
    'schema', 'runtime_spec', 'actual_version', 'actual_module_version', 'oversize', 'duplicate'])
def test_invalid_local_runtime_fails_before_socket_bind(release, tmp_path, damage):
    path, manifest = release
    argument = str(path)
    prefix = ''
    if damage == 'identity': manifest['runtime_id'] = '0' * 64
    elif damage == 'hash': manifest['files']['rppg/live_web/live.js'] = '0' * 64
    elif damage == 'missing': (tmp_path / 'rppg/live_web/live.js').unlink()
    elif damage in ('extra', 'traversal', 'absolute'):
        manifest['files'][{'extra':'extra.py', 'traversal':'../escape', 'absolute':'/etc/passwd'}[damage]] = '0' * 64
    elif damage == 'file_symlink':
        target = tmp_path / 'rppg/live_web/live.js'
        outside = tmp_path.parent / (tmp_path.name + '-outside.js')
        target.rename(outside)
        target.symlink_to(outside)
    elif damage == 'directory_symlink':
        target = tmp_path / 'rppg/live_web'
        outside = tmp_path.parent / (tmp_path.name + '-outside-web')
        target.rename(outside)
        target.symlink_to(outside, target_is_directory=True)
    elif damage == 'manifest_symlink':
        outside = tmp_path.parent / (tmp_path.name + '-manifest.json')
        outside.write_text(json.dumps(manifest))
        path.unlink()
        path.symlink_to(outside)
    elif damage == 'relative': argument = 'manifest.json'
    elif damage == 'foreign_package':
        outside = tmp_path.parent / (tmp_path.name + '-foreign')
        outside.mkdir()
        argument = str(outside / 'manifest.json')
        Path(argument).write_text(json.dumps(manifest))
    elif damage == 'schema': manifest['schema'] = True
    elif damage == 'runtime_spec': manifest['runtime']['python'] = '0.0.0'
    elif damage == 'actual_version':
        prefix = "import rppg.live as live; live.platform.python_version = lambda: '0.0.0'; "
    elif damage == 'actual_module_version':
        prefix = "import rppg.live as live; live.np.__version__ = '0.0.0'; "
    elif damage == 'oversize': (tmp_path / 'rppg/live_web/live.js').write_bytes(b'x' * (256 * 1024 + 1))
    if damage != 'manifest_symlink':
        save_manifest(path, manifest, resign=damage in ('runtime_spec', 'hash'))
    if damage == 'duplicate':
        path.write_text(path.read_text().replace('"schema": 1', '"schema": 1, "schema": 1'))
    script = prefix + f"""
from rppg.live import LiveServer, ThreadingHTTPServer
def unexpected_bind(*args, **kwargs):
    raise AssertionError('socket binding attempted')
ThreadingHTTPServer.__init__ = unexpected_bind
try:
    LiveServer(0, runtime_manifest={argument!r})
except ValueError:
    print('rejected before bind')
else:
    raise AssertionError('invalid runtime accepted')
"""
    result = release_python(path, script)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'rejected before bind'


def test_manifest_rejects_actual_dependency_metadata(release):
    path, _ = release
    result = release_python(path, """
import rppg.live as live
live.metadata.version = lambda name: '0.0.0'
try:
    live.LiveServer(0, runtime_manifest=str(__import__('pathlib').Path('manifest.json').resolve()))
except ValueError as exc:
    assert 'installed runtime versions' in str(exc)
else:
    raise AssertionError('wrong dependency version accepted')
""")
    assert result.returncode == 0, result.stderr


def test_cli_local_runtime_failure_is_fatal(release):
    path, manifest = release
    manifest['runtime_id'] = '0' * 64
    save_manifest(path, manifest)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PYTHONPATH=str(path.parent))
    result = subprocess.run([sys.executable, '-B', '-m', 'rppg.live', '--local-runtime', str(path)],
                            cwd=path.parent, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 2 and 'runtime identity mismatch' in result.stderr


def test_health_and_config_report_session_lifecycle_without_token_in_health(api):
    request, _, clock, _ = api
    for endpoint in ['/api/health', '/api/config']:
        assert request(endpoint)[1]['active_session'] is False
    sid = session(request)
    for endpoint in ['/api/health', '/api/config']:
        payload = request(endpoint)[1]
        assert payload['active_session'] is True
        assert payload['execution_mode'] == 'remote' and payload['runtime_id'] is None
    health = request('/api/health', headers={'X-RPPG-Token':''})[1]
    assert set(health) == {'service', 'protocol', 'boot_id', 'execution_mode', 'runtime_id', 'active_session'}
    clock.value = 10
    assert request('/api/health')[1]['active_session'] is False
    sid = session(request)
    request('/api/stop', json.dumps({'session_id':sid}))
    assert request('/api/config')[1]['active_session'] is False


def test_cli_local_runtime_accepts_verified_snapshot(release):
    path, _ = release
    result = release_python(path, f"""
import runpy, sys
from http.server import ThreadingHTTPServer
original_bind = ThreadingHTTPServer.server_bind
def ephemeral_bind(self):
    self.server_address = ('127.0.0.1', 0)
    original_bind(self)
ThreadingHTTPServer.server_bind = ephemeral_bind
ThreadingHTTPServer.serve_forever = lambda self: print('verified CLI startup')
sys.argv = ['rppg.live', '--local-runtime', {str(path)!r}]
runpy.run_module('rppg.live', run_name='__main__')
""")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'verified CLI startup'
