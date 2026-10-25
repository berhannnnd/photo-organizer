"""Run reproducible cached-query kernel measurements against an explicitly chosen catalog."""

import argparse
import json
from pathlib import Path

from photo_organizer.evaluation.performance import measure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repetitions", type=int, default=10)
    args = parser.parse_args()
    report = measure(args.state, json.loads(Path(args.cases).read_text()), args.repetitions)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: report[k] for k in ("gate", "p95_seconds", "failures", "boundary")}))


if __name__ == "__main__":
    main()
