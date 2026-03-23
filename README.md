# fx_rates

A dataset builder for **FX exchange rates** sourced from the
**Banco Central do Brasil (BCB) PTAX API**, with **daily auto-update**
via GitHub Actions.

> API reference: <https://opendata.bcb.gov.br/en/dataset/exchange-rates-daily-bulletins>

---

## What it does

`fetch_fx_rates.py` connects to the BCB PTAX OData service, retrieves the full
list of available currencies, and downloads their daily exchange rates.

The **Excel output** (`--format excel`) produces a single `.xlsx` workbook with:

| Sheet | Contents |
|-------|----------|
| **USD Parity** | Type-A currencies – rate = USD per 1 unit of foreign currency |
| **BRL Parity** | Type-B currencies – rate = BRL per 1 unit of foreign currency |

Each sheet is in **wide format** (one row per date, one column per currency,
closing sell rate). The full history starts from **2000-01-01**.

A **GitHub Actions workflow** runs every weekday at 22:00 UTC (after Brazilian
market close) to rebuild the dataset and commit updated files automatically.

---

## Currency parity types

The BCB classifies every currency with a `tipoMoeda` field:

| Type | Parity | Rate meaning | Typical examples |
|------|--------|--------------|------------------|
| **A** | USD parity | USD per 1 unit of foreign currency | EUR, GBP, AUD, CAD, CHF, JPY, NZD, SEK, DKK, NOK, XDR |
| **B** | BRL parity | BRL per 1 unit of foreign currency | USD, ARS, MXN, CLP, COP, CNY, KRW, INR, TRY, RUB |

To discover the exact set of currencies currently available in each type, run:

```bash
python fetch_fx_rates.py --list-currencies
```

---

## Requirements

```bash
pip install requests pandas openpyxl pyarrow
```

Python 3.10+ required (uses `list[str] | None` union syntax).

---

## Quick start

```bash
# List all available currencies by parity type
python fetch_fx_rates.py --list-currencies

# Excel workbook with both parity tabs (full history)
python fetch_fx_rates.py --start 2000-01-01 --format excel --output data/fx_rates

# All USD-parity currencies (type A), last 1 year, CSV output
python fetch_fx_rates.py --start 2024-01-01 --end 2024-12-31

# Specific currencies, Parquet output + wide format
python fetch_fx_rates.py --start 2020-01-01 --currencies EUR GBP JPY \
    --format parquet --wide

# Include BRL-parity currencies as well (CSV)
python fetch_fx_rates.py --start 2020-01-01 --parity AB --format both
```

---

## CLI reference

| Flag | Default | Description |
|------|---------|-------------|
| `--start` | `2000-01-01` | Start date (`YYYY-MM-DD`) |
| `--end` | today | End date (`YYYY-MM-DD`) |
| `--output` | `data/fx_rates.csv` | Output file path |
| `--format` | `csv` | `csv`, `parquet`, `both`, or `excel` |
| `--currencies` | *(all)* | Space-separated currency codes to fetch |
| `--parity` | `A` | Currency parity type: `A` (USD), `B` (BRL), or `AB` (both) |
| `--list-currencies` | off | Print all available currencies by type and exit |
| `--wide` | off | Also save a wide-format file (date x currency matrix) |
| `--all-bulletins` | off | Keep all 5 daily bulletins instead of closing only |
| `--chunk-days` | `365` | Days per API request per currency |

### Format notes

- `csv`, `parquet`, `both` — produce flat files for the selected `--parity`.
- `excel` — ignores `--parity` and `--currencies`; always builds **both**
  parity types into a two-sheet `.xlsx` workbook.

---

## Output schema

### Long format (default for csv/parquet)

| Column | Type | Description |
|--------|------|-------------|
| `date` | datetime | Trading date |
| `currency` | str | ISO currency code (e.g. `EUR`, `GBP`) |
| `buy_rate` | float | BCB buy rate |
| `sell_rate` | float | BCB sell rate |
| `bulletin` | str | Bulletin type (`Fechamento` = closing) |

### Wide format (`--wide` or `--format excel`)

One row per date, one column per currency code containing the **sell rate**.

---

## Daily auto-update

The repository includes a GitHub Actions workflow
(`.github/workflows/daily_update.yml`) that:

1. Runs Mon–Fri at **22:00 UTC** (after BCB publishes the closing bulletin).
2. Fetches the full history (2000-01-01 to today) for both parity types.
3. Produces three outputs under `data/`:
   - `fx_rates.xlsx` — Excel workbook (Tab 1: USD Parity, Tab 2: BRL Parity)
   - `fx_rates_usd.csv` — flat CSV of USD-parity rates
   - `fx_rates_brl.csv` — flat CSV of BRL-parity rates
4. Commits and pushes only if the data has changed.

You can also trigger the workflow manually from the **Actions** tab.

---

## Notes

- BCB publishes rates on **Brazilian business days** only; weekends and
  Brazilian holidays have no data.
- The API date format is `MM-DD-YYYY`; the script handles conversion.
- Requests are chunked into 1-year windows per currency to stay within
  API response limits.
- A 0.3 s polite delay is applied between requests with automatic retry
  (up to 5 attempts, exponential back-off).

---

## Data source

Banco Central do Brasil – PTAX OData service
`https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/`

Key endpoints used:

| Endpoint | Purpose |
|----------|---------|
| `Moedas` | List all available currencies with their parity type |
| `CotacaoMoedaPeriodo(moeda,dataInicial,dataFinalCotacao)` | Rates for one currency over a date range |
