"""Container health probe; no dependency on a shell/curl inside the API image."""
import argparse
import json
import time
import urllib.error
import urllib.request


def wait_ready(wait_seconds=0):
    deadline = time.monotonic() + wait_seconds
    while True:
        remaining = deadline - time.monotonic()
        try:
            with urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready',
                                        timeout=min(10, max(.01, remaining)) if wait_seconds else 10) as response:
                body = json.load(response)
                if body.get('status') == 'ready' and body.get('database') == 'cockroach':
                    return
        except (urllib.error.URLError, TimeoutError, ValueError):
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SystemExit('CockroachDB/OPA readiness was not reached before the timeout')
        time.sleep(min(.5, remaining))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait', type=float, default=0, help='Bounded readiness wait in seconds')
    args = parser.parse_args()
    if args.wait < 0:
        parser.error('--wait must be nonnegative')
    wait_ready(args.wait)
