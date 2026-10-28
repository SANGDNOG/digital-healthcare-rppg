"""Build an allowlisted Windows directory; the caller supplies official uv and public prose."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

UV_VERSION = '0.13.6'
TEMPLATES = ('start.cmd', 'start.py', 'requirements.txt')
GUIDE_LINK = 'href="http://127.0.0.1:8765/stress-pilot-20261028/index.html" target="_blank" rel="noopener"'
RESULTS_LINK = 'href="http://127.0.0.1:8765/"'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')


def bounded_file(root, relative, limit):
    path = root / relative
    if path.resolve() != path or not path.is_file():
        raise ValueError('Expected a regular file without symlinks: ' + relative)
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('File exceeds limit: ' + relative)
    return data


def standalone_index(original, guide, results):
    text = original.decode('utf-8')
    if text.count(GUIDE_LINK) != 1 or text.count(RESULTS_LINK) != 1 or text.count('</main>') != 1:
        raise ValueError('Runtime index changed; review standalone link patch')
    text = text.replace(GUIDE_LINK, 'href="#experiment-guide"')
    text = text.replace(RESULTS_LINK, 'href="#project-results"')
    sections = guide.decode('utf-8') + '\n' + results.decode('utf-8') + '\n'
    return text.replace('</main>', sections + '</main>').encode('utf-8')


def build(repo, output, uv_binary, uv_license, public_docs=()):
    repo = Path(repo).resolve()
    output = Path(output).absolute()
    templates = repo / 'packaging/windows'
    # Reuse the canonical bounded six-file exporter, without importing the backend.
    exporter = runpy.run_path(str(repo / 'scripts/export_live_runtime.py'))
    envelope = json.loads(exporter['export'](repo))
    snapshot = {name: exporter['read_file'](repo, name) for name in exporter['FILES']}
    if any(digest(data) != envelope['files'][name]['sha256'] for name, data in snapshot.items()):
        raise ValueError('Runtime sources changed during packaging; retry')
    source_hashes = {name: digest(data) for name, data in snapshot.items()}
    index = 'rppg/live_web/index.html'
    snapshot[index] = standalone_index(snapshot[index],
        bounded_file(templates, 'guide-fragment.html', 128 * 1024),
        bounded_file(templates, 'results-fragment.html', 128 * 1024))
    if len(snapshot[index]) > exporter['MAX_FILE']:
        raise ValueError('Packaged index exceeds runtime file limit')
    unsigned = dict(schema=1, runtime=envelope['runtime'],
                    files={name: digest(data) for name, data in snapshot.items()})
    manifest = dict(unsigned, runtime_id=digest(canonical(unsigned)))
    payload = {'runtime/' + name: data for name, data in snapshot.items()}
    payload['runtime/manifest.json'] = canonical(manifest)
    for name in TEMPLATES:
        payload[name] = bounded_file(templates, name, 256 * 1024)
    # Batch uses CRLF and ASCII so cmd.exe does not need an encoding change.
    payload['start.cmd'] = payload['start.cmd'].decode('ascii').replace('\r\n', '\n').replace('\n', '\r\n').encode('ascii')
    uv_binary = Path(uv_binary).absolute()
    payload['tools/uv.exe'] = bounded_file(uv_binary.parent, uv_binary.name, 100 * 1024 * 1024)
    licenses = [uv_license] if isinstance(uv_license, (str, Path)) else list(uv_license)
    if not licenses:
        raise ValueError('At least one supplied uv license is required')
    for supplied in licenses:
        supplied = Path(supplied).absolute()
        destination = 'tools/' + supplied.name
        if not supplied.name.startswith('uv-LICENSE') or destination in payload:
            raise ValueError('Provide unique uv-LICENSE* files')
        payload[destination] = bounded_file(supplied.parent, supplied.name, 1024 * 1024)
    if not payload['tools/uv.exe'].startswith(b'MZ'):
        raise ValueError('uv binary must be the supplied Windows executable')
    for name in public_docs:
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or not relative.parts or relative.parts[0] != 'docs' or '\\' in name:
            raise ValueError('Public document must be an explicit path below docs/')
        payload[relative.as_posix()] = bounded_file(repo, relative.as_posix(), 20 * 1024 * 1024)
    commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    payload['package.json'] = canonical(dict(schema=1, source_commit=commit,
        source_files=source_hashes, runtime_id=manifest['runtime_id'], uv_version=UV_VERSION,
        uv_sha256=digest(payload['tools/uv.exe']), platform='windows-x86_64',
        public_docs=sorted(public_docs)))
    payload['SHA256SUMS'] = ''.join(digest(data) + '  ' + name + '\n'
                                   for name, data in sorted(payload.items())).encode('utf-8')
    # Never merge with an old build, cache, or unreviewed files.
    output.mkdir(parents=True, exist_ok=False)
    try:
        for name, data in payload.items():
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    except BaseException:
        shutil.rmtree(output)
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--uv-binary', type=Path, required=True)
    parser.add_argument('--uv-license', type=Path, action='append', required=True, help='Supplied uv-LICENSE* file; repeat to preserve both licenses')
    parser.add_argument('--public-doc', action='append', default=[], help='Explicit reviewed repo-relative docs/ file; repeat for each file')
    args = parser.parse_args()
    result = build(args.repo_root, args.output_dir, args.uv_binary, args.uv_license, args.public_doc)
    print('Built runtime ' + result['runtime_id'])


if __name__ == '__main__':
    main()
