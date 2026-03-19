# fx_rates

A dataset builder for **USD-parity exchange rates** sourced from the
**Banco Central do Brasil (BCB) PTAX API**.

> API reference: <https://opendata.bcb.gov.br/en/dataset/exchange-rates-daily-bulletins>

---

## What it does

`fetch_fx_rates.py` connects to the BCB PTAX OData service, retrieves the full
list of available currencies, and downloads their daily exchange rates expressed
in **USD parity** (i.e. how many units of each currency equal 1 USD).

By default it keeps only the **closing bulletin** (`Fechamento`) per day,
yielding one clean row per (date, currency) pair.

Output options: **CSV**, **Parquet**, or both. Optionally a **wide-format**
file is produced with one column per currency.

---

## Requirements

```bash
pip install requests pandas pyarrow
```

Python 3.10+ required (uses `list[str] | None` union syntax).

---

## Quick start

```bash
# All currencies, last 1 year, CSV output
python fetch_fx_rates.py --start 2024-01-01 --end 2024-12-31

# Specific currencies, Parquet output + wide format
python fetch_fx_rates.py --start 2020-01-01 --currencies EUR GBP JPY CNY \
    --format parquet --wide

# Full history since 2000, all formats
python fetch_fx_rates.py --start 2000-01-01 --format both --output data/fx_rates
```

---

## CLI reference

| Flag | Default | Description |
|------|---------|-------------|
| `--start` | `2000-01-01` | Start date (`YYYY-MM-DD`) |
| `--end` | today | End date (`YYYY-MM-DD`) |
| `--output` | `data/fx_rates.csv` | Output file path |
| `--format` | `csv` | `csv`, `parquet`, or `both` |
| `--currencies` | *(all)* | Space-separated currency codes to fetch |
| `--wide` | off | Also save a wide-format file (date × currency matrix) |
| `--all-bulletins` | off | Keep all 5 daily bulletins instead of closing only |
| `--chunk-days` | `365` | Days per API request per currency |

---

## Output schema

### Long format (default)

| Column | Type | Description |
|--------|------|-------------|
| `date` | datetime | Trading date |
| `currency` | str | ISO currency code (e.g. `EUR`, `GBP`) |
| `buy_rate` | float | BCB buy rate (USD parity) |
| `sell_rate` | float | BCB sell rate (USD parity) |
| `bulletin` | str | Bulletin type (`Fechamento` = closing) |

### Wide format (`--wide`)

One row per date, one column per currency code containing the **sell rate**.

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
`https://olinda.bcb.gov.br/olinda/service/PTAX/version/v1/odata/`

Key endpoints used:

| Endpoint | Purpose |
|----------|---------|
| `Moedas` | List all available currencies |
| `CotacaoMoedaPeriodo(moeda,dataInicial,dataFinal)` | Rates for one currency over a date range |
