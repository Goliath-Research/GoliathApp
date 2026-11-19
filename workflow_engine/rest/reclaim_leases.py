"""CLI: reset RUNNING node executions whose task lease expired back to READY.

Run on a timer next to goliath-gateway (``goliath-reclaim-leases``). It uses the gateway's
own connection settings (``rest.connection``) and ``wf.sp_reclaim_expired_leases``; it has
no product-specific code, so a descendant does not need to overlay anything to run it.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional


def reclaim_expired_leases(
    *,
    workflow_instance_id: Optional[int] = None,
    grace_seconds: int = 60,
    db: Any = None,
) -> list[dict[str, Any]]:
    """Call ``wf.sp_reclaim_expired_leases`` and return the reclaimed rows."""
    if db is not None:
        return list(
            db.reclaim_expired_leases(
                workflow_instance_id=workflow_instance_id, grace_seconds=grace_seconds
            )
        )
    from rest.db import open_gateway_db

    gateway_db = open_gateway_db()
    try:
        return list(
            gateway_db.reclaim_expired_leases(
                workflow_instance_id=workflow_instance_id, grace_seconds=grace_seconds
            )
        )
    finally:
        gateway_db.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reset RUNNING workflow nodes with expired or missing task leases back to READY "
            "so workers can claim them again."
        )
    )
    parser.add_argument("--instance-id", type=int, default=None,
                        help="Limit reclaim to one workflow_instance_id (default: all)")
    parser.add_argument("--grace-seconds", type=int, default=60,
                        help="Extra seconds after lease expiry before reclaim (default: 60)")
    parser.add_argument("--json", action="store_true", help="Print reclaimed rows as JSON")
    args = parser.parse_args(argv)
    if args.grace_seconds < 0:
        parser.error("--grace-seconds must be >= 0")

    rows = reclaim_expired_leases(
        workflow_instance_id=args.instance_id, grace_seconds=args.grace_seconds
    )
    if args.json:
        print(json.dumps(rows, default=str))
    elif not rows:
        print("reclaim_expired_leases: 0 nodes reclaimed")
    else:
        print(f"reclaim_expired_leases: {len(rows)} node(s) reclaimed")
        for r in rows:
            print(
                f"  ne={r.get('node_execution_id')} instance={r.get('workflow_instance_id')} "
                f"prev_worker={r.get('previous_worker_id')}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
