"""Score a frozen full-scope annotation artifact; no model calls or source changes."""

import argparse
import json
from pathlib import Path

from photo_organizer.evaluation.quality import score


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = score(
        json.loads(Path(args.truth).read_text()), json.loads(Path(args.predictions).read_text())
    )
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {k: report[k] for k in ("gate", "protocol_ready", "independent_truth", "overall")},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
