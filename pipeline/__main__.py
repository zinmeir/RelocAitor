"""
Data pipeline CLI.

    python -m pipeline fetch     # download World Bank + WHO data for every country in data/world.csv, and extend
                                 # data/manual/ from the published tables (needs internet; --no-wiki to skip those)
    python -m pipeline coverage  # which countries have enough data to be ranked
    python -m pipeline build     # rebuild data/countries.csv, provenance.csv, SOURCES.md (offline)
    python -m pipeline currencies # rebuild data/currencies.json (rates to show money in your own currency)
    python -m pipeline check     # exit 1 if countries.csv is out of date with its sources (for CI)
    python -m pipeline report    # how the sourced data differs from the original hand-made values
"""

import sys

import pandas as pd

from . import build as b
from . import fetch as f


def main(argv=None) -> int:
    cmd = (argv or sys.argv[1:] or ["build"])[0]
    args = argv or sys.argv[1:]
    if cmd == "fetch":
        codes = list(b.load_world().index)
        print(f"Downloading World Bank and WHO data for {len(codes)} countries…")
        try:
            counts = f.fetch_all(codes)
        except OSError as err:
            print(f"Download failed: {err}", file=sys.stderr)
            return 2
        for sid, n in counts.items():
            print(f"  {sid:22} {n}/{len(codes)} countries")
        if "--no-wiki" not in args:
            from . import wiki
            print("Extending data/manual/ from the published tables…")
            for r in wiki.fetch_all():
                msg = r.get("error") or f"{r['added']} countries added ({r['parsed']} rows read)"
                print(f"  {r['source']:22} {msg}")
        cov = b.coverage()
        print(f"{int(cov['included'].sum())} of {len(cov)} countries have enough data to be ranked.")
        print("Now run: python -m pipeline build")
        return 0
    if cmd == "coverage":
        cov = b.coverage()
        out = cov[~cov["included"]].sort_values("measured")
        print(f"{int(cov['included'].sum())} of {len(cov)} countries are ranked "
              f"(need income data and {b.MIN_MEASURED} of {len(b.CORE_INDICATORS)} core indicators).")
        if len(out):
            print("Not yet ranked: " + ", ".join(f"{c} ({m})" for c, m in out["measured"].items()))
        return 0
    if cmd == "build":
        countries, prov = b.write()
        counts = prov["method"].value_counts().to_dict()
        print(f"Wrote data/countries.csv ({len(countries)} countries), data/provenance.csv, data/SOURCES.md")
        print("  values by method:", counts)
        return 0
    if cmd == "currencies":
        from . import currency
        out = currency.write()
        annual = sum(1 for r in out["rates"].values() if r["basis"] == "annual")
        print(f"Wrote data/currencies.json: {len(out['rates'])} currencies "
              f"({annual} from World Bank annual averages), {len(out['countries'])} countries")
        return 0
    if cmd == "check":
        ok = b.is_up_to_date()
        print("countries.csv is up to date" if ok else "countries.csv is OUT OF DATE: run python -m pipeline build")
        return 0 if ok else 1
    if cmd == "report":
        print(b.report())
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
