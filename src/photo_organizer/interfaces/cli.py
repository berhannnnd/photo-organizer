"""Host-independent JSON CLI. Natural language interpretation belongs to the Skill agent."""

import argparse
import json
import sys

from photo_organizer.library.lifecycle import synchronize as scan
from photo_organizer.organizing.execution import apply
from photo_organizer.organizing.planning import plan
from photo_organizer.search.query import search
from photo_organizer.storage.catalog import connect, report
from photo_organizer.vision.indexing import index
from photo_organizer.vision.provider import Provider
from photo_organizer.vision.semantic import enrich


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default=".photo-organizer")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("scan")
    p.add_argument("root")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--verify", action="store_true")
    sub.add_parser("status")
    sub.add_parser("capabilities")
    p = sub.add_parser("call")
    p.add_argument("operation")
    p.add_argument("--args", default="{}")
    for command in ("index", "enrich"):
        p = sub.add_parser(command)
        p.add_argument("--config")
        p.add_argument("--cc-db")
        p.add_argument("--provider-id")
        p.add_argument("--app", default="claude")
        p.add_argument("--model")
        p.add_argument("--limit", type=int)
        p.add_argument("--workers", type=int, default=4)
        if command == "index":
            p.add_argument("--reindex", action="store_true")
        else:
            p.add_argument("--condition", required=True)
            p.add_argument("--result-set-id")
    p = sub.add_parser("search")
    p.add_argument("--rule", required=True)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)
    p = sub.add_parser("plan")
    p.add_argument("--spec", required=True)
    p.add_argument("--mode", choices=["album", "copy", "compress"], default="album")
    p.add_argument("--target")
    p = sub.add_parser("apply")
    p.add_argument("plan_id")
    args = parser.parse_args()
    try:
        if hasattr(args, "workers") and not 1 <= args.workers <= 16:
            raise ValueError("workers must be 1..16")
        if args.command in ("index", "enrich") and args.limit is not None and args.limit < 1:
            raise ValueError("limit must be positive")
        if args.command in ("call", "capabilities"):
            from photo_organizer.interfaces.service import dispatch

            result = dispatch(
                args.state,
                args.operation if args.command == "call" else "capabilities",
                json.loads(args.args) if args.command == "call" else {},
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "completed" else 2
        if args.command == "scan":
            result = scan(args.state, args.root, args.workers, args.verify)
        elif args.command == "status":
            with connect(args.state) as c:
                result = report(c)
        elif args.command in ("index", "enrich"):
            if args.config:
                if args.cc_db or args.provider_id or args.model:
                    raise ValueError("config cannot be mixed with CC Switch arguments")
                provider = Provider.from_config(args.config)
            else:
                if not all((args.cc_db, args.provider_id, args.model)):
                    raise ValueError("provide --config, or explicit CC Switch db/provider/model")
                provider = Provider(args.cc_db, args.provider_id, args.model, args.app)
            if args.command == "index":
                result = index(args.state, provider, args.limit, args.workers, args.reindex)
            else:
                result = enrich(
                    args.state,
                    provider,
                    args.condition,
                    args.limit,
                    args.workers,
                    args.result_set_id,
                )
        elif args.command == "search":
            with connect(args.state) as c:
                result = search(c, json.loads(args.rule), args.limit, args.offset)
        elif args.command == "plan":
            result = plan(args.state, json.loads(args.spec), args.target, args.mode)
        else:
            result = apply(args.state, args.plan_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if (
            result.get("errors")
            or result.get("failed_now")
            or (args.command == "scan" and result.get("file_errors"))
        ):
            return 2
        return 0
    except (ValueError, OSError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
