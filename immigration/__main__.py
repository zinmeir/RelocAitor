"""
Immigration data CLI.

    python -m immigration build                  # version routes, log changes, refresh the source registry
    python -m immigration check                  # exit 1 if records.json is out of date (CI)
    python -m immigration report                 # how much of each field is verified, sourced, unknown...
    python -m immigration review                 # pending proposals, as diffs, with blocking problems
    python -m immigration approve FILE --by NAME # the human step: accept a proposal
    python -m immigration verify ROUTE FIELD --by NAME --source URL   # sign off an existing value
    python -m immigration monitor                # flag routes whose official page changed (needs internet)
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from . import monitor, records as R, store, workflow
from .catalogue import FIELDS, STATUSES, STATUS_LABEL


def report(today: date = None) -> str:
    today = today or date.today()
    recs = store.load("records", {}).get("routes", {})
    rows = []
    for f in FIELDS:
        counts = {s: 0 for s in STATUSES}
        for r in recs.values():
            counts[R.status_on(r["fields"][f.name], f.name, today)] += 1
        rows.append((f.label, counts))
    head = f"{len(recs)} routes · statuses per field\n" + f"{'Field':44}" + "".join(f"{s[:9]:>10}" for s in STATUSES)
    body = "\n".join(f"{label:44}" + "".join(f"{c[s]:>10}" for s in STATUSES) for label, c in rows)
    return head + "\n" + body + "\n\n" + "\n".join(f"{s:>12}: {STATUS_LABEL[s]}" for s in STATUSES)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m immigration")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("build"); sub.add_parser("check"); sub.add_parser("report"); sub.add_parser("review")
    sub.add_parser("monitor")
    a = sub.add_parser("approve"); a.add_argument("file"); a.add_argument("--by", required=True)
    v = sub.add_parser("verify"); v.add_argument("route"); v.add_argument("field")
    v.add_argument("--by", required=True); v.add_argument("--source", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "build":
        out = store.build()
        print(f"{out['routes']} routes; {len(out['changes'])} changes logged")
        for c in out["changes"]:
            print(f"  {c['route']}: {c['kind']} {c.get('field') or ''} {c['previous']!r} -> {c['new']!r}")
        return 0
    if args.cmd == "check":
        ok = store.is_up_to_date()
        print("records.json is up to date" if ok else "records.json is OUT OF DATE: run python -m immigration build")
        return 0 if ok else 1
    if args.cmd == "report":
        print(report())
        return 0
    if args.cmd == "review":
        props = workflow.load_proposals()
        if not props:
            print("No pending proposals.")
        visas = store.load_visas()
        for p in props:
            res = workflow.check(p, visas)
            print(f"\n{p['_file']}  {p.get('route')}  (checked {p.get('checked')}, proposed by {p.get('proposed_by', '?')})")
            for d in res["diff"]:
                print(f"  {d['key']}: {d['previous']!r} -> {d['new']!r}")
            for prob in res["problems"]:
                print(f"  BLOCKED: {prob}")
        return 0
    if args.cmd == "approve":
        try:
            res = workflow.approve(args.file, args.by)
        except (ValueError, FileNotFoundError) as err:
            print(f"Not approved: {err}", file=sys.stderr)
            return 1
        print(f"Approved {res['route']}. Now run: python -m pipeline.visa_details && python -m immigration build")
        return 0
    if args.cmd == "verify":
        try:
            e = workflow.verify(args.route, args.field, args.by, args.source)
        except ValueError as err:
            print(f"Not verified: {err}", file=sys.stderr)
            return 1
        print(f"Verified {e['route']} {e['field']} by {e['by']}. Run: python -m immigration build")
        return 0
    if args.cmd == "monitor":
        res = monitor.check_pages(store.load("sources"), store.load("page_hashes", {}))
        store.save("page_hashes", res["hashes"])
        for e in res["events"]:
            print(f"{e['event']:12} {e['url']}  routes: {', '.join(e['routes']) or '-'}")
        print(f"{len(res['hashes'])} pages fingerprinted; {sum(e['event'] == 'changed' for e in res['events'])} changed")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
