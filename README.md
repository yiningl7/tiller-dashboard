# Restaurant Insights

An interactive Streamlit dashboard that helps restaurant owners understand their sales, menu, service and payments, built on real order data from restaurants across Paris using the [Tiller by SumUp](https://www.tillersystems.com/) point-of-sale system.

**Live demo:** https://tiller-dashboard.streamlit.app/

## Why this project

Tiller offers restaurants a full ecosystem of tools (cash register, payments, table management), but no analytics tool to help owners turn their sales data into decisions. This dashboard is a prototype of what that tool could look like: the key numbers an owner checks every day, for their own restaurant, compared with similar restaurants, and readable on a phone.

## Features

Pick a restaurant and a date range in the sidebar. Everything on the page follows that choice.

| Tab | What it shows |
|---|---|
| **Overview** | Revenue, orders, average ticket, spend per guest, dwell time and table turnover, with % change vs the previous period of the same length. Daily revenue trend (weekly for long ranges). How the restaurant compares with the median of similar restaurants. |
| **Sales** | Average orders or revenue per day by hour. Weekday × hour heatmap for staff planning. Lunch vs dinner and weekdays vs weekends. |
| **Menu** | Top 5 items by units and by revenue, each ranked on its own, filterable by category. Menu engineering matrix (Stars, Plowhorses, Puzzles, Dogs). |
| **Service** | Party-size mix and average dwell time by party size, for floor planning. |
| **Payments** | How guests pay, by amount and by number of payments, with average payment size. |

Also:

- **Restaurant settings:** number of tables, opening hours, lunch and dinner times, which line items aren't menu items (deposits, delivery fees…) and the currency symbol.
- **Use your own data:** a restaurant can upload CSV exports from its till to try the dashboard before any integration exists.
- **Download data (CSV)** under every chart, and a footer stating the data source, dates shown and how figures are calculated.

## Key insights (all restaurants in the dataset)

- Card payments make up about **52% of payments but 89% of revenue**, while cash makes up about **44% of payments but under 6% of revenue**. Cash is used often, but for small amounts.
- The **50 cl Blonde Meteor** is by far the best seller, with over 237,000 units sold.
- The **1.5 L Blonde Meteor** ranks 5th by units but 2nd by revenue, because each sale is worth much more.

## How figures are calculated

- **Revenue** is the amount paid on each order, incl. VAT (`m_cached_payed`). It's used for every revenue figure on the Overview and Sales tabs. Item revenue on the Menu tab comes from order lines and payment totals from payments, so those can differ slightly (discounts, tips, split bills); each tab says so.
- **Trading day:** a day runs 05:00 to 05:00, so a 01:00 order on Saturday counts towards Friday night.
- **Averages per day** divide by the days the restaurant actually traded in the period.
- **Table turnover** is orders served at a table ÷ (number of tables × trading days). The table count starts at the number of tables seen in the data and can be changed in Restaurant settings.
- **% change** is only shown when a full previous period of the same length exists in the data.
- **Benchmarks** use the median of at least 3 other restaurants with 30+ orders on the same dates: restaurants in the same postcode when there are enough of them, otherwise all other restaurants. Peers are anonymised.

### Cleaning choices

- Dwell times of 0 minutes or over 4 hours are excluded as data errors.
- Discount lines, deposits and delivery fees are excluded from the Menu tab (the word list is editable in Restaurant settings).
- Cancelled, void, refunded and failed payments are excluded.

## Data

The dataset comes from Tiller and was provided through the Le Wagon bootcamp (originally hosted in BigQuery). It contains four tables:

| Table | Description |
|---|---|
| `order_data` | One row per order: store, table, waiter, open/close times, number of guests, amount paid |
| `order_line` | One row per item ordered: product, category, quantity, price, VAT, discounts |
| `payment_data` | One row per payment: type (card, cash, meal voucher…), status, amount |
| `store_data` | One row per restaurant: subscription date, zipcode, country, currency |

### Data preparation

The raw CSVs (over 600 MB) are too large for GitHub and for Streamlit Community Cloud's memory limit, so `convert_to_parquet.py` prepares lighter versions using the same rules as the app (`data.py`):

- keeps only the columns the dashboard uses;
- reduces order lines to **one row per restaurant, trading day and product**;
- tags each payment with its restaurant and trading day, so payments follow the filters;
- keeps each restaurant's postcode and currency for benchmarks and labels;
- stores repeated text as categories and saves everything as compressed Parquet.

The raw CSVs are not included in this repository.

### Uploading your own data

Upload CSVs under **Use your own data** in the sidebar. Column names follow the Tiller export:

| File | Required columns | Optional |
|---|---|---|
| Orders | `id_order`, `date_opened`, and `m_cached_payed` or `m_cached_price` | `id_store`, `id_table`, `date_closed`, `m_nb_customer` |
| Order lines | `id_order`, `dim_name_translated`, `m_quantity`, `m_total_price_inc_vat` | `dim_type`, `dim_category_translated` |
| Payments | `id_order`, `dim_type`, `m_amount` | `id_pay`, `dim_status` |

## Tech stack

Python · pandas · Plotly · Streamlit · Parquet (pyarrow)

## Project structure

```
├── app.py                    # Streamlit dashboard (layout and charts)
├── analysis.py               # Every figure on the page, in plain pandas
├── data.py                   # Loading and cleaning, shared by the app and the converter
├── convert_to_parquet.py     # Prepares the data from the raw CSVs
├── requirements.txt
├── .streamlit/config.toml    # Theme: colours and fonts
└── data/
    ├── df_order_data.parquet
    ├── df_product_daily.parquet
    ├── df_payment_data.parquet
    └── df_store_data.parquet
```

## Run it locally

```bash
git clone https://github.com/yiningl7/tiller-dashboard.git
cd tiller-dashboard
pip install -r requirements.txt
streamlit run app.py
```

To rebuild the Parquet files, place the raw CSVs (`df_order_data.csv`, `df_order_line.csv`, `df_payment_data.csv`, `df_store_data.csv`) in `data/` and run:

```bash
python convert_to_parquet.py
```

## Next steps

- Revenue trend vs the same period last year, with a sales forecast
- Weekly email summary and alerts (e.g. "Revenue down 12% vs last Tuesday")
- Log-in so each owner only sees their own restaurant
- Item costs, to turn the menu engineering matrix from price into true profit

## Author

**Andrea Yining Liu** · [GitHub](https://github.com/yiningl7) · [LinkedIn](https://www.linkedin.com/in/yining-liu-10b030221)
