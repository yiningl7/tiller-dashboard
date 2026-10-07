import pandas as pd

def read(name, cols):
    df = pd.read_csv(f"data/{name}.csv")
    df.columns = df.columns.str.strip().str.lower()
    return df[[c for c in cols if c in df.columns]]

orders = read("df_order_data", ["id_order", "id_store", "id_table", "date_opened",
                                "date_closed", "m_nb_customer", "m_cached_payed", "m_cached_price"])
lines = read("df_order_line", ["id_order", "dim_type", "dim_name_translated",
                            "dim_category_translated", "m_quantity", "m_total_price_inc_vat"])
payments = read("df_payment_data", ["id_pay", "id_order", "dim_status", "dim_type", "m_amount"])

# Order lines: one row per day per product instead of one row per item ordered
orders["date_opened"] = pd.to_datetime(orders["date_opened"])
lines = lines.merge(orders[["id_order", "date_opened"]], on="id_order")
lines["order_date"] = lines["date_opened"].dt.normalize()
product_daily = (
    lines.groupby(["order_date", "dim_type", "dim_name_translated", "dim_category_translated"],
                observed=True)
    .agg(m_quantity=("m_quantity", "sum"), m_total_price_inc_vat=("m_total_price_inc_vat", "sum"))
    .reset_index()
)

# Store repeated text as categories (much smaller in memory)
for df in (orders, product_daily, payments):
    for c in df.columns:
        if c.startswith("dim_"):
            df[c] = df[c].astype("category")

orders.to_parquet("data/df_order_data.parquet", index=False, compression="zstd")
product_daily.to_parquet("data/df_product_daily.parquet", index=False, compression="zstd")
payments.to_parquet("data/df_payment_data.parquet", index=False, compression="zstd")
print("done")
