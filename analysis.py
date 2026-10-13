"""Every number shown on the dashboard. Pure pandas, no Streamlit, so it can be tested."""

from datetime import date, timedelta

import pandas as pd

from data import DAY_START_HOUR

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_DWELL_MIN = 240  # stays over 4 hours are treated as data errors
SERVICES = ["Lunch", "Dinner", "Other times"]


# -------------------------------------------------------------------------
# Number formatting: one helper, one decimal place, used everywhere
# -------------------------------------------------------------------------
def fmt(val, prefix: str = "", whole: bool = False) -> str:
    """41171 -> 41.2K, 1281148 -> 1.3M, 23.456 -> 23.5, (523, whole=True) -> 523."""
    if val is None or pd.isna(val):
        return "–"
    sign = "-" if val < 0 else ""
    v = abs(float(val))
    if v >= 999_950:  # so 999,960 shows as 1.0M, not 1000.0K
        body = f"{v / 1_000_000:,.1f}M"
    elif v >= 999.95:
        body = f"{v / 1_000:.1f}K"
    elif whole:
        body = f"{v:,.0f}"
    else:
        body = f"{v:,.1f}"
    return f"{sign}{prefix}{body}"


def fmt_pct(val, signed: bool = False) -> str:
    if val is None or pd.isna(val):
        return "–"
    return f"{val:+.1%}" if signed else f"{val:.1%}"


def hour_label(h: int) -> str:
    return f"{h:02d}:00"


# -------------------------------------------------------------------------
# Periods and hours
# -------------------------------------------------------------------------
def in_period(df: pd.DataFrame, start: date, end: date, col: str = "date") -> pd.DataFrame:
    d = df[col]
    return df[(d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))]


def previous_period(start: date, end: date) -> tuple[date, date]:
    span = (end - start) + timedelta(days=1)
    return start - span, start - timedelta(days=1)


def ordered_hours(open_h: int, close_h: int) -> list[int]:
    """Hours from opening to closing, wrapping past midnight (e.g. 18 -> 1)."""
    if close_h >= open_h:
        return list(range(open_h, close_h + 1))
    return list(range(open_h, 24)) + list(range(0, close_h + 1))


def default_opening_hours(orders: pd.DataFrame, min_share: float = 0.005) -> tuple[int, int]:
    """First and last hour that each carry at least 0.5% of the restaurant's orders."""
    share = orders["hour"].value_counts(normalize=True)
    busy = share[share >= min_share].index.tolist() or share.index.tolist() or [11, 23]
    busy = sorted(busy, key=lambda h: (h - DAY_START_HOUR) % 24)
    return int(busy[0]), int(busy[-1])


def service_of(hours: pd.Series, lunch: tuple[int, int], dinner_start: int) -> pd.Series:
    """Lunch if lunch[0] <= hour < lunch[1]; dinner from dinner_start until the trading day ends."""
    lunch_mask = (hours >= lunch[0]) & (hours < lunch[1])
    dinner_mask = (hours >= dinner_start) | (hours < DAY_START_HOUR)
    out = pd.Series("Other times", index=hours.index)
    out[dinner_mask] = "Dinner"
    out[lunch_mask] = "Lunch"
    return out


# -------------------------------------------------------------------------
# KPIs
# -------------------------------------------------------------------------
def valid_table(o: pd.DataFrame) -> pd.Series:
    """Orders served at a real table (table id missing, blank or 0 = counter/takeaway)."""
    raw = o["id_table"]
    text = raw.astype(str).str.strip()
    is_zero = pd.to_numeric(raw, errors="coerce") == 0  # catches 0 and 0.0
    return raw.notna() & ~is_zero & ~text.isin(["", "nan", "None", "<NA>"])


def count_tables(o: pd.DataFrame) -> int:
    return int(o.loc[valid_table(o), "id_table"].nunique())


def dwell_minutes(o: pd.DataFrame) -> pd.Series:
    d = (o["date_closed"] - o["date_opened"]).dt.total_seconds() / 60
    return d[(d > 0) & (d <= MAX_DWELL_MIN)]


def kpis(o: pd.DataFrame, n_tables: int | None) -> dict:
    revenue = o["revenue"].sum()
    orders = o["id_order"].nunique()
    days_open = o["date"].nunique()
    seated = o[o["m_nb_customer"] > 0]
    covers = seated["m_nb_customer"].sum()
    dwell = dwell_minutes(o)
    table_orders = o.loc[valid_table(o), "id_order"].nunique()
    return {
        "revenue": revenue,
        "orders": orders,
        "avg_ticket": revenue / orders if orders else None,
        "spend_per_cover": seated["revenue"].sum() / covers if covers else None,
        "dwell": dwell.mean() if not dwell.empty else None,
        # Orders served at a table, per table, per day the restaurant traded.
        # Dividing by ALL tables (not only the ones used that day) avoids overstating it.
        "turns": table_orders / (n_tables * days_open) if n_tables and days_open else None,
        "days_open": days_open,
        "revenue_per_day": revenue / days_open if days_open else None,
        "orders_per_day": orders / days_open if days_open else None,
    }


def change(cur, prev):
    if cur is None or prev is None or not prev:
        return None
    return (cur - prev) / prev


# -------------------------------------------------------------------------
# Overview
# -------------------------------------------------------------------------
def revenue_trend(o: pd.DataFrame, start: date, end: date) -> tuple[pd.DataFrame, str]:
    """Daily revenue (weekly for ranges over 92 days); days with no orders count as 0."""
    daily = o.groupby("date")["revenue"].sum()
    daily = daily.reindex(pd.date_range(start, end, freq="D"), fill_value=0.0)
    if (end - start).days + 1 > 92:
        weekly = daily.resample("W-MON", label="left", closed="left").sum()
        return weekly.rename_axis("period").reset_index(name="revenue"), "week"
    return daily.rename_axis("period").reset_index(name="revenue"), "day"


def store_metrics(o_all: pd.DataFrame) -> pd.DataFrame:
    """Benchmark metrics for every restaurant over the same dates."""
    o = o_all.assign(
        covers=o_all["m_nb_customer"].where(o_all["m_nb_customer"] > 0, 0),
        seated_rev=o_all["revenue"].where(o_all["m_nb_customer"] > 0, 0),
        dwell=(o_all["date_closed"] - o_all["date_opened"]).dt.total_seconds() / 60,
    )
    o["dwell"] = o["dwell"].where((o["dwell"] > 0) & (o["dwell"] <= MAX_DWELL_MIN))
    g = o.groupby("id_store", observed=True).agg(
        revenue=("revenue", "sum"), orders=("id_order", "nunique"),
        days=("date", "nunique"), covers=("covers", "sum"),
        seated_rev=("seated_rev", "sum"), dwell=("dwell", "mean"))
    return pd.DataFrame({
        "orders": g["orders"],
        "avg_ticket": g["revenue"] / g["orders"],
        "spend_per_cover": (g["seated_rev"] / g["covers"]).where(g["covers"] > 0),
        "revenue_per_day": g["revenue"] / g["days"],
        "dwell": g["dwell"],
    })


def benchmark(o_all_period: pd.DataFrame, store: str, stores: pd.DataFrame | None,
              min_peers: int = 3, min_orders: int = 30):
    """Your metrics vs the median of comparable restaurants (same postcode if possible)."""
    m = store_metrics(o_all_period)
    if store not in m.index:
        return None
    others = m[(m.index != store) & (m["orders"] >= min_orders)]

    group = "other restaurants in the data"
    if stores is not None and stores["zipcode"].notna().any():
        zips = stores.set_index("id_store")["zipcode"]
        my_zip = zips.get(store)
        if isinstance(my_zip, str):
            local = others[others.index.map(zips.get) == my_zip]
            if len(local) >= min_peers:
                others, group = local, f"other restaurants in {my_zip}"
    if len(others) < min_peers:
        return None
    return {"you": m.loc[store], "peers": others.median(numeric_only=True),
            "n_peers": len(others), "group": group}


# -------------------------------------------------------------------------
# Sales
# -------------------------------------------------------------------------
def hourly_profile(o: pd.DataFrame, hours: list[int]) -> pd.DataFrame:
    """Average orders and revenue per trading day, by hour of day."""
    days = o["date"].nunique() or 1
    g = o.groupby("hour").agg(orders=("id_order", "nunique"), revenue=("revenue", "sum"))
    g = g.reindex(hours, fill_value=0)
    out = pd.DataFrame({"hour": hours, "label": [hour_label(h) for h in hours],
                        "avg_orders": g["orders"].values / days,
                        "avg_revenue": g["revenue"].values / days})
    return out


def weekday_hour(o: pd.DataFrame, hours: list[int]) -> pd.DataFrame:
    """Average orders for each weekday x hour (rows Mon..Sun, columns in opening order)."""
    days_per_weekday = o.groupby("weekday")["date"].nunique().reindex(range(7))
    counts = (o.groupby(["weekday", "hour"])["id_order"].nunique()
               .unstack(fill_value=0)
               .reindex(index=range(7), columns=hours, fill_value=0))
    avg = counts.div(days_per_weekday, axis=0)  # NaN where that weekday never traded
    avg.index = WEEKDAYS
    avg.columns = [hour_label(h) for h in hours]
    return avg


def service_split(o: pd.DataFrame, lunch: tuple[int, int], dinner_start: int) -> pd.DataFrame:
    days = o["date"].nunique() or 1
    s = o.assign(service=service_of(o["hour"], lunch, dinner_start))
    g = s.groupby("service").agg(revenue=("revenue", "sum"), orders=("id_order", "nunique"))
    g = g.reindex(SERVICES).fillna(0)
    g = g[g["orders"] > 0]
    return pd.DataFrame({
        "group": g.index,
        "revenue_per_day": g["revenue"].values / days,
        "orders_per_day": g["orders"].values / days,
        "avg_ticket": (g["revenue"] / g["orders"]).values,
        "share": (g["revenue"] / g["revenue"].sum()).values,
    })


def weekday_weekend(o: pd.DataFrame) -> pd.DataFrame:
    s = o.assign(group=o["weekday"].map(lambda d: "Weekend" if d >= 5 else "Weekdays"))
    g = s.groupby("group").agg(revenue=("revenue", "sum"), orders=("id_order", "nunique"),
                               days=("date", "nunique"))
    g = g.reindex(["Weekdays", "Weekend"]).dropna()
    return pd.DataFrame({
        "group": g.index,
        "revenue_per_day": (g["revenue"] / g["days"]).values,
        "orders_per_day": (g["orders"] / g["days"]).values,
        "avg_ticket": (g["revenue"] / g["orders"]).values,
        "days": g["days"].astype(int).values,
    })


# -------------------------------------------------------------------------
# Menu
# -------------------------------------------------------------------------
def menu_items(products: pd.DataFrame, exclude_terms: list[str]) -> pd.DataFrame:
    """Sellable products only: no discounts, deposits, delivery fees etc."""
    p = products
    if "dim_type" in p:
        p = p[p["dim_type"].astype(str).str.strip().str.lower() == "product"]
    terms = [t.strip().upper() for t in exclude_terms if t.strip()]
    if terms:
        pattern = "|".join(pd.Series(terms).str.replace(r"([\\^$.|?*+()\[\]{}])", r"\\\1",
                                                         regex=True))
        name = p["dim_name_translated"].astype(str).str.upper()
        cat = p["dim_category_translated"].astype(str).str.upper()
        p = p[~name.str.contains(pattern) & ~cat.str.contains(pattern)]
    return p


def item_totals(p: pd.DataFrame) -> pd.DataFrame:
    g = (p.groupby(["dim_name_translated", "dim_category_translated"], observed=True)
          .agg(units=("m_quantity", "sum"), revenue=("m_total_price_inc_vat", "sum"))
          .reset_index()
          .rename(columns={"dim_name_translated": "item",
                           "dim_category_translated": "category"}))
    g = g[g["units"] > 0]
    g["item"] = g["item"].astype(str)
    g["category"] = g["category"].astype(str)
    return g


def categories_by_revenue(items: pd.DataFrame) -> list[str]:
    return (items.groupby("category")["revenue"].sum()
                 .sort_values(ascending=False).index.tolist())


def top_items(items: pd.DataFrame, by: str, n: int = 5) -> pd.DataFrame:
    total = items[by].sum()
    top = items.nlargest(n, by).copy()
    top["share"] = top[by] / total if total else 0
    top["avg_price"] = top["revenue"] / top["units"]
    return top


MENU_CLASSES = ["Star", "Plowhorse", "Puzzle", "Dog"]


def menu_matrix(items: pd.DataFrame) -> tuple[pd.DataFrame, float, float]:
    """Classic menu engineering, using average selling price because item costs
    are not in the data. Popular = at least 70% of an even share of units."""
    m = items.copy()
    m["avg_price"] = m["revenue"] / m["units"]
    pop_line = 0.7 * m["units"].sum() / len(m) if len(m) else 0
    price_line = m["revenue"].sum() / m["units"].sum() if len(m) else 0
    popular = m["units"] >= pop_line
    premium = m["avg_price"] >= price_line
    m["class"] = "Dog"
    m.loc[popular & premium, "class"] = "Star"
    m.loc[popular & ~premium, "class"] = "Plowhorse"
    m.loc[~popular & premium, "class"] = "Puzzle"
    return m, pop_line, price_line


# -------------------------------------------------------------------------
# Service
# -------------------------------------------------------------------------
PARTY_SIZES = ["1", "2", "3", "4", "5–6", "7+"]


def party_sizes(o: pd.DataFrame) -> pd.DataFrame:
    seated = o[o["m_nb_customer"] > 0].copy()
    if seated.empty:
        return pd.DataFrame(columns=["party", "orders", "share", "dwell", "spend_per_cover"])
    n = seated["m_nb_customer"]
    seated["party"] = pd.cut(n, bins=[0, 1, 2, 3, 4, 6, float("inf")], labels=PARTY_SIZES)
    d = (seated["date_closed"] - seated["date_opened"]).dt.total_seconds() / 60
    seated["dwell"] = d.where((d > 0) & (d <= MAX_DWELL_MIN))
    g = seated.groupby("party", observed=False).agg(
        orders=("id_order", "nunique"), dwell=("dwell", "mean"),
        revenue=("revenue", "sum"), covers=("m_nb_customer", "sum"))
    g["share"] = g["orders"] / g["orders"].sum()
    g["spend_per_cover"] = (g["revenue"] / g["covers"]).where(g["covers"] > 0)
    return g.reset_index()[["party", "orders", "share", "dwell", "spend_per_cover"]]


# -------------------------------------------------------------------------
# Payments
# -------------------------------------------------------------------------
def payment_split(pay: pd.DataFrame, top: int = 4) -> pd.DataFrame:
    g = (pay.groupby("dim_type", observed=True)
            .agg(amount=("m_amount", "sum"), payments=("m_amount", "size"))
            .sort_values("amount", ascending=False)
            .reset_index())
    g["method"] = g["dim_type"].astype(str).str.replace("_", " ").str.title()
    if len(g) > top + 1:  # fold the long tail into "Others"
        rest = g.iloc[top:]
        g = pd.concat([g.iloc[:top], pd.DataFrame({
            "dim_type": ["OTHERS"], "method": ["Others"],
            "amount": [rest["amount"].sum()], "payments": [rest["payments"].sum()]})],
            ignore_index=True)
    g["amount_share"] = g["amount"] / g["amount"].sum() if g["amount"].sum() else 0
    g["payment_share"] = g["payments"] / g["payments"].sum() if g["payments"].sum() else 0
    g["avg_payment"] = g["amount"] / g["payments"]
    return g[["method", "amount", "payments", "amount_share", "payment_share", "avg_payment"]]
