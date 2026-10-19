"""Owned standard-library probe entry point. No shell, writes or arbitrary route."""
from dataclasses import asdict
import json
from pathlib import Path
import sys

# -I ignores ambient PYTHONPATH and user-site packages. Load this checkout only.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from admin.health import GatewayObserver


if __name__ == '__main__':
    observer = GatewayObserver(sys.argv[1], float(sys.argv[2]))
    print(json.dumps(asdict(observer._poll_once())))
