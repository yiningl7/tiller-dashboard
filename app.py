import io
import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analysis as an
from analysis import fmt, fmt_pct
from data import (DEFAULT_EXCLUDED_ITEMS, REQUIRED_COLS, REVENUE_COLS, SINGLE_STORE_ID,
                  load_bundled, missing_columns, prepare)

st.set_page_config(page_title="Restaurant Insights", page_icon="🍽️", layout="wide")

# Colours: orange = money, blue = counts, used the same way in every chart
MONEY = "#eb6834"
COUNT = "#2a78d6"
SEQUENTIAL = ["#eef5fd", "#b7d3f6", "#6da7ec", "#2a78d6", "#1c5cab", "#0d366b"]
CLASS_COLORS = {"Star": "#2a78d6", "Plowhorse": "#eb6834", "Puzzle": "#1baf7a", "Dog": "#a3a19b"}
FONT = "Inter, sans-serif"
CHART_CONFIG = {"displayModeBar": False}


# -------------------------------------------------------------------------
# Chart helpers
# -------------------------------------------------------------------------
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
# -------------------------------------------------------------------------
@st.cache_resource(show_spinner="Loading data…")
def bundled_data():
    return load_bundled()


@st.cache_data(show_spinner="Reading your files…", max_entries=2)
def uploaded_data(orders_b, lines_b, pay_b):
    read = lambda b: pd.read_csv(io.BytesIO(b)) if b else None  # noqa: E731
    return prepare(read(orders_b), read(lines_b), read(pay_b))


def upload_panel():
    """Lets a restaurant try the dashboard on its own till export."""
    with st.sidebar.expander("Use your own data"):
        st.caption("Upload CSV exports from your till. Orders are required; "
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
    data = bundled_data()

orders_all = data["orders"]
products_all = data["products"]
payments_all = data["payments"]
stores = data["stores"]

# -------------------------------------------------------------------------
# Sidebar: restaurant, dates, settings
# -------------------------------------------------------------------------
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
        help="Used for table turnover. Starts at the number of tables seen in the data.")
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
        help="Comma-separated words. Lines whose name or category contains one of "
             "them (deposits, delivery fees…) are left out of the Menu tab.")
    store_currency = currencies.get(store)
    currency = st.text_input("Currency symbol",
                             store_currency if isinstance(store_currency, str) else "€",
                             key=f"cur_{store}", max_chars=4)

exclude_terms = [t for t in exclude_text.split(",") if t.strip()]
if not tables_seen:  # no table numbers in the data, so turnover can't be measured
    n_tables = None
hours = an.ordered_hours(open_h, close_h)
money = lambda v: fmt(v, currency)  # noqa: E731

# -------------------------------------------------------------------------
# Header and period checks
# -------------------------------------------------------------------------
st.title("Restaurant Insights")

if not (isinstance(dates, tuple) and len(dates) == 2):
    st.info("Pick an end date to see the figures.")
    st.stop()
start, end = dates
st.caption(f"{store_label(store)} · {start:%d %b %Y} – {end:%d %b %Y} "
           f"({(end - start).days + 1} days)")

o = an.in_period(o_store, start, end)
if o.empty:
    st.warning("No orders in this period. Pick another date range in the sidebar.")
    st.stop()

prev_start, prev_end = an.previous_period(start, end)
has_history = prev_start >= first_day
cur = an.kpis(o, n_tables)
prev = an.kpis(an.in_period(o_store, prev_start, prev_end), n_tables) if has_history else None

tab_overview, tab_sales, tab_menu, tab_service, tab_payments = st.tabs(
    ["Overview", "Sales", "Menu", "Service", "Payments"])

# -------------------------------------------------------------------------
# Overview
# -------------------------------------------------------------------------
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
           "Revenue per guest, on orders where the number of guests was recorded")
    metric(c5, "Average dwell time",
           f"{fmt(cur['dwell'])} min" if cur["dwell"] is not None else "–", "dwell",
           "Time from table opened to closed. Stays over 4 hours are left out as errors.",
           delta_color="off")
    metric(c6, "Table turnover",
           f"{fmt(cur['turns'])} turns/day" if cur["turns"] is not None else "–", "turns",
           f"Table orders per table per trading day, across all {n_tables} tables "
           "(set the table count in Restaurant settings)." if n_tables else
           "Table numbers aren't recorded in this data, so turnover can't be measured.")
    if not has_history:
        st.caption("No change shown: there isn't a full previous period of the same "
                   "length before these dates.")

    trend, grain = an.revenue_trend(o, start, end)
    fig = go.Figure(go.Scatter(
        x=trend["period"], y=trend["revenue"], mode="lines+markers" if len(trend) <= 45 else "lines",
        line=dict(color=MONEY, width=2), marker=dict(size=7),
        customdata=[money(v) for v in trend["revenue"]],
        hovertemplate=("%{x|%a %d %b %Y}" if grain == "day" else "Week of %{x|%d %b %Y}")
                      + "<br>%{customdata}<extra></extra>",
    ))
    show(style(fig, "Daily revenue" if grain == "day" else "Weekly revenue", 340,
               xaxis=dict(title=None, showgrid=False),
               yaxis=dict(title=None, gridcolor="rgba(128,128,128,0.15)", rangemode="tozero",
                          **axis_ticks(trend["revenue"].max(), currency)),
               hovermode="x"), key="trend")
    download(trend.rename(columns={"period": grain}), "revenue_trend")

    st.markdown("##### How you compare")
    bench = an.benchmark(an.in_period(orders_all, start, end), store, stores)
    if bench is None:
        st.caption("Benchmarks need at least 3 other restaurants with orders on the same dates.")
    else:
        you, peers = bench["you"], bench["peers"]

        def vs(key):
            c = an.change(you[key], peers[key])
            return None if c is None or pd.isna(c) else f"{fmt_pct(c, signed=True)} vs peers"

        b1, b2, b3, b4 = st.columns(4)
        b1.metric("Average ticket", money(you["avg_ticket"]), vs("avg_ticket"),
                  help=f"Peer median: {money(peers['avg_ticket'])}", border=True)
        b2.metric("Spend per guest", money(you["spend_per_cover"]), vs("spend_per_cover"),
                  help=f"Peer median: {money(peers['spend_per_cover'])}", border=True)
        b3.metric("Revenue per trading day", money(you["revenue_per_day"]),
                  vs("revenue_per_day"),
                  help=f"Peer median: {money(peers['revenue_per_day'])}", border=True)
        b4.metric("Average dwell time", f"{fmt(you['dwell'])} min", vs("dwell"),
                  delta_color="off",
                  help=f"Peer median: {fmt(peers['dwell'])} min", border=True)
        st.caption(f"Compared with the median of {bench['n_peers']} {bench['group']} on the "
                   "same dates. Other restaurants are anonymised. Hover a figure to see the "
                   "peer median.")

# -------------------------------------------------------------------------
# Sales
# -------------------------------------------------------------------------
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

    st.subheader("Busiest times of the week")
    heat = an.weekday_hour(o, hours)
    fig = go.Figure(go.Heatmap(
        z=heat.values, x=heat.columns, y=heat.index,
        colorscale=[[i / (len(SEQUENTIAL) - 1), c] for i, c in enumerate(SEQUENTIAL)],
        xgap=2, ygap=2, colorbar=dict(title="Orders", thickness=10),
        hovertemplate="%{y} %{x}<br>%{z:.1f} orders on average<extra></extra>",
        hoverongaps=False,
    ))
    show(style(fig, "Average orders by weekday and hour opened", 360,
               xaxis=dict(title=None, type="category", showgrid=False),
               yaxis=dict(title=None, autorange="reversed", showgrid=False)), key="heatmap")
    download(heat.reset_index(names="weekday"), "weekday_hour_orders")

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
        st.caption(f"Lunch {an.hour_label(lunch[0])}–{an.hour_label(lunch[1])}, dinner from "
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
# -------------------------------------------------------------------------
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

            st.subheader("Top 5 items")
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
                          "By units sold", COUNT, hover(by_units)), key="top_units")
            with right:
                show(hbar(by_rev["item"], by_rev["revenue"],
                          [f"{money(r)} · {fmt_pct(s)}" for r, s in
                           zip(by_rev["revenue"], by_rev["share"])],
                          "By revenue", MONEY, hover(by_rev)), key="top_revenue")
            st.caption("Each chart is ranked on its own. Percentages are shares of "
                       f"{'all items' if category == 'All categories' else category} sold. "
                       "Item revenue comes from order lines incl. VAT, so it can differ "
                       "slightly from order revenue.")
            download(pd.concat([by_units.assign(ranked_by="units"),
                                by_rev.assign(ranked_by="revenue")]), "top_items")

            st.subheader("Menu engineering")
            matrix, pop_line, price_line = an.menu_matrix(items)
            fig = go.Figure()
            for cls in an.MENU_CLASSES:
                d = matrix[matrix["class"] == cls]
                fig.add_trace(go.Scatter(
                    x=d["units"], y=d["avg_price"], mode="markers", name=f"{cls}s",
                    marker=dict(size=9, color=CLASS_COLORS[cls], opacity=0.85,
                                line=dict(width=1, color="white")),
                    customdata=[[i, c, money(r)] for i, c, r in
                                zip(d["item"], d["category"], d["revenue"])],
                    hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>"
                                  "%{x:,.0f} sold · average price " + currency +
                                  "%{y:.1f}<br>Revenue %{customdata[2]}<extra>" + cls + "</extra>",
                ))
            # Dividing lines drawn as plain traces so they sit in data units on the log axis
            guide = dict(mode="lines", line=dict(color="gray", width=1, dash="dot"),
                         hoverinfo="skip", showlegend=False)
            x_lo, x_hi = matrix["units"].min() * 0.8, matrix["units"].max() * 1.25
            y_lo, y_hi = 0, matrix["avg_price"].max() * 1.05
            fig.add_trace(go.Scatter(x=[pop_line, pop_line], y=[y_lo, y_hi], **guide))
            fig.add_trace(go.Scatter(x=[x_lo, x_hi], y=[price_line, price_line], **guide))
            show(style(fig, "Popularity vs price", 460, showlegend=True,
                       legend=dict(orientation="h", y=-0.15),
                       xaxis=dict(title="Units sold (log scale)", type="log",
                                  gridcolor="rgba(128,128,128,0.15)"),
                       yaxis=dict(title="Average price", tickprefix=currency,
                                  gridcolor="rgba(128,128,128,0.15)")), key="matrix")
            counts = matrix["class"].value_counts().reindex(an.MENU_CLASSES, fill_value=0)
            st.caption(
                f"**Stars** ({counts['Star']}): popular and above-average price, keep them "
                f"prominent. **Plowhorses** ({counts['Plowhorse']}): popular but cheaper, "
                f"try a small price rise. **Puzzles** ({counts['Puzzle']}): pricier but slow "
                f"sellers, promote or rework them. **Dogs** ({counts['Dog']}): neither, "
                "consider removing them. Popular means at least 70% of an even share of "
                "units. Item costs aren't in the data, so average price stands in for "
                "profit. Compare within one category for the fairest picture.")
            download(matrix.sort_values("revenue", ascending=False), "menu_engineering")

# -------------------------------------------------------------------------
# Service
# -------------------------------------------------------------------------
with tab_service:
    st.subheader("Party sizes")
    parties = an.party_sizes(o)
    if parties["orders"].sum() == 0:
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
# -------------------------------------------------------------------------
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
            st.caption("Cancelled, void, refunded and failed payments are left out. Totals "
                       "can differ slightly from order revenue (tips, split bills).")
            download(split, "payment_methods")

# -------------------------------------------------------------------------
# Footer
# -------------------------------------------------------------------------
st.divider()
st.caption(
    f"**Data:** {source_label} · **Showing:** {store_label(store)}, "
    f"{start:%d %b %Y} – {end:%d %b %Y} · **Data available to:** {last_day:%d %b %Y}  \n"
    "**How figures are calculated:** revenue is the amount paid on each order, incl. VAT. "
    "A trading day runs 05:00 to 05:00, so late-night orders count towards the evening "
    "they belong to.")
