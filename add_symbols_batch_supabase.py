#!/usr/bin/env python3
"""
Insert symbols into Supabase `symbols` table, skipping any already present.
Uses SUPABASE_URL and SUPABASE_KEY from the environment (same as app.py defaults).
"""
import os
import sys

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://pggshikvapdnukpzoznk.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_BgGQTZmkECmAwRAOM6Bmig_uTafg82R")

NEW_SYMBOLS_RAW = """
RCL CCL UAL CVNA NCLH LUV BLDR PHM COIN APTV LEN HOOD DHI GM EXPE MAS DLTR WSM MPWR ADI DAL BAX NVR RL HAS COF TDG PH STT AMCR SHW SWK CRH MAR Q SYF TSLA F PPG
""".split()


def main():
    wanted = []
    seen = set()
    for s in NEW_SYMBOLS_RAW:
        u = s.strip().upper()
        if not u or u in seen:
            continue
        seen.add(u)
        wanted.append(u)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    resp = client.table("symbols").select("symbol").execute()
    if not resp.data:
        print("No rows returned from symbols table (empty or error).", file=sys.stderr)
        sys.exit(1)

    existing = {row["symbol"] for row in resp.data}
    to_add = [s for s in wanted if s not in existing]
    skipped = [s for s in wanted if s in existing]

    print(f"Requested (unique): {len(wanted)}")
    print(f"Already in Supabase: {len(skipped)} -> {', '.join(skipped) if skipped else '(none)'}")
    print(f"To insert: {len(to_add)} -> {', '.join(to_add) if to_add else '(none)'}")

    if not to_add:
        print("Nothing to insert.")
        return

    rows = [{"symbol": s} for s in to_add]
    client.table("symbols").insert(rows).execute()
    print("Insert OK.")


if __name__ == "__main__":
    main()
