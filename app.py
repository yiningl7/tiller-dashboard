import pandas as pd
import plotly.express as px
import streamlit as st
import plotly.graph_objects as go

for name in ["df_order_data", "df_order_line", "df_payment_data"]:
    pd.read_csv(f"data/{name}.csv").to_parquet(f"data/{name}.parquet", index=False)

from datetime import timedelta

def short(val, prefix=""):
    """20277943 -> €20.3M, 1281148 -> 1.28M, 41171 -> 41.2K"""
    if abs(val) >= 1_000_000:
        return f"{prefix}{val / 1_000_000:.1f}M"
    if abs(val) >= 1_000:
        return f"{prefix}{val / 1_000:.1f}K"
    return f"{prefix}{val:,.2f}" if prefix else f"{val:,.0f}"

def hbar(names, values, labels, title, color, height=300):
    """Horizontal bar chart with value + % labels and no axis clutter."""
    fig = go.Figure(
        go.Bar(
            x=values,
            y=names,
            orientation="h",
            text=labels,
            textposition="outside",
            cliponaxis=False,
            marker_color=color,
            hoverinfo="skip",
        )
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        height=height,
        margin=dict(l=0, r=20, t=40, b=0),
        xaxis=dict(visible=False, range=[0, max(values) * 1.45]),
        yaxis=dict(title=None),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig

# Set page configuration
st.set_page_config(
    page_title="Tiller Restaurant Operations Dashboard",
    page_icon="🍽️",
    layout="wide",
)


# -------------------------------------------------------------------------
# Data Loading & Preparation
# -------------------------------------------------------------------------
@st.cache_data
def load_and_prep_data():
    df_order_data = pd.read_parquet("data/df_order_data.parquet")
    df_order_line = pd.read_parquet("data/df_order_line.parquet")

    # Clean headers
    df_order_data.columns = df_order_data.columns.str.strip().str.lower()
    df_order_line.columns = df_order_line.columns.str.strip().str.lower()

    # Parse datetimes
    df_order_data["date_opened"] = pd.to_datetime(df_order_data["date_opened"])
    df_order_data["date_closed"] = pd.to_datetime(df_order_data["date_closed"])

    return df_order_data, df_order_line


df_order_data, df_order_line = load_and_prep_data()

# -------------------------------------------------------------------------
# Sidebar Filters
# -------------------------------------------------------------------------
st.sidebar.header("Filter Options")

# Date Filter
min_date = df_order_data["date_opened"].dt.date.min()
max_date = df_order_data["date_opened"].dt.date.max()

selected_dates = st.sidebar.date_input(
    "Select Date Range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)

# Apply Date Filter
if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
    start_date, end_date = selected_dates
    filtered_order_data = df_order_data[
        (df_order_data["date_opened"].dt.date >= start_date)
        & (df_order_data["date_opened"].dt.date <= end_date)
    ]
else:
    filtered_order_data = df_order_data.copy()

filtered_order_line = df_order_line[
    df_order_line["id_order"].isin(filtered_order_data["id_order"])
]

# -------------------------------------------------------------------------
# Main Dashboard Layout
# -------------------------------------------------------------------------
st.title("🍽️ Tiller Restaurant Operational Efficiency Dashboard")

# --- High-Level Metric Cards ---
revenue_col = "m_cached_payed" if "m_cached_payed" in df_order_data.columns else "m_cached_price"
table_col = next((c for c in df_order_data.columns if "table" in c), None)


def compute_kpis(df):
    revenue = df[revenue_col].sum()
    orders = df["id_order"].nunique()

    with_covers = df[df["m_nb_customer"] > 0]
    covers = with_covers["m_nb_customer"].sum()

    dwell = (df["date_closed"] - df["date_opened"]).dt.total_seconds() / 60
    dwell = dwell[(dwell > 0) & (dwell <= 240)]

    turns = 0.0
    if table_col:
        t = df[df[table_col].notna()
            & ~df[table_col].astype(str).str.strip().isin(["", "0"])]
        if not t.empty:
            turns = (
                t.groupby(["id_store", t["date_opened"].dt.date, table_col])["id_order"]
                .nunique()
                .mean()
            )

    return {
        "revenue": revenue,
        "orders": orders,
        "avg_ticket": revenue / orders if orders else 0,
        "spend_per_cover": with_covers[revenue_col].sum() / covers if covers else 0,
        "dwell": dwell.mean() if not dwell.empty else 0,
        "turns": turns,
    }


cur = compute_kpis(filtered_order_data)

# Compare with the previous period of the same length
prev = None
if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
    span = (end_date - start_date) + timedelta(days=1)
    order_dates = df_order_data["date_opened"].dt.date
    prev_df = df_order_data[(order_dates >= start_date - span) & (order_dates < start_date)]
    if not prev_df.empty:
        prev = compute_kpis(prev_df)


def delta(key):
    if not prev or not prev[key]:
        return None
    return f"{(cur[key] - prev[key]) / prev[key]:+.1%} vs prev. period"


st.markdown("##### Sales")
c1, c2, c3 = st.columns(3)
c1.metric("Revenue", short(cur["revenue"], "€"), delta("revenue"),
        help=f"Exact: €{cur['revenue']:,.2f}", border=True)
c2.metric("Orders", short(cur["orders"]), delta("orders"),
        help=f"Exact: {cur['orders']:,}", border=True)
c3.metric("Average ticket", f"€{cur['avg_ticket']:.2f}", delta("avg_ticket"),
        help="Average revenue per order", border=True)

st.markdown("##### Service")
c4, c5, c6 = st.columns(3)
c4.metric("Spend per cover", f"€{cur['spend_per_cover']:.2f}", delta("spend_per_cover"),
        help="Average revenue per customer", border=True)
c5.metric("Average dwell time", f"{cur['dwell']:.1f} min", delta("dwell"),
        delta_color="off",
        help="Time from table opened to closed, excluding stays over 4 hours", border=True)
c6.metric("Table turnover", f"{cur['turns']:.2f} turns/day", delta("turns"),
        help="Average orders per table per day", border=True)

st.divider()

# --- Hourly Rush Chart Section ---
st.subheader("📊 Hourly Demand & Peak Hour Analysis")

df_ops = filtered_order_data.copy()
df_ops["opening_hour"] = df_ops["date_opened"].dt.hour

hourly_perf = (
    df_ops.groupby("opening_hour")
    .agg(
        total_orders=("id_order", "nunique"),
        total_revenue=(revenue_col, "sum"),
        total_customers=("m_nb_customer", "sum"),
    )
    .reset_index()
)

fig_hourly = px.bar(
    hourly_perf,
    x="opening_hour",
    y="total_orders",
    color="total_revenue",
    labels={
        "opening_hour": "Hour of Day (24h)",
        "total_orders": "Order Count",
        "total_revenue": "Revenue (€)",
    },
    title="Order Volume and Revenue by Hour of Day",
    color_continuous_scale="Viridis",
)
fig_hourly.update_layout(xaxis=dict(tickmode="linear", tick0=0, dtick=1))

st.plotly_chart(fig_hourly, use_container_width=True)

# --- Top / Bottom Performers Section ---
st.divider()
st.subheader("🏆 Product Performance Overview")

col_top_5 = st.columns(1)[0]

df_products = filtered_order_line.copy()
if "dim_type" in df_products.columns:
    df_products = df_products[
        df_products["dim_type"].astype(str).str.strip().str.lower() == "product"
    ]

exclude_terms = ["DEPOSIT", "CONSIGNE", "ORDER", "DELIVERY PACKAGE"]
pattern = "|".join(exclude_terms)

df_products = df_products[
    ~df_products["dim_name_translated"]
    .astype(str)
    .str.upper()
    .str.contains(pattern)
    & ~df_products["dim_category_translated"]
    .astype(str)
    .str.upper()
    .str.contains(pattern)
]

performers = (
    df_products.groupby("dim_name_translated")
    .agg(
        quantity_sold=("m_quantity", "sum"),
        total_revenue=("m_total_price_inc_vat", "sum"),
    )
    .reset_index()
)

with col_top_5:
    st.subheader("Top 5 Products Sold")

    total_rev = performers["total_revenue"].sum()
    total_qty = performers["quantity_sold"].sum()

    top_5 = performers.sort_values("quantity_sold", ascending=False).head(5).copy()
    top_5["volume_pct"] = top_5["quantity_sold"] / total_qty
    top_5["revenue_pct"] = top_5["total_revenue"] / total_rev

    # Plotly draws horizontal bars bottom-up, so reverse to put #1 on top
    plot_df = top_5.iloc[::-1]

    def product_bar(values, labels, title, color):
        fig = go.Figure(
            go.Bar(
                x=values,
                y=plot_df["dim_name_translated"],
                orientation="h",
                text=labels,
                textposition="outside",
                cliponaxis=False,
                marker_color=color,
                hoverinfo="skip",
            )
        )
        fig.update_layout(
            title=dict(text=title, font=dict(size=16)),
            height=300,
            margin=dict(l=0, r=20, t=40, b=0),
            xaxis=dict(visible=False, range=[0, values.max() * 1.45]),
            yaxis=dict(title=None),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        return fig

    units_labels = [
        f"{q:,.0f} units · {p:.1%}"
        for q, p in zip(plot_df["quantity_sold"], plot_df["volume_pct"])
    ]
    revenue_labels = [
        f"€{r / 1000:,.0f}k · {p:.1%}"
        for r, p in zip(plot_df["total_revenue"], plot_df["revenue_pct"])
    ]

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            product_bar(plot_df["quantity_sold"], units_labels,
                        "Units sold", "#4C78A8"),
            use_container_width=True,
            config={"displayModeBar": False},
        )
    with right:
        st.plotly_chart(
            product_bar(plot_df["total_revenue"], revenue_labels,
                        "Revenue", "#F58518"),
            use_container_width=True,
            config={"displayModeBar": False},
        )

#####PAYMENT ANALYSIS SECTION#####
# -------------------------------------------------------------------------
# 1. Load & Clean Data
# -------------------------------------------------------------------------
df_payment_data = pd.read_parquet("data/df_payment_data.parquet")

# Clean column headers
df_payment_data.columns = df_payment_data.columns.str.strip().str.lower()

# -------------------------------------------------------------------------
# 2. Payment Analysis Function
# -------------------------------------------------------------------------
def calculate_payment_split(df_payment_data: pd.DataFrame):
    """Calculates revenue and transaction volume split across payment types."""
    df_pay = df_payment_data.copy()

    # Filter out failed or void payments if dim_status is present
    if "dim_status" in df_pay.columns:
        # Standardise status strings
        df_pay = df_pay[
            ~df_pay["dim_status"]
            .astype(str)
            .str.upper()
            .isin(["CANCELLED", "VOID", "REFUNDED", "FAILED"])
        ]

    # Group by payment method
    payment_split = (
        df_pay.groupby("dim_type")
        .agg(
            total_amount=("m_amount", "sum"),
            transaction_count=("id_pay", "count"),
        )
        .reset_index()
    )

    # Calculate percentages
    total_revenue = payment_split["total_amount"].sum()
    total_tx = payment_split["transaction_count"].sum()

    payment_split["revenue_percentage"] = (
        (payment_split["total_amount"] / total_revenue) * 100
        if total_revenue > 0
        else 0
    )

    payment_split["volume_percentage"] = (
        (payment_split["transaction_count"] / total_tx) * 100
        if total_tx > 0
        else 0
    )

    # Sort by total revenue descending
    payment_split = payment_split.sort_values(
        by="total_amount", ascending=False
    )

    return payment_split


# -------------------------------------------------------------------------
# 3. Streamlit Display Component
# -------------------------------------------------------------------------

# 1. Define a helper function to abbreviate large numbers
def format_abbrev(val, is_currency=False):
    prefix = "€" if is_currency else ""
    if val >= 1_000_000:
        return f"{prefix}{val/1_000_000:.2f}m"
    elif val >= 1_000:
        return f"{prefix}{val/1_000:.0f}k"
    return f"{prefix}{val:.2f}" if is_currency else str(int(val))

# 2. Process your payment data (existing logic)
payment_df = calculate_payment_split(df_payment_data)
payment_df = payment_df.sort_values(by="total_amount", ascending=False)

top_4_df = payment_df.head(4)
others_df = payment_df.iloc[4:]

if not others_df.empty:
    others_row = pd.DataFrame({
        "dim_type": ["Others"],
        "total_amount": [others_df["total_amount"].sum()],
        "transaction_count": [others_df["transaction_count"].sum()],
        "revenue_percentage": [others_df["revenue_percentage"].sum()],
        "volume_percentage": [others_df["volume_percentage"].sum()]
    })
    display_df = pd.concat([top_4_df, others_row], ignore_index=True)
else:
    display_df = payment_df.copy()

# 3. Create new columns with the abbreviated string formats
display_df["formatted_amount"] = display_df["total_amount"].apply(
    lambda x: format_abbrev(x, is_currency=True)
)
display_df["formatted_count"] = display_df["transaction_count"].apply(
    lambda x: format_abbrev(x, is_currency=False)
)

st.divider()
st.subheader("💳 Payment Method Split")

# Friendlier names: TICKET_RESTAURANT -> Ticket Restaurant
display_df["method"] = display_df["dim_type"].str.replace("_", " ").str.title()

# Reverse so the biggest method sits on top (and "Others" stays at the bottom)
pay_plot = display_df.iloc[::-1]

amount_labels = [
    f"{format_abbrev(a, is_currency=True)} · {p:.1f}%"
    for a, p in zip(pay_plot["total_amount"], pay_plot["revenue_percentage"])
]
count_labels = [
    f"{format_abbrev(c)} payments · {p:.1f}%"
    for c, p in zip(pay_plot["transaction_count"], pay_plot["volume_percentage"])
]

left, right = st.columns(2)
with left:
    st.plotly_chart(
        hbar(pay_plot["method"], pay_plot["total_amount"], amount_labels,
            "Amount paid", "#F58518"),
        use_container_width=True,
        config={"displayModeBar": False},
    )
with right:
    st.plotly_chart(
        hbar(pay_plot["method"], pay_plot["transaction_count"], count_labels,
            "Number of payments", "#4C78A8"),
        use_container_width=True,
        config={"displayModeBar": False},
    )
