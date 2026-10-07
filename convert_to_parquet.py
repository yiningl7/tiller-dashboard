import pandas as pd

for name in ["df_order_data", "df_order_line", "df_payment_data"]:
    pd.read_csv(f"data/{name}.csv").to_parquet(f"data/{name}.parquet", index=False)
    print(f"Converted {name}")
