# /// script
# requires-python = ">=3.10"
# dependencies = ["watchfiles>=1.0,<2"]
# ///
"""Run with `uv run dev.py` or install requirements-dev.txt and use Python."""
import shlex
import sys
from pathlib import Path

from watchfiles import run_process

ROOT = Path(__file__).resolve().parent


if __name__ == '__main__':
    command = shlex.join([sys.executable, str(ROOT / 'app.py'), *sys.argv[1:]])
    print('Watching app.py and static/. Press Ctrl+C to stop.', flush=True)
    run_process(ROOT / 'app.py', ROOT / 'static', target=command,
                target_type='command', debounce=300)
