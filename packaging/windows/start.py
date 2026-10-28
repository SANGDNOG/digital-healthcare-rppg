"""Start the verified packaged loopback server. Camera access stays in the browser."""
import argparse
import os
from pathlib import Path
import sys
import webbrowser

sys.dont_write_bytecode = True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate runtime and exit without binding or opening a browser')
    args = parser.parse_args(argv)
    runtime = Path(__file__).resolve().parent / 'runtime'
    sys.path.insert(0, str(runtime))
    from rppg.live import LiveServer, validate_runtime_manifest

    manifest = runtime / 'manifest.json'
    if args.check:
        identity = validate_runtime_manifest(manifest)
        print('Runtime verified: ' + identity)
        return 0
    with LiveServer(port=0, runtime_manifest=manifest) as server:
        url = 'http://127.0.0.1:' + str(server.server_port) + '/'
        print('Open ' + url + ' in your browser. Press Ctrl+C here to stop.', flush=True)
        if os.environ.get('RPPG_NO_BROWSER') != '1':
            try:
                webbrowser.open(url)
            except webbrowser.Error as error:
                print('Open the URL above manually: ' + str(error), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
