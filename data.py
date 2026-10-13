"""Loading and cleaning restaurant data.

Shared by the dashboard (app.py) and by convert_to_parquet.py, so bundled data,
re-converted data and CSVs uploaded by a restaurant all go through the same rules.
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"

# Columns kept from each raw export
ORDER_COLS = ["id_order", "id_store", "id_table", "date_opened", "date_closed",
              "m_nb_customer", "m_cached_payed", "m_cached_price"]
LINE_COLS = ["id_order", "dim_type", "dim_name_translated", "dim_category_translated",
             "m_quantity", "m_total_price_inc_vat"]
PAYMENT_COLS = ["id_pay", "id_order", "dim_status", "dim_type", "m_amount"]

# Minimum columns a restaurant must provide when uploading its own CSVs
REQUIRED_COLS = {
    "orders": ["id_order", "date_opened"],
    "lines": ["id_order", "dim_name_translated", "m_quantity", "m_total_price_inc_vat"],
    "payments": ["id_order", "dim_type", "m_amount"],
}
# Orders also need one of these as the amount paid
REVENUE_COLS = ["m_cached_payed", "m_cached_price"]

EXCLUDED_PAYMENT_STATUSES = {"CANCELLED", "CANCELED", "VOID", "REFUNDED", "FAILED"}
DEFAULT_EXCLUDED_ITEMS = ["DEPOSIT", "CONSIGNE", "ORDER", "DELIVERY PACKAGE"]

# A trading day runs from 05:00 to 05:00, so a 01:00 order on Saturday
# counts towards Friday night's service.
DAY_START_HOUR = 5

SINGLE_STORE_ID = "My restaurant"

CURRENCY_SYMBOLS = {"EUR": "€", "GBP": "£", "USD": "$", "AUD": "A$", "CAD": "C$",
                    "CHF": "CHF ", "JPY": "¥", "NZD": "NZ$", "SGD": "S$"}


def _lower_cols(df: pd.DataFrame) -> pd.DataFrame:
    # rename (not copy) keeps memory low: pandas only copies data when it's changed
    return df.rename(columns=lambda c: str(c).strip().lower())


def missing_columns(df: pd.DataFrame, kind: str) -> list[str]:
    """Columns an uploaded file of this kind is missing (empty list = OK)."""
    cols = set(df.columns.astype(str).str.strip().str.lower())
    missing = [c for c in REQUIRED_COLS[kind] if c not in cols]
    if kind == "orders" and not cols.intersection(REVENUE_COLS):
        missing.append(" or ".join(REVENUE_COLS))
    return missing


def trading_date(ts: pd.Series) -> pd.Series:
    return (ts - pd.Timedelta(hours=DAY_START_HOUR)).dt.normalize()


def clean_orders(orders: pd.DataFrame) -> pd.DataFrame:
    o = _lower_cols(orders)
    o["date_opened"] = pd.to_datetime(o["date_opened"])
    o["date_closed"] = pd.to_datetime(o["date_closed"]) if "date_closed" in o else pd.NaT
    o = o[o["date_opened"].notna()]

    if "id_store" not in o:
        o["id_store"] = SINGLE_STORE_ID
    o["id_store"] = o["id_store"].astype(str).astype("category")

    # One definition of revenue everywhere: the amount paid on the order, incl. VAT
    rev_col = next(c for c in REVENUE_COLS if c in o)
    o["revenue"] = pd.to_numeric(o[rev_col], errors="coerce").fillna(0.0)

    o["m_nb_customer"] = (pd.to_numeric(o["m_nb_customer"], errors="coerce").fillna(0)
                          if "m_nb_customer" in o else 0)
    if "id_table" not in o:
        o["id_table"] = pd.NA

    o["date"] = trading_date(o["date_opened"])
    o["hour"] = o["date_opened"].dt.hour.astype("int8")
    o["weekday"] = o["date"].dt.dayofweek.astype("int8")  # Monday = 0
    return o.reset_index(drop=True)


def daily_products(lines: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    """Order lines -> one row per restaurant, trading day and product."""
    p = _lower_cols(lines)
    if "dim_type" not in p:
        p["dim_type"] = "product"
    if "dim_category_translated" not in p:
        p["dim_category_translated"] = "Uncategorised"

    if "order_date" not in p:  # raw order lines: attach restaurant and date via the order
        p = p.merge(orders[["id_order", "id_store", "date"]], on="id_order", how="inner")
        p = p.rename(columns={"date": "order_date"})

    p["order_date"] = pd.to_datetime(p["order_date"]).dt.normalize()
    keys = ["order_date", "dim_type", "dim_name_translated", "dim_category_translated"]
    if "id_store" in p:
        p["id_store"] = p["id_store"].astype(str)
        keys = ["id_store"] + keys
    for c in ["m_quantity", "m_total_price_inc_vat"]:
        p[c] = pd.to_numeric(p[c], errors="coerce").fillna(0)
    for c in keys:
        if c != "order_date":
            p[c] = p[c].astype(str).astype("category")

    return (p.groupby(keys, observed=True)
             .agg(m_quantity=("m_quantity", "sum"),
                  m_total_price_inc_vat=("m_total_price_inc_vat", "sum"))
             .reset_index())


def clean_payments(payments: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    """Valid payments, tagged with the restaurant and trading day of their order."""
    pay = _lower_cols(payments)
    if "dim_status" in pay:
        status = pay["dim_status"].astype(str).str.strip().str.upper()
        pay = pay[~status.isin(EXCLUDED_PAYMENT_STATUSES)]
    pay["m_amount"] = pd.to_numeric(pay["m_amount"], errors="coerce").fillna(0)

    if not {"id_store", "date"}.issubset(pay.columns):
        pay = pay.drop(columns=[c for c in ["id_store", "date"] if c in pay])
        pay = pay.merge(orders[["id_order", "id_store", "date"]], on="id_order", how="inner")
    pay["id_store"] = pay["id_store"].astype(str).astype("category")
    pay["dim_type"] = pay["dim_type"].astype(str).astype("category")
    pay["date"] = pd.to_datetime(pay["date"])
    keep = [c for c in ["id_pay", "id_order", "id_store", "date", "dim_type", "m_amount"]
            if c in pay]
    return pay[keep].reset_index(drop=True)


def clean_stores(stores: pd.DataFrame) -> pd.DataFrame:
    """id_store, zipcode and currency symbol, whatever the export calls them."""
    s = _lower_cols(stores)

    def find(*words):
        return next((c for c in s.columns if any(w in c for w in words)), None)

    out = pd.DataFrame({"id_store": s["id_store"].astype(str)})
    zip_col, cur_col = find("zip", "postal", "postcode"), find("currency")
    out["zipcode"] = s[zip_col].astype(str).str.replace(r"\.0$", "", regex=True) if zip_col else None
    if cur_col:  # "EUR" -> "€"; values that are already symbols are kept
        cur = s[cur_col].astype(str).str.strip()
        out["currency"] = cur.str.upper().map(CURRENCY_SYMBOLS).fillna(cur)
    else:
        out["currency"] = None
    for c in ["zipcode", "currency"]:
        out[c] = out[c].where(~out[c].isin(["", "nan", "None", "<NA>"]), None)
    return out.drop_duplicates("id_store")


def prepare(orders, lines=None, payments=None, stores=None) -> dict:
    o = clean_orders(orders)
    return {
        "orders": o,
        "products": daily_products(lines, o) if lines is not None else None,
        "payments": clean_payments(payments, o) if payments is not None else None,
        "stores": clean_stores(stores) if stores is not None else None,
    }


def load_bundled() -> dict:
    def read(name):
        path = DATA_DIR / f"{name}.parquet"
        return pd.read_parquet(path) if path.exists() else None

    return prepare(read("df_order_data"), read("df_product_daily"),
                   read("df_payment_data"), read("df_store_data"))
