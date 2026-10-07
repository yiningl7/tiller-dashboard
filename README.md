# 🍽️ Tiller Restaurant Operations Dashboard

An interactive Streamlit dashboard that helps restaurant owners understand their sales, products, service and payments, built on real order data from restaurants across Paris using the [Tiller by SumUp](https://www.tillersystems.com/) point-of-sale system.

**Live demo:** https://tiller-dashboard.streamlit.app/

## Why this project

Tiller offers restaurants a full ecosystem of tools (cash register, payments, table management), but no analytics tool to help owners turn their sales data into decisions. This dashboard is a prototype of what that tool could look like: the key numbers an owner checks every day, presented clearly and filterable by date.

## Features

- **KPI overview:** revenue, orders, average ticket, spend per cover, average dwell time and table turnover, with % change versus the previous period of the same length.
- **Hourly demand:** order volume and revenue by hour of day, to spot rush hours and plan staffing.
- **Top products:** the five best sellers by units and by revenue, with each product's share of the total.
- **Payment methods:** how customers pay, by amount and by number of payments, including average payment size.
- **Date filter:** every section updates for the selected date range.

## Key insights

- Card payments make up about **52% of payments but 89% of revenue**, while cash makes up about **44% of payments but under 6% of revenue**. Cash is used often, but for small amounts.
- The **50 cl Blonde Meteor** is by far the best seller, with over 237,000 units sold.
- The **1.5 L Blonde Meteor** ranks 5th by units but 2nd by revenue, because each sale is worth much more.

## Data

The dataset comes from Tiller and was provided through the Le Wagon bootcamp (originally hosted in BigQuery). It contains four tables:

| Table | Description |
|---|---|
| `order_data` | One row per order: store, table, waiter, open/close times, number of guests, amount paid |
| `order_line` | One row per item ordered: product, category, quantity, price, VAT, discounts |
| `payment_data` | One row per payment: type (card, cash, meal voucher…), status, amount |
| `store_data` | One row per restaurant: subscription date, zipcode, country, currency |

### Data preparation

The raw CSVs (over 600 MB) are too large for GitHub and for Streamlit Community Cloud's memory limit, so `convert_to_parquet.py` prepares lighter versions:

- keeps only the columns the dashboard uses;
- pre-aggregates order lines to **one row per day per product** (414 MB CSV → 2.5 MB);
- stores repeated text as categories and saves everything as compressed Parquet.

The raw CSVs are not included in this repository.

### Cleaning choices

- Dwell times of 0 minutes or over 4 hours are excluded as data errors.
- Discount lines, deposits and delivery fees are excluded from product rankings.
- Cancelled, void, refunded and failed payments are excluded from the payment split.

## Tech stack

Python · pandas · Plotly · Streamlit · Parquet (pyarrow)

## Project structure

```
├── app.py                    # Streamlit dashboard
├── convert_to_parquet.py     # Prepares the data from the raw CSVs
├── requirements.txt
└── data/
    ├── df_order_data.parquet
    ├── df_product_daily.parquet
    └── df_payment_data.parquet
```

## Run it locally

```bash
git clone https://github.com/yiningl7/tiller-dashboard.git
cd tiller-dashboard
pip install -r requirements.txt
streamlit run app.py
```

To rebuild the Parquet files, place the raw CSVs in `data/` and run:

```bash
python convert_to_parquet.py
```

## Next steps

- Revenue trend over time with a sales forecast
- Busiest-hours heatmap (day of week × hour) for staff planning
- Menu engineering matrix (popularity vs. revenue per item)
- Restaurant selector and benchmarking against similar restaurants in the same area

## Author

**Andrea Yining Liu** · [GitHub](https://github.com/yiningl7) · [LinkedIn](https://www.linkedin.com/in/yining-liu-10b030221)
