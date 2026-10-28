"""Export only the six local live-runtime files, without importing the backend."""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

RUNTIME = dict(python='3.11.17', numpy='2.4.6', scipy='1.17.1',
               opencv_python_headless='4.11.0.86')
FILES = ('rppg/__init__.py', 'rppg/live.py', 'rppg/signal.py',
         'rppg/live_web/index.html', 'rppg/live_web/live.js', 'rppg/live_web/live.css')
MAX_FILE = 256 * 1024
MAX_EXPORT = 1024 * 1024


def read_file(root, name):
    path = root / name
    if any(parent.is_symlink() for parent in path.parents if parent != root.parent):
        raise ValueError('Runtime paths must not contain symlinks')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
            raise ValueError('Runtime file is not a bounded regular file')
        data = stream.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValueError('Runtime file exceeds size limit')
    return data


def export(root):
    snapshot = {name: read_file(root, name) for name in FILES}
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in snapshot.items()}
    manifest = dict(schema=1, runtime=RUNTIME, files=hashes)
    identity = hashlib.sha256(json.dumps(manifest, sort_keys=True,
                                        separators=(',', ':')).encode()).hexdigest()
    envelope = dict(manifest, runtime_id=identity,
                    files={name: dict(sha256=hashes[name], base64=base64.b64encode(data).decode('ascii'))
                           for name, data in snapshot.items()})
    output = json.dumps(envelope, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(output) > MAX_EXPORT:
        raise ValueError('Runtime export exceeds size limit')
    # Re-read after constructing the complete output. Never mix old hashes and new bytes.
    if any(hashlib.sha256(read_file(root, name)).hexdigest() != hashes[name] for name in FILES):
        raise ValueError('Runtime source changed during export; retry after edits finish')
    return output


if __name__ == '__main__':
    try:
        sys.stdout.buffer.write(export(Path(__file__).resolve().parents[1]))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
