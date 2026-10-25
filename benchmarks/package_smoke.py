"""Install a built wheel into a clean temporary venv and run transport/workflow tests."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
wheel = repo / 'dist' / 'photo_organizer-0.2.0a1-py3-none-any.whl'
start = time.perf_counter()
with tempfile.TemporaryDirectory(prefix='photo-organizer-install-') as tmp:
    base = Path(tmp)
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    def run(args):
        return subprocess.run([str(x) for x in args], cwd=base, env=env, check=True,
                              capture_output=True, text=True)
    run([sys.executable, '-m', 'venv', base / 'venv'])
    python = base / 'venv/bin/python'
    run([python, '-m', 'pip', 'install', str(wheel) + '[mcp]'])
    origin = run([python, '-c', 'import photo_organizer; print(photo_organizer.__file__)']).stdout.strip()
    assert str(base) in origin and str(repo) not in origin
    skill = base / 'venv/share/photo-organizer/skills/photo-organizer/SKILL.md'
    assert skill.is_file()
    result = run([python, '-m', 'unittest', 'discover', '-s', repo / 'tests', '-v'])
    report = {'wheel': wheel.name, 'isolated_install': True, 'bundled_skill': True,
              'seconds': time.perf_counter() - start, 'test_output': result.stdout + result.stderr,
              'scope': 'local clean venv, not clean OS or independent agent host acceptance'}
    output = repo / 'benchmarks/results/package-smoke.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != 'test_output'}, indent=2))
    print(result.stderr[-300:])
