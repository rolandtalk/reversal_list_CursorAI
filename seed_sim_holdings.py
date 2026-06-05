"""
Seed the universal SIM holdings table in Supabase.

Uses SUPABASE_URL and SUPABASE_KEY from the environment, falling back to the
same defaults as app.py.
"""

import os

from supabase import create_client


SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://pggshikvapdnukpzoznk.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_BgGQTZmkECmAwRAOM6Bmig_uTafg82R")

SIM_HOLDINGS = [
    {"symbol": "AG", "shares": 30, "cost": 25.87, "buy_date": "Jun05"},
    {"symbol": "COIN", "shares": 148, "cost": 170.33, "buy_date": "Jun05"},
    {"symbol": "FIX", "shares": 2, "cost": 1336.50, "buy_date": "Jun05"},
    {"symbol": "FTAI", "shares": 70, "cost": 258.59, "buy_date": "Jun05"},
    {"symbol": "META", "shares": 48, "cost": 652.18, "buy_date": "Jun05"},
    {"symbol": "PINS", "shares": 230, "cost": 17.69, "buy_date": "Jun05"},
    {"symbol": "SHOP", "shares": 50, "cost": 128.02, "buy_date": "Jun05"},
    {"symbol": "SNAP", "shares": 100, "cost": 5.19, "buy_date": "Jun05"},
]


def main():
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    desired_symbols = {row["symbol"] for row in SIM_HOLDINGS}

    existing = client.table("sim_positions").select("symbol").execute().data or []
    for row in existing:
        symbol = row.get("symbol")
        if symbol and symbol not in desired_symbols:
            client.table("sim_positions").delete().eq("symbol", symbol).execute()

    for row in SIM_HOLDINGS:
        client.table("sim_positions").upsert(row).execute()

    print(f"Seeded {len(SIM_HOLDINGS)} SIM holdings.")


if __name__ == "__main__":
    main()
