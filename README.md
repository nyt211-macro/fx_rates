# fx_rates

A dataset builder for **USD-parity exchange rates** sourced from the
**Banco Central do Brasil (BCB) PTAX API**.

> API reference: <https://opendata.bcb.gov.br/en/dataset/exchange-rates-daily-bulletins>

---

## What it does

`fetch_fx_rates.py` connects to the BCB PTAX OData service, retrieves the full
list of available currencies, and downloads their daily exchange rates.

By default it keeps only **USD-parity (type-A) currencies** and the
**closing bulletin** (`Fechamento`) per day, yielding one clean row per
(date, currency) pair with rates expressed as **USD per 1 unit of the foreign
currency**.

Output options: **CSV**, **Parquet**, or both. Optionally a **wide-format**
file is produced with one column per currency.

---

## Currency parity types

The BCB classifies every currency with a `tipoMoeda` field:

| Type | Parity | Rate meaning | Typical examples |
|------|--------|--------------|------------------|
| **A** | USD parity | USD per 1 unit of foreign currency | EUR, GBP, AUD, CAD, CHF, JPY, NZD, SEK, DKK, NOK, XDR … |
| **B** | BRL parity | BRL per 1 unit of foreign currency | USD, ARS, MXN, CLP, COP, CNY, KRW, INR, TRY, RUB … |

The default `--parity A` fetches **only type-A currencies** so that the
resulting dataset is internally consistent (all rates share the same USD base).

To discover the exact set of currencies currently available in each type, run:

```bash
python fetch_fx_rates.py --list-currencies
```

---

## Requirements

```bash
pip install requests pandas pyarrow
```

Python 3.10+ required (uses `list[str] | None` union syntax).

---

## Quick start

```bash
# List all available currencies by parity type
python fetch_fx_rates.py --list-currencies

# All USD-parity currencies (type A), last 1 year, CSV output
python fetch_fx_rates.py --start 2024-01-01 --end 2024-12-31

# Specific currencies, Parquet output + wide format
python fetch_fx_rates.py --start 2020-01-01 --currencies EUR GBP JPY \
    --format parquet --wide

# Include BRL-parity currencies as well
python fetch_fx_rates.py --start 2020-01-01 --parity AB --format both

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
| `--parity` | `A` | Currency parity type: `A` (USD), `B` (BRL), or `AB` (both) |
| `--list-currencies` | off | Print all available currencies by type and exit |
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
| `buy_rate` | float | BCB buy rate (USD per 1 unit of currency, for type-A) |
| `sell_rate` | float | BCB sell rate (USD per 1 unit of currency, for type-A) |
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
`https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/`

Key endpoints used:

| Endpoint | Purpose |
|----------|---------|
| `Moedas` | List all available currencies with their parity type |
| `CotacaoMoedaPeriodo(moeda,dataInicial,dataFinalCotacao)` | Rates for one currency over a date range |
