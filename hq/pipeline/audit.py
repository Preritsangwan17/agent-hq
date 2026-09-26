"""`make audit`: export the first 20 real eligibility/pay verdicts to data/audit/verdicts.csv for a manual check
(CONTRACT_C acceptance: ≥ 90 % correct eligibility and pay verdicts on the first 20)."""
from __future__ import annotations

import sys

from hq import settings as paths
from hq.api.routes_pipeline import audit_csv
from hq.db.conn import connect


def main(argv: list[str]) -> int:
    limit = int(argv[1]) if len(argv) > 1 else 20
    conn = connect()
    out = paths.DATA / "audit" / "verdicts.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = audit_csv(conn, limit)
    out.write_text(text)
    print(f"{max(0, text.count(chr(10)) - 1)} verdicts → {out}\nMark the last two columns y/n and count the y's.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
