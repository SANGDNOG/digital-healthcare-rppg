"""Loopback-only, bounded browser PNG sampling. No camera or recording access."""
import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
from importlib import metadata
import platform
import stat
import sys
import math
from pathlib import Path
import re
import secrets
import struct
import threading
import time
import uuid

import cv2
import numpy as np
from .signal import analyze_window

MAX_BODY = 2 * 1024 * 1024
DRIFT_SECONDS = 2.
WEB = Path(__file__).with_name('live_web')


RUNTIME_FILES = (
    'rppg/__init__.py', 'rppg/live.py', 'rppg/signal.py',
    'rppg/live_web/index.html', 'rppg/live_web/live.js', 'rppg/live_web/live.css',
)
RUNTIME_VERSIONS = dict(python='3.11.17', numpy='2.4.6', scipy='1.17.1',
                        opencv_python_headless='4.11.0.86')


def validate_runtime_manifest(manifest_path):
    """Verify the launcher's schema-1 immutable snapshot before binding a socket."""
    def reject(message):
        raise ValueError('Invalid local runtime: ' + message)

    def read_file(path, limit):
        if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
            reject('files must be regular files, without symlinks')
        with path.open('rb') as source:
            data = source.read(limit + 1)
        if len(data) > limit:
            reject('file exceeds size limit')
        return data

    path = Path(manifest_path)
    if not path.is_absolute() or path.name != 'manifest.json' or path != path.resolve():
        reject('manifest must be an absolute, canonical manifest.json path')
    release = path.parent
    if release != Path(__file__).resolve().parent.parent:
        reject('manifest does not belong to the running package')
    try:
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    reject('duplicate JSON key')
                result[key] = value
            return result
        manifest = json.loads(read_file(path, 1024 * 1024), object_pairs_hook=unique_object)
        if not isinstance(manifest, dict) or set(manifest) != {'schema', 'runtime', 'files', 'runtime_id'}:
            reject('manifest fields do not match schema 1')
        if type(manifest['schema']) is not int or manifest['schema'] != 1:
            reject('unsupported schema')
        if manifest['runtime'] != RUNTIME_VERSIONS:
            reject('runtime specification does not match the managed versions')
        files = manifest['files']
        if not isinstance(files, dict) or set(files) != set(RUNTIME_FILES):
            reject('exact six-file allowlist required')
        for name, digest in files.items():
            if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                reject('invalid file digest')
            target = release / name
            if target.resolve() != target:
                reject('symlink in runtime file path')
            if hashlib.sha256(read_file(target, 256 * 1024)).hexdigest() != digest:
                reject('file hash mismatch: ' + name)
        allowed = set(RUNTIME_FILES) | {'manifest.json'}
        directories = {'rppg', 'rppg/live_web'}
        for entry in release.rglob('*'):
            name = entry.relative_to(release).as_posix()
            if entry.is_symlink() or name not in allowed | directories:
                reject('unexpected release entry: ' + name)
        identity = {key: manifest[key] for key in ('schema', 'runtime', 'files')}
        runtime_id = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        if manifest['runtime_id'] != runtime_id:
            reject('runtime identity mismatch')
        import scipy
        actual = dict(python=platform.python_version(), numpy=metadata.version('numpy'),
                      scipy=metadata.version('scipy'),
                      opencv_python_headless=metadata.version('opencv-python-headless'))
        if (actual != manifest['runtime'] or np.__version__ != actual['numpy'] or
                scipy.__version__ != actual['scipy'] or
                cv2.__version__ != actual['opencv_python_headless'].rsplit('.', 1)[0]):
            reject('installed runtime versions do not match manifest')
        for name, relative in [('rppg', 'rppg/__init__.py'), ('rppg.signal', 'rppg/signal.py')]:
            module = sys.modules.get(name)
            if module is None or Path(module.__file__).resolve() != release / relative:
                reject('import path does not match release: ' + name)
        return runtime_id
    except (OSError, ValueError, TypeError, metadata.PackageNotFoundError) as exc:
        raise ValueError('Local runtime verification failed: ' + str(exc)) from exc


class Failure(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def fail(status, code, message):
    raise Failure(status, code, message)


def decode_png(data):
    if (len(data) < 33 or data[:8] != b'\x89PNG\r\n\x1a\n' or
            data[8:16] != b'\x00\x00\x00\x0dIHDR'):
        fail(400, 'invalid_png', 'A PNG with a leading IHDR chunk is required.')
    width, height = struct.unpack('!II', data[16:24])
    if not (0 < width <= 640 and 0 < height <= 480):
        fail(413, 'image_dimensions', 'PNG dimensions must be within 640 by 480.')
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape[:2] != (height, width):
        fail(400, 'invalid_png', 'PNG could not be decoded consistently with its IHDR.')
    return frame


class Sampler:
    def __init__(self, detector=None):
        self.detector = detector if detector is not None else cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        self.previous_gray = self.previous_box = None
        self.segment_id = 1
        self.clear()

    def clear(self):
        self.rows = deque(maxlen=1500)
        self.start = self.last_valid = None
        self.window_index = 0
        self.analysis = None

    def reset(self):
        if self.start is not None:
            self.segment_id += 1
        self.clear()

    def extract(self, frame, elapsed):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape
        faces = self.detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        box = list(map(int, faces[0])) if len(faces) == 1 else None
        patches = []
        if box is not None:
            x, y, w, h = box
            for rx, ry, rw, rh in [(x+.25*w, y+.12*h, .5*w, .18*h),
                                  (x+.15*w, y+.5*h, .25*w, .2*h),
                                  (x+.6*w, y+.5*h, .25*w, .2*h)]:
                x1, y1 = max(0, int(rx)), max(0, int(ry))
                x2, y2 = min(width, int(rx+rw)), min(height, int(ry+rh))
                if x2 > x1 and y2 > y1:
                    patches.append(frame[y1:y2, x1:x2].reshape(-1, 3))
        small = cv2.resize(gray, (64, 64)).astype(float)
        motion = float(np.mean(np.abs(small-self.previous_gray))/255) if self.previous_gray is not None else 0.
        if box is not None and self.previous_box is not None:
            motion = max(motion, float(np.max(np.abs(np.array(box)-self.previous_box)))/max(1, box[2]))
        self.previous_gray, self.previous_box = small, np.array(box) if box is not None else None
        rgb = np.concatenate(patches).mean(axis=0)[::-1] if patches else [None]*3
        brightness = float(np.mean(rgb)) if patches else None
        reasons = []
        if len(faces) == 0: reasons.append('no_face')
        if len(faces) > 1: reasons.append('multiple_faces')
        if len(faces) == 1 and not patches: reasons.append('invalid_roi')
        if motion > .12: reasons.append('motion')
        if brightness is not None and not 10 <= brightness <= 245: reasons.append('illumination')
        row = dict(timestamp_s=elapsed, r=rgb[0], g=rgb[1], b=rgb[2], roi_valid=bool(patches),
                   motion_metric=motion, brightness_metric=brightness)
        self.add(row, reasons)
        return dict(segment_id=self.segment_id, elapsed_s=elapsed, face_count=len(faces), face_box=box,
                    frame_width=width, frame_height=height, frame_reasons=reasons,
                    sample_count=len(self.rows), segment_elapsed_s=elapsed-self.start if self.start is not None else 0.,
                    analysis=self.analysis)

    def add(self, row, reasons):
        """Feed an extracted row; fixed endpoints do not follow HTTP arrival jitter."""
        t = row['timestamp_s']
        if 'multiple_faces' in reasons or (self.last_valid is not None and t-self.last_valid > .2+1e-8):
            self.reset()
        good = row['roi_valid'] and not reasons
        if self.start is None:
            if not good: return
            self.start = t
        if good: self.last_valid = t
        self.rows.append(row)
        while self.rows and self.rows[0]['timestamp_s'] < t-22:
            self.rows.popleft()
        while t+1e-7 >= self.start+20+self.window_index:
            end = self.start+20+self.window_index
            subset = [r for r in self.rows if end-20 <= r['timestamp_s'] <= end]
            self.analysis = analyze_window(subset, end-20, end)
            self.analysis['event_id'] = f'{self.segment_id}:{self.window_index}'
            self.window_index += 1


class LiveState:
    def __init__(self, clock=time.monotonic, sampler_factory=Sampler):
        self.clock, self.sampler_factory = clock, sampler_factory
        self.boot_id, self.token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.session = None
        self.stopped = deque(maxlen=64)

    def expire(self):
        s = self.session
        if s and (self.clock()-s['last'] >= 10 or self.clock()-s['begun'] >= 300):
            self.stopped.append(s['id'])
            self.session = None

    def start(self, client):
        try:
            if not isinstance(client, str) or str(uuid.UUID(client)) != client.lower(): raise ValueError()
        except (ValueError, AttributeError):
            fail(400, 'invalid_client_id', 'client_id must be a UUID string.')
        self.expire()
        if self.session:
            if self.session['client'] != client: fail(409, 'busy', 'Another client has an active session.')
        else:
            now = self.clock()
            self.session = dict(id=str(uuid.uuid4()), client=client, begun=now, last=now,
                                seq=-1, capture=None, origin=None, receive=None, sampler=self.sampler_factory())
        return dict(session_id=self.session['id'], boot_id=self.boot_id)

    def stop(self, sid):
        if not isinstance(sid, str) or len(sid) > 64: fail(400, 'invalid_session', 'session_id must be a bounded string.')
        self.expire()
        if self.session and sid == self.session['id']:
            self.stopped.append(sid)
            self.session = None
        elif sid not in self.stopped:
            fail(409, 'session_mismatch', 'The session is unknown; no active session was cleared.')
        return dict(stopped=True)

    def timing(self, sid, seq, capture):
        self.expire()
        s = self.session
        if not s or s['id'] != sid: fail(409, 'session_mismatch', 'Session expired, stopped, or does not match.')
        if not re.fullmatch(r'0|[1-9][0-9]{0,15}', seq or ''):
            fail(400, 'invalid_sequence', 'Frame sequence must be a nonnegative integer.')
        seq = int(seq)
        if seq > 2**53-1 or seq <= s['seq'] or (s['seq'] == -1 and seq != 0):
            fail(409, 'sequence_order', 'Sequence must start at zero and strictly increase.')
        try: capture = float(capture)
        except (ValueError, TypeError): fail(400, 'invalid_timestamp', 'Capture time must be finite seconds.')
        if not math.isfinite(capture) or not 0 <= capture <= 1e12:
            fail(400, 'invalid_timestamp', 'Capture time must be finite nonnegative seconds within bounds.')
        if s['capture'] is not None and capture-s['capture'] < 1/60-1e-9:
            fail(409, 'capture_order_or_rate', 'Capture times must strictly increase at no more than 60 Hz.')
        elapsed = capture-s['origin'] if s['origin'] is not None else 0.
        lag = self.clock()-s['receive']-elapsed if s['receive'] is not None else 0.
        if elapsed > 300 or abs(lag) > DRIFT_SECONDS:
            fail(409, 'capture_drift', 'Capture elapsed time differs from server elapsed time by over 2 seconds, or exceeds 300 seconds.')
        return seq, capture, elapsed, lag

    def frame(self, sid, seq, capture, data):
        seq, capture, elapsed, lag = self.timing(sid, seq, capture)
        received = self.clock()
        frame = decode_png(data)
        s = self.session
        result = s['sampler'].extract(frame, elapsed)
        if s['origin'] is None: s['origin'], s['receive'] = capture, received
        s.update(seq=seq, capture=capture, last=self.clock())
        return dict(boot_id=self.boot_id, session_id=sid, seq=seq, server_receive_lag_s=lag, **result)


class LiveServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, port=8766, state=None, runtime_manifest=None):
        self.runtime_id = validate_runtime_manifest(runtime_manifest) if runtime_manifest is not None else None
        self.execution_mode = 'local' if self.runtime_id is not None else 'remote'
        self.state = state if state is not None else LiveState()
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(('127.0.0.1', port), Handler)

    def service_actions(self):
        if self.state.lock.acquire(False):
            try: self.state.expire()
            finally: self.state.lock.release()

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(3)
        return sock, addr

    def process_request(self, request, client_address):
        if not self.slots.acquire(False):
            self.shutdown_request(request)
            return
        try: super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try: super().process_request_thread(request, client_address)
        finally: self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'rPPG-live'

    def log_message(self, *_):
        pass

    def reply(self, status, body, content_type='application/json'):
        data = json.dumps(body, allow_nan=False).encode() if content_type == 'application/json' else body
        self.send_response(status)
        for key, value in {'Content-Type': content_type, 'Content-Length': str(len(data)),
                           'Connection': 'close', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                           'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
                           'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY'}.items():
            self.send_header(key, value)
        self.end_headers()
        self.close_connection = True
        self.wfile.write(data)

    def send_error(self, code, message=None, explain=None):
        self.reply(code, dict(error='malformed_http', message='Malformed or unsupported HTTP request.'))

    def header(self, name):
        values = self.headers.get_all(name, [])
        if len(values) > 1: fail(400, 'duplicate_header', f'Duplicate {name} headers are not allowed.')
        return values[0] if values else None

    def security(self, post):
        port = self.server.server_port
        host = self.header('Host')
        if host not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            fail(403, 'host_rejected', 'Host must be the configured loopback address and port.')
        origin = self.header('Origin')
        if (post or origin is not None) and origin != f'http://{host}':
            fail(403, 'origin_rejected', 'Origin must exactly match this HTTP loopback host.')
        if self.header('Sec-Fetch-Site') == 'cross-site':
            fail(403, 'cross_site', 'Cross-site requests are not allowed.')
        if post:
            token = self.header('X-RPPG-Token')
            if not token or not secrets.compare_digest(token.encode('utf-8'), self.server.state.token.encode('ascii')):
                fail(403, 'token_rejected', 'A valid X-RPPG-Token capability is required.')

    def body(self, limit):
        if self.header('Transfer-Encoding') is not None:
            fail(400, 'transfer_encoding', 'Transfer-Encoding is not supported; use Content-Length.')
        length = self.header('Content-Length')
        if not length or not re.fullmatch(r'[0-9]{1,10}', length):
            fail(400, 'content_length', 'A bounded decimal Content-Length is required.')
        length = int(length)
        if not 0 < length <= limit: fail(413, 'body_size', f'Body must be between 1 and {limit} bytes.')
        data = self.rfile.read(length)
        if len(data) != length: fail(400, 'truncated_body', 'Request body ended before Content-Length.')
        return data

    def do_GET(self):
        self.handle_route(False)

    def do_POST(self):
        self.handle_route(True)

    def handle_route(self, post):
        locked = False
        try:
            self.security(post)
            state = self.server.state
            if not post:
                if self.path in ('/api/health', '/api/config'):
                    with state.lock:
                        state.expire()
                        runtime = dict(execution_mode=self.server.execution_mode,
                                       runtime_id=self.server.runtime_id, active_session=state.session is not None)
                if self.path == '/api/health':
                    result = dict(service='rppg-live', protocol=1, boot_id=state.boot_id, **runtime)
                elif self.path == '/api/config':
                    result = dict(token=state.token, boot_id=state.boot_id, window_seconds=20, target_fps=15,
                                  max_width=640, max_height=480, max_session_seconds=300, **runtime)
                elif self.path in ('/', '/index.html', '/live.js', '/live.css'):
                    path = WEB / ('index.html' if self.path == '/' else self.path[1:])
                    if not path.is_file(): fail(404, 'not_found', 'Live UI file is not installed.')
                    mime = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8'}
                    self.reply(200, path.read_bytes(), mime[path.suffix])
                    return
                else: fail(404, 'not_found', 'Route is not allowlisted.')
            else:
                if self.path not in ('/api/session', '/api/frame', '/api/stop'):
                    fail(404, 'not_found', 'Route is not allowlisted.')
                locked = state.lock.acquire(False)
                if not locked: fail(409, 'processing_busy', 'Another request is processing; do not queue frames.')
                if self.path == '/api/frame':
                    if self.header('Content-Type') != 'image/png': fail(415, 'content_type', 'Frame Content-Type must be image/png.')
                    sid, seq, capture = self.header('X-Session-ID'), self.header('X-Frame-Seq'), self.header('X-Capture-Time')
                    state.timing(sid, seq, capture)
                    result = state.frame(sid, seq, capture, self.body(MAX_BODY))
                else:
                    if self.header('Content-Type') != 'application/json': fail(415, 'content_type', 'Content-Type must be application/json.')
                    try: payload = json.loads(self.body(1024))
                    except (ValueError, UnicodeError): fail(400, 'invalid_json', 'Body must be a JSON object.')
                    if not isinstance(payload, dict): fail(400, 'invalid_json', 'Body must be a JSON object.')
                    result = state.start(payload.get('client_id')) if self.path == '/api/session' else state.stop(payload.get('session_id'))
            self.reply(200, result)
        except Failure as exc:
            self.reply(exc.status, dict(error=exc.code, message=exc.message))
        except (TimeoutError, ConnectionError):
            try: self.reply(408, dict(error='read_timeout', message='Socket read timed out or disconnected.'))
            except OSError: pass
        except Exception:
            self.reply(500, dict(error='processing_failed', message='Frame processing failed; stop and restart the session.'))
        finally:
            if locked: self.server.state.lock.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--local-runtime', help='Absolute verified release manifest.json path')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535: parser.error('port must be within 1..65535')
    try:
        server = LiveServer(args.port, runtime_manifest=args.local_runtime)
    except ValueError as exc:
        parser.error(str(exc))
    with server:
        try: server.serve_forever()
        except KeyboardInterrupt: pass


if __name__ == '__main__':
    main()
