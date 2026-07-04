"""
Оркестратор пайплайна Radar.
Запускает: fetch-posts → filter-signals → digest-agent
Использование: python scripts/run-pipeline.py [--skip-fetch] [--skip-filter] [--skip-digest]

Для backfill конкретной даты запускайте скрипты напрямую:
  python scripts/filter-signals.py --date 2026-05-20
  python agents/digest-agent.py --date 2026-05-20
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPTS = ROOT / "scripts"
AGENTS = ROOT / "agents"

STEPS = [
    ("fetch",   SCRIPTS / "fetch-posts.py",   []),
    ("filter",  SCRIPTS / "filter-signals.py", []),
    ("digest",  AGENTS  / "digest-agent.py",  []),
]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-fetch",  action="store_true")
    parser.add_argument("--skip-filter", action="store_true")
    parser.add_argument("--skip-digest", action="store_true")
    return parser.parse_args()


def run_step(name: str, script: Path, extra_args: list[str]) -> bool:
    started = time.monotonic()
    print(f"\n{'-' * 50}")
    print(f"[{name.upper()}] {script.name}")
    print(f"{'-' * 50}")
    result = subprocess.run([sys.executable, str(script)] + extra_args, cwd=str(ROOT))
    elapsed = time.monotonic() - started
    status = "OK" if result.returncode == 0 else f"FAILED (exit {result.returncode})"
    print(f"[{name.upper()}] {status} — {elapsed:.1f}s")
    return result.returncode == 0


def main() -> None:
    args = parse_args()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"Radar pipeline — {now}")

    failed = []
    for name, script, extra_args in STEPS:
        if getattr(args, f"skip_{name}", False):
            print(f"\n[{name.upper()}] skipped")
            continue
        ok = run_step(name, script, extra_args)
        if not ok:
            failed.append(name)
            print(f"[WARN] step '{name}' failed — continuing")

    print(f"\n{'=' * 50}")
    if failed:
        print(f"Pipeline finished with errors: {', '.join(failed)}")
        sys.exit(1)
    else:
        print("Pipeline finished successfully.")


if __name__ == "__main__":
    main()
