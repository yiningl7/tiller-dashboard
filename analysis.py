from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
from data import DAY_START_HOUR

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_DWELL_MIN = 240  # stays over 4 hours are treated as data errors
SERVICES = ["Lunch", "Dinner", "Other times"]


# -------------------------------------------------------------------------
# Number formatting
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


def guests_recorded(o: pd.DataFrame) -> bool:
    """False when guest numbers are just a default (e.g. a bar where every bill shows 1)."""
    g = o["m_nb_customer"]
    seated = g[g > 0]
    return len(seated) > 0 and (seated > 1).mean() >= 0.02


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
        "spend_per_cover": (seated["revenue"].sum() / covers
                            if covers and guests_recorded(o) else None),
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
# Overview: daily view, holidays, peaks, week on week
PEAK_RATIO = 1.5      # a day at 1.5x a normal same weekday counts as a peak
TYPICAL_WINDOW = 28   # "normal" = median of the same weekday within 4 weeks either side


def easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def special_days(years) -> dict:
    """French public holidays plus the dates that change how people eat and drink out."""
    out = {}
    for y in years:
        easter = easter_sunday(y)
        out.update({
            date(y, 1, 1): "New Year's Day",
            date(y, 2, 14): "Valentine's Day",
            easter + timedelta(days=1): "Easter Monday",
            date(y, 5, 1): "May Day",
            date(y, 5, 8): "Victory in Europe Day",
            easter + timedelta(days=39): "Ascension Day",
            easter + timedelta(days=50): "Whit Monday",
            date(y, 6, 21): "F\u00eate de la Musique",
            date(y, 7, 14): "Bastille Day",
            date(y, 8, 15): "Assumption Day",
            date(y, 11, 1): "All Saints' Day",
            date(y, 11, 11): "Armistice Day",
            date(y, 12, 24): "Christmas Eve",
            date(y, 12, 25): "Christmas Day",
            date(y, 12, 31): "New Year's Eve",
        })
    return out


def _typical(values: pd.Series, window: int = TYPICAL_WINDOW) -> pd.Series:
    """For each day, the median of the same weekday within `window` days either side,
    leaving the day itself out. NaN when fewer than 2 such days traded."""
    out = pd.Series(float("nan"), index=values.index)
    for wd in range(7):
        s = values[values.index.dayofweek == wd]
        if s.empty:
            continue
        days = s.index.values.astype("datetime64[D]").astype("int64")
        vals = s.values
        lo = days.searchsorted(days - window, side="left")
        hi = days.searchsorted(days + window, side="right")
        typ = []
        for i, (a, b) in enumerate(zip(lo, hi)):
            near = [vals[j] for j in range(a, b) if j != i]
            typ.append(float(pd.Series(near).median()) if len(near) >= 2 else float("nan"))
        out.loc[s.index] = typ
    return out


def daily_profile(o_store: pd.DataFrame) -> pd.DataFrame:
    """One row per trading day of a restaurant: revenue, orders, orders in the busiest hour,
    and how the day compares with a normal same weekday. Closed days have no row."""
    days = o_store.groupby("date").agg(revenue=("revenue", "sum"),
                                       orders=("id_order", "nunique"))
    days = days[days["orders"] > 0]
    peak_hour = o_store.groupby(["date", "hour"])["id_order"].nunique()
    days["busiest_hour_orders"] = peak_hour.groupby(level=0).max().reindex(days.index)
    days["typical_revenue"] = _typical(days["revenue"])
    days["typical_busiest_hour"] = _typical(days["busiest_hour_orders"].astype(float))
    days["vs_typical"] = days["revenue"] / days["typical_revenue"]
    names = special_days(sorted(set(days.index.year)))
    days["special"] = [names.get(d.date()) for d in days.index]
    return days


def revenue_trend(days: pd.DataFrame, start: date, end: date) -> tuple[pd.DataFrame, str]:
    """Revenue per trading day (weekly for ranges over 92 days). Closed days are left out
    rather than drawn as zero; a week with no trading at all is a gap."""
    d = in_period(days.rename_axis("date").reset_index(), start, end)
    if (end - start).days + 1 > 92:
        s = d.set_index("date")["revenue"]
        weekly = s.resample("W-MON", label="left", closed="left").agg(["sum", "count"])
        weekly = weekly.reindex(pd.date_range(pd.Timestamp(start) - pd.Timedelta(
            days=pd.Timestamp(start).dayofweek), end, freq="W-MON"))
        rev = weekly["sum"].where(weekly["count"] > 0)
        out = pd.DataFrame({"period": weekly.index, "revenue": rev.values,
                            "trading_days": weekly["count"].fillna(0).astype(int).values})
        return out, "week"
    out = d.rename(columns={"date": "period"})[
        ["period", "revenue", "orders", "typical_revenue", "vs_typical", "special"]]
    return out.reset_index(drop=True), "day"


def peak_days(days: pd.DataFrame, start: date, end: date, ratio: float = PEAK_RATIO) -> pd.DataFrame:
    """Holidays and unusually busy days in the period, with what they meant for staffing."""
    d = in_period(days.rename_axis("date").reset_index(), start, end)
    keep = d["special"].notna() | (d["vs_typical"] >= ratio)
    d = d[keep].copy()
    d["label"] = d["special"].fillna("Unusual peak")
    d["extra_busiest_hour"] = d["busiest_hour_orders"] / d["typical_busiest_hour"] - 1
    return d.sort_values("date").reset_index(drop=True)[
        ["date", "label", "revenue", "typical_revenue", "vs_typical", "orders",
         "busiest_hour_orders", "typical_busiest_hour", "extra_busiest_hour"]]


def week_on_week(days: pd.DataFrame, end: date) -> pd.DataFrame:
    """Each weekday of the last 7 days to `end` against the same weekday a week before."""
    end_ts = pd.Timestamp(end)
    rows = []
    for back in range(6, -1, -1):
        this_day = end_ts - pd.Timedelta(days=back)
        last_week = this_day - pd.Timedelta(days=7)
        cur = days["revenue"].get(this_day)
        prev = days["revenue"].get(last_week)
        if cur is None and prev is None:
            continue  # closed both weeks: not a trading day
        rows.append({"weekday": WEEKDAYS[this_day.dayofweek], "date": this_day,
                     "revenue": cur, "previous_date": last_week, "previous_revenue": prev,
                     "change": change(cur, prev), "special": days["special"].get(this_day)})
    return pd.DataFrame(rows, columns=["weekday", "date", "revenue", "previous_date",
                                       "previous_revenue", "change", "special"])


def weekday_over_weeks(days: pd.DataFrame, start: date, end: date, weekday: int) -> pd.DataFrame:
    """One weekday (Mon = 0) across every week of the period, with the change on the week before."""
    d = in_period(days.rename_axis("date").reset_index(), start, end)
    all_days = pd.date_range(start, end, freq="D")
    wanted = all_days[all_days.dayofweek == weekday]
    s = d.set_index("date")["revenue"].reindex(wanted)
    out = pd.DataFrame({"date": wanted, "revenue": s.values})
    out["change"] = out["revenue"] / out["revenue"].shift(1) - 1
    out["special"] = [days["special"].get(x) for x in wanted]
    return out


def trading_weekdays(days: pd.DataFrame, start: date, end: date) -> list[int]:
    d = in_period(days.rename_axis("date").reset_index(), start, end)
    return sorted(set(d["date"].dt.dayofweek))


# -------------------------------------------------------------------------
# Sales
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


def top_items(items: pd.DataFrame, by: str, n: int = 15) -> pd.DataFrame:
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
PARTY_SIZES = ["1", "2", "3", "4", "5-6", "7+"]


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
