"""Turn the raw Tiller CSVs in data/ into the small Parquet files the dashboard reads.

Uses the same cleaning rules as the app (see data.py). Order lines are reduced to one
row per restaurant, trading day and product; payments are tagged with their
restaurant and trading day so the dashboard can filter them.
"""

import pandas as pd

from data import DATA_DIR, LINE_COLS, ORDER_COLS, PAYMENT_COLS, prepare


def read(name, cols=None):
    path = DATA_DIR / f"{name}.csv"
    if not path.exists():
        print(f"skipped {path.name} (not found)")
        return None
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip().str.lower()
    return df[[c for c in cols if c in df.columns]] if cols else df


d = prepare(read("df_order_data", ORDER_COLS), read("df_order_line", LINE_COLS),
            read("df_payment_data", PAYMENT_COLS), read("df_store_data"))

orders = d["orders"][[c for c in ORDER_COLS if c in d["orders"].columns]]
orders.to_parquet(DATA_DIR / "df_order_data.parquet", index=False, compression="zstd")
for key, name in [("products", "df_product_daily"), ("payments", "df_payment_data"),
                  ("stores", "df_store_data")]:
    if d[key] is not None:
        d[key].to_parquet(DATA_DIR / f"{name}.parquet", index=False, compression="zstd")
print("done")
