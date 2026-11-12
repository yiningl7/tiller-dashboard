import io
import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analysis as an
from analysis import fmt, fmt_pct
from data import (DEFAULT_EXCLUDED_ITEMS, REQUIRED_COLS, REVENUE_COLS, SINGLE_STORE_ID,
                data_version, load_bundled, missing_columns, prepare)

st.set_page_config(page_title="Restaurant Insights", page_icon="🍽️", layout="wide")

# Colours: orange = money, blue = counts, used the same way in every chart
MONEY = "#eb6834"
MONEY_LIGHT = "#f4b393"  # ordinary days, so holidays and peaks stand out
COUNT = "#2a78d6"
SEQUENTIAL = ["#eef5fd", "#b7d3f6", "#6da7ec", "#2a78d6", "#1c5cab", "#0d366b"]
CLASS_COLORS = {"Star": "#2a78d6", "Plowhorse": "#eb6834", "Puzzle": "#1baf7a", "Dog": "#a3a19b"}
FONT = "Inter, sans-serif"
CHART_CONFIG = {"displayModeBar": False}


# -------------------------------------------------------------------------
# Chart helpers
def style(fig, title, height=320, **layout):
    settings = dict(
        title=dict(text=title, font=dict(size=15)),
        height=height,
        margin=dict(l=0, r=16, t=44, b=0),
        font=dict(family=FONT),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(font=dict(family=FONT)),
        showlegend=False,
    )
    fig.update_layout(**{**settings, **layout})
    return fig


def show(fig, key=None):
    st.plotly_chart(fig, width="stretch", config=CHART_CONFIG, key=key)


def hbar(names, values, labels, title, color, hover, height=300):
    """Horizontal bars, largest on top, with value labels and a hover tooltip."""
    names, values, labels, hover = (list(x)[::-1] for x in (names, values, labels, hover))
    fig = go.Figure(go.Bar(
        x=values, y=names, orientation="h", marker_color=color,
        text=labels, textposition="outside", cliponaxis=False,
        customdata=hover, hovertemplate="%{customdata}<extra></extra>",
    ))
    top = max(values) if len(values) and max(values) > 0 else 1
    return style(fig, title, height,
                xaxis=dict(visible=False, range=[0, top * 1.5]),
                yaxis=dict(title=None, automargin=True))


def bar_height(n):
    """Room for n horizontal bars plus the title."""
    return max(300, 26 * n + 70)


def axis_ticks(max_value, prefix=""):
    """About 4 round tick values, labelled with the same formatter as the rest of the page."""
    if not max_value or max_value <= 0 or pd.isna(max_value):
        return {}
    raw = max_value / 4
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    vals = [i * step for i in range(int(max_value // step) + 2)]
    return dict(tickvals=vals, ticktext=[fmt(v, prefix, whole=True) for v in vals])


def download(df, name, label="Download data (CSV)"):
    st.download_button(label, df.to_csv(index=False).encode("utf-8"),
                    file_name=f"{name}.csv", mime="text/csv",
                    icon=":material/download:", on_click="ignore", key=f"dl_{name}")


# -------------------------------------------------------------------------
# Data
@st.cache_resource(show_spinner="Loading data…", max_entries=1)
def bundled_data(version):
    """Loaded once and shared; reloaded automatically when the data files change."""
    return load_bundled()


@st.cache_data(show_spinner=False, max_entries=64)
def store_days(store, data_key, _orders):
    """One row per trading day for a restaurant (cached per restaurant and data set)."""
    return an.daily_profile(_orders[_orders["id_store"] == store])


@st.cache_data(show_spinner="Reading your files…", max_entries=2)
def uploaded_data(orders_b, lines_b, pay_b):
    read = lambda b: pd.read_csv(io.BytesIO(b)) if b else None  # noqa: E731
    return prepare(read(orders_b), read(lines_b), read(pay_b))


def upload_panel():
    """Lets a restaurant try the dashboard on its own tiller export."""
    with st.sidebar.expander("Use your own data"):
        st.caption("Upload CSV exports from your tiller. Orders are required; "
                "order lines and payments unlock the Menu and Payments tabs.")
        files = {
            "orders": st.file_uploader("Orders", type="csv", key="up_orders"),
            "lines": st.file_uploader("Order lines", type="csv", key="up_lines"),
            "payments": st.file_uploader("Payments", type="csv", key="up_payments"),
        }
        st.markdown(
            "**Columns needed**  \n"
            f"Orders: `{'`, `'.join(REQUIRED_COLS['orders'])}`, and "
            f"`{'` or `'.join(REVENUE_COLS)}`. Optional: `id_store`, `id_table`, "
            "`date_closed`, `m_nb_customer`.  \n"
            f"Order lines: `{'`, `'.join(REQUIRED_COLS['lines'])}`.  \n"
            f"Payments: `{'`, `'.join(REQUIRED_COLS['payments'])}`.")

    if files["orders"] is None:
        return None, "Demo data: Paris restaurants using Tiller by SumUp"

    raw = {k: (f.getvalue() if f is not None else None) for k, f in files.items()}
    problems = []
    for kind, b in raw.items():
        if b:
            header = pd.read_csv(io.BytesIO(b), nrows=0)
            if miss := missing_columns(header, kind):
                problems.append(f"**{kind.title()}** is missing: {', '.join(miss)}")
    if problems:
        st.sidebar.error("Couldn't use your files, so the demo data is shown.  \n"
                        + "  \n".join(problems))
        return None, "Demo data: Paris restaurants using Tiller by SumUp"
    try:
        return uploaded_data(raw["orders"], raw["lines"], raw["payments"]), "Your uploaded files"
    except Exception as e:  # malformed dates, wrong separators…
        st.sidebar.error(f"Couldn't read your files ({e}), so the demo data is shown.")
        return None, "Demo data: Paris restaurants using Tiller by SumUp"


data, source_label = upload_panel()
if data is None:
    data = bundled_data(data_version())

orders_all = data["orders"]
products_all = data["products"]
payments_all = data["payments"]
stores = data["stores"]

# -------------------------------------------------------------------------
# Sidebar: restaurant, dates, settings
store_ids = orders_all["id_store"].value_counts().index.astype(str).tolist()
zips = stores.set_index("id_store")["zipcode"].to_dict() if stores is not None else {}
currencies = stores.set_index("id_store")["currency"].to_dict() if stores is not None else {}


def store_label(s):
    if s == SINGLE_STORE_ID:
        return s
    z = zips.get(s)
    return f"Restaurant {s}" + (f" · {z}" if isinstance(z, str) else "")


store = st.sidebar.selectbox("Restaurant", store_ids, format_func=store_label,
                            help="In a live product each owner would log in and see "
                                "only their own restaurant.")
o_store = orders_all[orders_all["id_store"] == store]

first_day = o_store["date"].min().date()
last_day = o_store["date"].max().date()
default_start = max(first_day, last_day - pd.Timedelta(days=27).to_pytimedelta())

dates = st.sidebar.date_input("Dates", value=(default_start, last_day),
                            min_value=first_day, max_value=last_day,
                            key=f"dates_{store}", format="DD/MM/YYYY")

tables_seen = an.count_tables(o_store)
with st.sidebar.expander("Restaurant settings"):
    n_tables = st.number_input(
        "Number of tables", min_value=1, step=1,
        value=max(tables_seen, 1), key=f"tables_{store}",
        help="Used for table turnover.")
    open_default, close_default = an.default_opening_hours(o_store)
    hour_opts = list(range(24))
    c_open, c_close = st.columns(2)
    open_h = c_open.selectbox("Opens", hour_opts, index=open_default,
                            format_func=an.hour_label, key=f"open_{store}")
    close_h = c_close.selectbox("Last orders", hour_opts, index=close_default,
                                format_func=an.hour_label, key=f"close_{store}")
    lunch = st.slider("Lunch service", 5, 18, (11, 15), format="%d:00", key="lunch",
                    help="Orders opened from the first hour up to (not including) the last.")
    dinner_start = st.selectbox("Dinner starts", list(range(15, 24)), index=3,
                                format_func=an.hour_label, key="dinner")
    exclude_text = st.text_area(
        "Not menu items", ", ".join(DEFAULT_EXCLUDED_ITEMS), key="exclude",
        help="Lines whose name or category contains one of (deposits, delivery fees…) are left out of the Menu tab.")
    store_currency = currencies.get(store)
    currency = st.text_input("Currency symbol",
                            store_currency if isinstance(store_currency, str) else "€",
                            key=f"cur_{store}", max_chars=4)

exclude_terms = [t for t in exclude_text.split(",") if t.strip()]
if not tables_seen:  # no table numbers in the data
    n_tables = None
hours = an.ordered_hours(open_h, close_h)
money = lambda v: fmt(v, currency)  # noqa: E731
data_key = (source_label, len(orders_all), round(float(orders_all["revenue"].sum()), 2))

# -------------------------------------------------------------------------
# Header and period checks
st.title("Restaurant Insights")

if not (isinstance(dates, tuple) and len(dates) == 2):
    st.info("Select an end date to see the figures.")
    st.stop()
start, end = dates
st.caption(f"{store_label(store)} · {start:%d %b %Y} - {end:%d %b %Y} "
        f"({(end - start).days + 1} days)")

o = an.in_period(o_store, start, end)
if o.empty:
    st.warning("No orders in this period. Select another date range.")
    st.stop()

days = store_days(store, data_key, orders_all)
day_name = lambda d: f"{d:%a %d %b %Y}"  # noqa: E731
name_of = lambda x: x if isinstance(x, str) else ""  # noqa: E731  holiday name or blank

prev_start, prev_end = an.previous_period(start, end)
has_history = prev_start >= first_day
cur = an.kpis(o, n_tables)
prev = an.kpis(an.in_period(o_store, prev_start, prev_end), n_tables) if has_history else None

tab_overview, tab_sales, tab_menu, tab_service, tab_payments = st.tabs(
    ["Overview", "Sales", "Menu", "Service", "Payments"])

# -------------------------------------------------------------------------
# Overview
with tab_overview:
    def delta(key):
        if prev is None:
            return None
        c = an.change(cur[key], prev[key])
        return None if c is None else f"{fmt_pct(c, signed=True)} vs previous period"

    def metric(col, label, value, key, help, **kw):
        col.metric(label, value, delta(key), help=help, border=True, **kw)

    st.markdown("##### Sales")
    c1, c2, c3 = st.columns(3)
    metric(c1, "Revenue", money(cur["revenue"]), "revenue",
        f"Amount paid on orders, incl. VAT. Exact: {currency}{cur['revenue']:,.2f}")
    metric(c2, "Orders", fmt(cur["orders"], whole=True), "orders",
        f"Exact: {cur['orders']:,}")
    metric(c3, "Average ticket", money(cur["avg_ticket"]), "avg_ticket",
        "Average revenue per order")

    st.markdown("##### Service")
    c4, c5, c6 = st.columns(3)
    metric(c4, "Spend per guest", money(cur["spend_per_cover"]), "spend_per_cover",
        "Revenue per guest, on orders where the number of guests was recorded"
        if an.guests_recorded(o) else
        "This restaurant doesn't record how many guests are on each bill.")
    metric(c5, "Average dwell time",
        f"{fmt(cur['dwell'])} min" if cur["dwell"] is not None else "-", "dwell",
        "Time from table opened to closed.",
        delta_color="off")
    metric(c6, "Table turnover",
        f"{fmt(cur['turns'])} turns/day" if cur["turns"] is not None else "-", "turns",
        f"Table orders per table per trading day, across all {n_tables} tables "
        "(set the table count in Restaurant settings)." if n_tables else
        "Table numbers aren't recorded in this data.")
    if not has_history:
        st.caption("No change shown: there isn't a full previous period of the same length before these dates.")

    trend, grain = an.revenue_trend(days, start, end)
    if grain == "day":
        special = trend["special"].notna() | (trend["vs_typical"] >= an.PEAK_RATIO)
        # Label the biggest highlighted days only, so labels don't collide
        labelled = set(trend[special].nlargest(4, "revenue").index)
        vs_text = [f"{v:.1f}x a normal {d:%A}" if pd.notna(v) else "no normal day to compare"
                   for v, d in zip(trend["vs_typical"], trend["period"])]
        fig = go.Figure(go.Bar(
            x=trend["period"], y=trend["revenue"],
            marker_color=[MONEY if sp else MONEY_LIGHT for sp in special],
            text=[(name_of(sp_name) or (f"{v:.1f}x" if pd.notna(v) else "")) if i in labelled
                  else "" for i, (sp_name, v) in enumerate(zip(trend["special"],
                                                              trend["vs_typical"]))],
            textposition="outside", cliponaxis=False, textfont=dict(size=11),
            customdata=[[day_name(d), money(r), vt, name_of(sp_name)] for d, r, vt, sp_name in
                        zip(trend["period"], trend["revenue"], vs_text, trend["special"])],
            hovertemplate="%{customdata[0]}<br>%{customdata[1]} · %{customdata[2]}"
                          "<br>%{customdata[3]}<extra></extra>",
        ))
        avg = trend["revenue"].mean()
        fig.add_hline(y=avg, line=dict(color="gray", width=1, dash="dot"),
                      annotation_text=f"average {money(avg)}", annotation_position="top left",
                      annotation_font=dict(size=11, color="gray"))
        top = trend["revenue"].max()
        show(style(fig, "Revenue per trading day", 360, bargap=0.2,
                   xaxis=dict(title=None, showgrid=False),
                   yaxis=dict(title=None, gridcolor="rgba(128,128,128,0.15)",
                              range=[0, top * 1.18], **axis_ticks(top, currency))), key="trend")
        closed = (end - start).days + 1 - len(trend)
        st.caption(
            (f"Closed days are left out ({closed} in this period). " if closed else "")
            + "Dark bars are holidays and peak days, at 1.5x or more a normal same weekday. "
              "A normal day is the middle value of that weekday over the 4 weeks either side.")
    else:
        fig = go.Figure(go.Scatter(
            x=trend["period"], y=trend["revenue"], mode="lines",
            line=dict(color=MONEY, width=2), connectgaps=False,
            customdata=[[money(r), int(n)] for r, n in zip(trend["revenue"], trend["trading_days"])],
            hovertemplate="Week of %{x|%d %b %Y}<br>%{customdata[0]} · "
                          "%{customdata[1]} trading days<extra></extra>",
        ))
        show(style(fig, "Weekly revenue", 340,
                   xaxis=dict(title=None, showgrid=False),
                   yaxis=dict(title=None, gridcolor="rgba(128,128,128,0.15)", rangemode="tozero",
                              **axis_ticks(trend["revenue"].max(), currency)),
                   hovermode="x"), key="trend")
        st.caption("Weeks when the restaurant didn't trade at all are shown as gaps.")
    download(trend.rename(columns={"period": grain}), "revenue_trend")

    st.markdown("##### Week on week")
    wow = an.week_on_week(days, end)
    if wow["revenue"].notna().sum() == 0:
        st.caption("No trading in the last 7 days of this period.")
    else:
        st.caption(f"Each day of the last 7 days to {end:%a %d %b} against the same day "
                   "the week before.")
        cols = st.columns(len(wow))
        for col, r in zip(cols, wow.itertuples()):
            col.metric(
                f"{r.date:%a %d %b}",
                money(r.revenue) if pd.notna(r.revenue) else "Closed",
                (f"{fmt_pct(r.change, signed=True)} vs {r.previous_date:%d %b}"
                 if r.change is not None and pd.notna(r.change) else None),
                help=(f"{name_of(r.special)}. " if name_of(r.special) else "")
                     + (f"{r.previous_date:%a %d %b}: {money(r.previous_revenue)}"
                        if pd.notna(r.previous_revenue) else
                        f"Closed on {r.previous_date:%a %d %b}"),
                border=True)

        open_days = an.trading_weekdays(days, start, end)
        in_range = an.in_period(days.rename_axis("date").reset_index(), start, end)
        avg_by_wd = in_range.groupby(in_range["date"].dt.dayofweek)["revenue"].mean()
        busiest = int(avg_by_wd.idxmax()) if len(avg_by_wd) else open_days[0]
        picked = st.segmented_control(
            "Weekday", [an.WEEKDAYS[w] for w in open_days], default=an.WEEKDAYS[busiest],
            required=True, key=f"wow_day_{store}")
        wd = an.WEEKDAYS.index(picked)
        series = an.weekday_over_weeks(days, start, end, wd)
        fig = go.Figure(go.Bar(
            x=[f"{d:%d %b}" for d in series["date"]], y=series["revenue"],
            marker_color=[MONEY if name_of(sp) else MONEY_LIGHT for sp in series["special"]],
            text=[fmt_pct(c, signed=True) if pd.notna(c) else "" for c in series["change"]],
            textposition="outside", cliponaxis=False,
            customdata=[[day_name(d), money(r) if pd.notna(r) else "Closed", name_of(sp)]
                        for d, r, sp in zip(series["date"], series["revenue"], series["special"])],
            hovertemplate="%{customdata[0]}<br>%{customdata[1]}<br>%{customdata[2]}"
                          "<extra></extra>",
        ))
        top = series["revenue"].max()
        show(style(fig, f"Every {an.WEEKDAYS[wd]} in this period, with the change on the week before",
                   320, bargap=0.35,
                   xaxis=dict(title=None, type="category"),
                   yaxis=dict(title=None, gridcolor="rgba(128,128,128,0.15)",
                              range=[0, (top if pd.notna(top) else 1) * 1.2],
                              **axis_ticks(top, currency))), key="wow_chart")
        download(series, f"week_on_week_{an.WEEKDAYS[wd].lower()}")

# -------------------------------------------------------------------------
# Sales
with tab_sales:
    st.subheader("Busiest hours")
    measure = st.segmented_control("Show", ["Orders", "Revenue"], default="Orders",
                                required=True, key="hourly_measure",
                                label_visibility="collapsed")
    hourly = an.hourly_profile(o, hours)
    is_rev = measure == "Revenue"
    col = "avg_revenue" if is_rev else "avg_orders"
    fig = go.Figure(go.Bar(
        x=hourly["label"], y=hourly[col], marker_color=MONEY if is_rev else COUNT,
        customdata=[money(v) if is_rev else f"{fmt(v)} orders" for v in hourly[col]],
        hovertemplate="%{x}<br>%{customdata} on an average day<extra></extra>",
    ))
    show(style(fig, f"Average {'revenue' if is_rev else 'orders'} per day, by hour opened",
            340, bargap=0.25,
            xaxis=dict(title=None, type="category"),
            yaxis=dict(title=None, gridcolor="rgba(128,128,128,0.15)",
                          **(axis_ticks(hourly[col].max(), currency) if is_rev else {}))),
        key="hourly")
    download(hourly.drop(columns="label"), "hourly_average")

    st.subheader("Peak days and staffing")
    peaks = an.peak_days(days, start, end)
    if peaks.empty:
        st.caption("No holidays or unusually busy days in this period.")
    else:
        busy = peaks[peaks["vs_typical"] >= an.PEAK_RATIO]
        if not busy.empty and busy["extra_busiest_hour"].notna().any():
            extra = busy["extra_busiest_hour"].median()
            st.markdown(
                f"**{len(busy)} day{'s' if len(busy) > 1 else ''} in this period ran at "
                f"{an.PEAK_RATIO:g}x a normal day or more.** At their busiest hour they "
                f"typically had {fmt_pct(extra)} more orders than normal: plan extra staff "
                "for that hour, not just more for the whole day.")
        table = pd.DataFrame({
            "Date": [day_name(d) for d in peaks["date"]],
            "What": peaks["label"],
            "Revenue": peaks["revenue"],
            "vs a normal day": peaks["vs_typical"],
            "Busiest hour (orders)": peaks["busiest_hour_orders"],
            "Normal busiest hour": peaks["typical_busiest_hour"],
            "Extra at busiest hour": peaks["extra_busiest_hour"] * 100,
        })
        st.dataframe(table, hide_index=True, width="stretch", column_config={
            "Revenue": st.column_config.NumberColumn(format=f"{currency}%.0f"),
            "vs a normal day": st.column_config.NumberColumn(format="%.1fx"),
            "Busiest hour (orders)": st.column_config.NumberColumn(format="%.0f"),
            "Normal busiest hour": st.column_config.NumberColumn(format="%.0f"),
            "Extra at busiest hour": st.column_config.NumberColumn(format="%+.0f%%"),
        })
        st.caption("Holidays are listed even when they were quiet, so you can see which ones "
                   "are worth staffing up for. A normal day is the middle value of the same "
                   "weekday over the 4 weeks either side. Closed days don't appear.")
        download(peaks, "peak_days")

    st.subheader("Lunch vs dinner, weekdays vs weekends")
    split = an.service_split(o, lunch, dinner_start)
    week = an.weekday_weekend(o)
    left, right = st.columns(2)
    with left:
        show(hbar(split["group"], split["revenue_per_day"],
                [f"{money(v)} · {fmt_pct(s)}" for v, s in
                zip(split["revenue_per_day"], split["share"])],
                "Average revenue per day, by service", MONEY,
                [f"{g}: {fmt(n)} orders a day, average ticket {money(t)}" for g, n, t in
                zip(split["group"], split["orders_per_day"], split["avg_ticket"])],
                height=240), key="service")
        st.caption(f"Lunch {an.hour_label(lunch[0])}-{an.hour_label(lunch[1])}, dinner from "
                f"{an.hour_label(dinner_start)}. Change these in Restaurant settings.")
    with right:
        show(hbar(week["group"], week["revenue_per_day"],
                [money(v) for v in week["revenue_per_day"]],
                "Average revenue per trading day", MONEY,
                [f"{g}: {fmt(n)} orders a day, average ticket {money(t)} "
                f"({d} trading days)" for g, n, t, d in
                zip(week["group"], week["orders_per_day"], week["avg_ticket"], week["days"])],
                height=240), key="weekpart")
    download(pd.concat([split.assign(split_by="service"), week.assign(split_by="day type")]),
            "service_and_weekday_split")

# -------------------------------------------------------------------------
# Menu
with tab_menu:
    if products_all is None:
        st.info("Upload order lines to see menu performance.")
    else:
        p = products_all
        if "id_store" in p:
            p = p[p["id_store"] == store]
        else:
            st.warning("This product file isn't split by restaurant, so the Menu tab shows "
                    "all restaurants together. Re-run convert_to_parquet.py to fix this.")
        items_all = an.item_totals(an.menu_items(an.in_period(p, start, end, "order_date"),
                                                exclude_terms))
        if items_all.empty:
            st.info("No menu items sold in this period.")
        else:
            cats = an.categories_by_revenue(items_all)
            category = st.selectbox(
                "Category", ["All categories"] + cats, key=f"cat_{store}",
                help="Drinks often outsell food on units. Pick a food category to see its "
                    "best sellers.")
            items = items_all if category == "All categories" else \
                items_all[items_all["category"] == category]

            st.subheader(f"Top {min(15, len(items))} items")
            by_units = an.top_items(items, "units")
            by_rev = an.top_items(items, "revenue")
            hover = lambda t: [  # noqa: E731
                f"{i}<br>{c}<br>{fmt(u, whole=True)} sold · {money(r)} · "
                f"average price {money(a)}"
                for i, c, u, r, a in zip(t["item"], t["category"], t["units"],
                                        t["revenue"], t["avg_price"])]
            left, right = st.columns(2)
            with left:
                show(hbar(by_units["item"], by_units["units"],
                        [f"{fmt(u, whole=True)} · {fmt_pct(s)}" for u, s in
                        zip(by_units["units"], by_units["share"])],
                        "By units sold", COUNT, hover(by_units),
                        height=bar_height(len(by_units))), key="top_units")
            with right:
                show(hbar(by_rev["item"], by_rev["revenue"],
                        [f"{money(r)} · {fmt_pct(s)}" for r, s in
                        zip(by_rev["revenue"], by_rev["share"])],
                        "By revenue", MONEY, hover(by_rev),
                        height=bar_height(len(by_rev))), key="top_revenue")
            st.caption("Each chart is ranked on its own. Percentages are shares of "
                    f"{'all items' if category == 'All categories' else category} sold. "
                    "Item revenue comes from order lines incl. VAT)")
            download(pd.concat([by_units.assign(ranked_by="units"),
                                by_rev.assign(ranked_by="revenue")]), "top_items")

            with st.expander(f"All {len(items)} items"):
                full = items.sort_values("revenue", ascending=False).reset_index(drop=True)
                st.dataframe(pd.DataFrame({
                    "Rank": range(1, len(full) + 1),
                    "Item": full["item"], "Category": full["category"],
                    "Units sold": full["units"], "Revenue": full["revenue"],
                    "Average price": full["revenue"] / full["units"],
                    "Share of revenue": full["revenue"] / full["revenue"].sum() * 100,
                }), hide_index=True, width="stretch", height=420, column_config={
                    "Units sold": st.column_config.NumberColumn(format="%.0f"),
                    "Revenue": st.column_config.NumberColumn(format=f"{currency}%.0f"),
                    "Average price": st.column_config.NumberColumn(format=f"{currency}%.2f"),
                    "Share of revenue": st.column_config.NumberColumn(format="%.1f%%"),
                })
                st.caption("Ranked by revenue. Click a column name to sort; use the search "
                           "icon above the table to find an item.")

# -------------------------------------------------------------------------
# Service
with tab_service:
    st.subheader("Party sizes")
    parties = an.party_sizes(o)
    if not an.guests_recorded(o):
        st.info("This restaurant doesn't record how many guests are on each bill, "
                "so party sizes can't be shown.")
    elif parties["orders"].sum() == 0:
        st.info("No guest counts recorded in this period.")
    else:
        left, right = st.columns(2)
        with left:
            fig = go.Figure(go.Bar(
                x=parties["party"].astype(str), y=parties["share"], marker_color=COUNT,
                text=[fmt_pct(s) for s in parties["share"]], textposition="outside",
                cliponaxis=False,
                customdata=[fmt(n, whole=True) for n in parties["orders"]],
                hovertemplate="Party of %{x}<br>%{customdata} orders · %{y:.1%}<extra></extra>",
            ))
            show(style(fig, "Share of orders by party size", 320,
                    xaxis=dict(title="Guests", type="category"),
                       yaxis=dict(visible=False, range=[0, parties["share"].max() * 1.2])),
                key="party_share")
        with right:
            dw = parties.dropna(subset=["dwell"])
            fig = go.Figure(go.Bar(
                x=dw["party"].astype(str), y=dw["dwell"], marker_color=COUNT,
                text=[f"{fmt(v)} min" for v in dw["dwell"]], textposition="outside",
                cliponaxis=False,
                customdata=[money(v) for v in dw["spend_per_cover"]],
                hovertemplate="Party of %{x}<br>%{y:.1f} min at the table<br>"
                            "%{customdata} spent per guest<extra></extra>",
            ))
            show(style(fig, "Average dwell time by party size", 320,
                    xaxis=dict(title="Guests", type="category"),
                    yaxis=dict(visible=False,
                                  range=[0, (dw["dwell"].max() if len(dw) else 1) * 1.2])),
                key="party_dwell")
        st.caption("Orders without a guest count are left out. Use the mix of party sizes "
                "to plan how many 2-tops and larger tables to set.")
        download(parties.assign(party=parties["party"].astype(str)), "party_sizes")

# -------------------------------------------------------------------------
# Payments
with tab_payments:
    st.subheader("How guests pay")
    if payments_all is None:
        st.info("Upload payments to see how guests pay.")
    else:
        pay = an.in_period(payments_all[payments_all["id_store"] == store], start, end)
        if pay.empty:
            st.info("No payments recorded in this period.")
        else:
            split = an.payment_split(pay)
            hover = [f"{m}: average payment {money(a)}"
                    for m, a in zip(split["method"], split["avg_payment"])]
            left, right = st.columns(2)
            with left:
                show(hbar(split["method"], split["amount"],
                        [f"{money(a)} · {fmt_pct(s)}" for a, s in
                        zip(split["amount"], split["amount_share"])],
                        "Amount paid", MONEY, hover), key="pay_amount")
            with right:
                show(hbar(split["method"], split["payments"],
                        [f"{fmt(c, whole=True)} payments · {fmt_pct(s)}" for c, s in
                        zip(split["payments"], split["payment_share"])],
                        "Number of payments", COUNT, hover), key="pay_count")
            st.caption("Cancelled, refunded and failed payments are not calculated.")
            download(split, "payment_methods")

# -------------------------------------------------------------------------
# Footer
st.divider()
st.caption(
    f"**Data:** {source_label} · **Showing:** {store_label(store)}, "
    f"{start:%d %b %Y} - {end:%d %b %Y} · **Data available to:** {last_day:%d %b %Y}  \n"
    "**How figures are calculated:** revenue is the amount paid on each order, incl. VAT. "
    "A trading day runs 05:00 to 05:00.")
