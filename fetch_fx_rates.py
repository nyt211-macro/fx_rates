"""
BCB PTAX FX Rates Dataset Builder
==================================
Fetches USD-parity exchange rates for currencies available in the
Banco Central do Brasil (BCB) PTAX API.

API: https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/
Docs: https://opendata.bcb.gov.br/en/dataset/exchange-rates-daily-bulletins

Currency parity types
---------------------
The BCB classifies each currency with a ``tipoMoeda`` field:

  Type A – USD parity
    Rates are expressed as **USD per 1 unit of the foreign currency**.
    Examples: EUR, GBP, AUD, CAD, CHF, JPY, NZD, SEK, DKK, NOK, XDR …
    These are the currencies fetched by default (``--parity A``).

  Type B – BRL parity
    Rates are expressed as **BRL per 1 unit of the foreign currency**
    (or BRL per USD for the USD line itself).
    Examples: USD, ARS, MXN, CLP, COP, CNY, KRW, INR, TRY, RUB …
    Include these with ``--parity B`` or ``--parity AB``.

Usage:
    python fetch_fx_rates.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
                             [--output data/fx_rates.csv] [--format csv|parquet]
                             [--currencies EUR GBP JPY ...]
                             [--parity A|B|AB]
                             [--list-currencies]
"""

import argparse
import logging
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata"
SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (compatible; BCB-FX-Rates-Fetcher/1.0)",
        "Accept": "application/json",
    }
)

DEFAULT_START = date(2000, 1, 1)
DEFAULT_END = date.today()
CHUNK_DAYS = 365          # query window per currency request
RETRY_ATTEMPTS = 5
RETRY_BACKOFF = 2.0       # seconds (doubles on each retry)
REQUEST_DELAY = 0.3       # polite delay between requests (seconds)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

_ODATA_SAFE = "@$,'"

def _build_url(base: str, params: dict) -> str:
    """Build URL keeping OData special chars ($, @, ') unencoded."""
    qs = "&".join(
        f"{k}={urllib.parse.quote(str(v), safe=_ODATA_SAFE)}"
        for k, v in params.items()
    )
    return f"{base}?{qs}"


def _get(url: str, params: dict | None = None) -> dict:
    """GET with retry + exponential back-off."""
    full_url = _build_url(url, params) if params else url
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = SESSION.get(full_url, timeout=30)
            if resp.status_code == 429:
                wait = RETRY_BACKOFF ** attempt
                log.warning("Rate-limited – sleeping %.0fs", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt == RETRY_ATTEMPTS:
                raise
            wait = RETRY_BACKOFF ** attempt
            log.warning("Request failed (%s) – retry %d/%d in %.0fs", exc, attempt, RETRY_ATTEMPTS, wait)
            time.sleep(wait)
    raise RuntimeError("Exhausted retries")  # unreachable, but satisfies type checkers


def fetch_currencies() -> pd.DataFrame:
    """
    Return DataFrame with columns: tipoMoeda, nomeFormatado, simbolo.

    tipoMoeda == "A"  →  USD-parity  (rate = USD per 1 unit of foreign currency)
    tipoMoeda == "B"  →  BRL-parity  (rate = BRL per 1 unit of foreign currency)
    """
    log.info("Fetching available currencies …")
    data = _get(f"{BASE_URL}/Moedas", params={"$format": "json"})
    df = pd.DataFrame(data["value"])
    a_count = (df["tipoMoeda"] == "A").sum()
    b_count = (df["tipoMoeda"] == "B").sum()
    log.info(
        "  → %d currencies found: %d type-A (USD parity), %d type-B (BRL parity)",
        len(df), a_count, b_count,
    )
    return df


def list_currencies(df: pd.DataFrame) -> None:
    """Print a formatted table of all available currencies grouped by parity type."""
    for parity, label in [("A", "USD parity"), ("B", "BRL parity")]:
        subset = df[df["tipoMoeda"] == parity].sort_values("simbolo")
        print(f"\nType {parity} – {label} ({len(subset)} currencies)")
        print(f"  {'Code':<8} {'Name'}")
        print(f"  {'-'*6}  {'-'*40}")
        for _, row in subset.iterrows():
            print(f"  {row['simbolo']:<8} {row['nomeFormatado']}")


def fetch_currency_period(currency: str, start: date, end: date) -> pd.DataFrame:
    """
    Fetch closing rates for one currency over [start, end].

    Returns DataFrame with columns:
        date, currency, cotacaoCompra, cotacaoVenda, boletim
    """
    url = (
        f"{BASE_URL}/CotacaoMoedaPeriodo"
        f"(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
    )
    params = {
        "@moeda": f"'{currency}'",
        "@dataInicial": f"'{start.strftime('%m-%d-%Y')}'",
        "@dataFinalCotacao": f"'{end.strftime('%m-%d-%Y')}'",
        "$format": "json",
        "$select": "cotacaoCompra,cotacaoVenda,dataHoraCotacao,tipoBoletim",
    }
    data = _get(url, params=params)
    rows = data.get("value", [])
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["currency"] = currency
    df["date"] = pd.to_datetime(df["dataHoraCotacao"]).dt.date
    df = df.rename(
        columns={
            "cotacaoCompra": "buy_rate",
            "cotacaoVenda": "sell_rate",
            "tipoBoletim": "bulletin",
        }
    )
    df = df[["date", "currency", "buy_rate", "sell_rate", "bulletin"]]
    return df


# ---------------------------------------------------------------------------
# Dataset builder
# ---------------------------------------------------------------------------

def build_dataset(
    start: date,
    end: date,
    currencies: list[str] | None,
    closing_only: bool = True,
    parity: str = "A",
) -> pd.DataFrame:
    """
    Download FX rates for all (or selected) currencies between start and end.

    Parameters
    ----------
    parity : "A" | "B" | "AB"
        Which BCB currency parity types to include.
        "A"  (default) – USD-parity currencies only (rate = USD per foreign unit).
        "B"            – BRL-parity currencies only (rate = BRL per foreign unit).
        "AB"           – All currencies regardless of parity type.

    BCB publishes up to 5 bulletins per day (Abertura, Intermediário, Fechamento, …).
    With closing_only=True (default) only the 'Fechamento' (closing) bulletin is kept,
    giving one row per currency per trading day.
    """
    avail = fetch_currencies()

    # Filter by parity type so the dataset is internally consistent
    parity = parity.upper()
    if parity == "AB":
        avail_filtered = avail
    elif parity in ("A", "B"):
        avail_filtered = avail[avail["tipoMoeda"] == parity]
        log.info(
            "Parity filter '%s': %d of %d currencies selected",
            parity, len(avail_filtered), len(avail),
        )
    else:
        raise ValueError(f"parity must be 'A', 'B', or 'AB'; got {parity!r}")

    if currencies:
        # validate against the parity-filtered set
        unknown = set(currencies) - set(avail_filtered["simbolo"])
        if unknown:
            log.warning(
                "Currency codes not in parity-%s set (will be skipped): %s",
                parity, ", ".join(sorted(unknown)),
            )
        target = [c for c in currencies if c in set(avail_filtered["simbolo"])]
    else:
        target = sorted(avail_filtered["simbolo"].tolist())

    log.info("Building dataset for %d currencies: %s … %s", len(target), start, end)

    frames: list[pd.DataFrame] = []
    total = len(target)

    for idx, currency in enumerate(target, 1):
        log.info("[%d/%d] %s", idx, total, currency)
        currency_frames: list[pd.DataFrame] = []

        # Chunk the date range to avoid overly-large responses
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS - 1), end)
            try:
                chunk = fetch_currency_period(currency, chunk_start, chunk_end)
                if not chunk.empty:
                    currency_frames.append(chunk)
            except Exception as exc:
                log.error("  Error fetching %s [%s – %s]: %s", currency, chunk_start, chunk_end, exc)
            chunk_start = chunk_end + timedelta(days=1)
            time.sleep(REQUEST_DELAY)

        if currency_frames:
            df_cur = pd.concat(currency_frames, ignore_index=True)
            if closing_only:
                # Keep only the closing bulletin; fall back to last bulletin of the day
                closing = df_cur[df_cur["bulletin"].str.upper() == "FECHAMENTO"]
                if not closing.empty:
                    df_cur = closing
                else:
                    df_cur = df_cur.groupby(["date", "currency"], as_index=False).last()
            frames.append(df_cur)

    if not frames:
        log.warning("No data retrieved.")
        return pd.DataFrame(columns=["date", "currency", "buy_rate", "sell_rate", "bulletin"])

    result = pd.concat(frames, ignore_index=True)
    result = result.drop_duplicates(subset=["date", "currency", "bulletin"])
    result = result.sort_values(["date", "currency"]).reset_index(drop=True)
    result["date"] = pd.to_datetime(result["date"])
    return result


# ---------------------------------------------------------------------------
# Pivot helpers
# ---------------------------------------------------------------------------

def pivot_wide(df: pd.DataFrame, rate: str = "sell_rate") -> pd.DataFrame:
    """
    Reshape to wide format: one column per currency, one row per date.
    `rate` can be 'sell_rate' or 'buy_rate'.
    """
    return (
        df.pivot_table(index="date", columns="currency", values=rate, aggfunc="last")
        .rename_axis(None, axis=1)
        .reset_index()
    )


def build_excel(
    start: date,
    end: date,
    output: Path,
    closing_only: bool = True,
) -> None:
    """
    Build an Excel workbook with two sheets:
      - 'USD Parity' (type-A currencies, wide format)
      - 'BRL Parity' (type-B currencies, wide format)
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    out_path = output.with_suffix(".xlsx")

    log.info("Building Excel workbook with USD + BRL parity tabs …")

    df_usd = build_dataset(start=start, end=end, currencies=None,
                           closing_only=closing_only, parity="A")
    df_brl = build_dataset(start=start, end=end, currencies=None,
                           closing_only=closing_only, parity="B")

    wide_usd = pivot_wide(df_usd) if not df_usd.empty else pd.DataFrame()
    wide_brl = pivot_wide(df_brl) if not df_brl.empty else pd.DataFrame()

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        if not wide_usd.empty:
            wide_usd.to_excel(writer, sheet_name="USD Parity", index=False)
            log.info("  USD Parity: %d rows × %d cols", len(wide_usd), len(wide_usd.columns))
        else:
            pd.DataFrame({"info": ["No USD-parity data found"]}).to_excel(
                writer, sheet_name="USD Parity", index=False)

        if not wide_brl.empty:
            wide_brl.to_excel(writer, sheet_name="BRL Parity", index=False)
            log.info("  BRL Parity: %d rows × %d cols", len(wide_brl), len(wide_brl.columns))
        else:
            pd.DataFrame({"info": ["No BRL-parity data found"]}).to_excel(
                writer, sheet_name="BRL Parity", index=False)

    log.info("Saved Excel → %s", out_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build a USD-parity FX rates dataset from BCB PTAX API.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--start",
        default=DEFAULT_START.isoformat(),
        help="Start date (YYYY-MM-DD)",
    )
    p.add_argument(
        "--end",
        default=DEFAULT_END.isoformat(),
        help="End date (YYYY-MM-DD)",
    )
    p.add_argument(
        "--output",
        default="data/fx_rates.csv",
        help="Output file path (.csv or .parquet)",
    )
    p.add_argument(
        "--format",
        choices=["csv", "parquet", "both", "excel"],
        default="csv",
        help="Output format. 'excel' produces an .xlsx with USD + BRL parity tabs.",
    )
    p.add_argument(
        "--currencies",
        nargs="+",
        metavar="CODE",
        default=None,
        help="Limit to specific currency codes (e.g. USD EUR GBP). Default: all.",
    )
    p.add_argument(
        "--wide",
        action="store_true",
        help="Also save a wide-format file (one column per currency).",
    )
    p.add_argument(
        "--all-bulletins",
        action="store_true",
        help="Keep all daily bulletins instead of closing only.",
    )
    p.add_argument(
        "--chunk-days",
        type=int,
        default=CHUNK_DAYS,
        help="Days per API request per currency.",
    )
    p.add_argument(
        "--parity",
        choices=["A", "B", "AB"],
        default="A",
        metavar="A|B|AB",
        help=(
            "Currency parity type to include. "
            "A=USD-parity (default), B=BRL-parity, AB=both."
        ),
    )
    p.add_argument(
        "--list-currencies",
        action="store_true",
        help="Print all available currencies grouped by parity type and exit.",
    )
    return p.parse_args()


def save(df: pd.DataFrame, path: Path, fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt in ("csv", "both"):
        out = path.with_suffix(".csv")
        df.to_csv(out, index=False)
        log.info("Saved CSV  → %s  (%d rows × %d cols)", out, len(df), len(df.columns))
    if fmt in ("parquet", "both"):
        out = path.with_suffix(".parquet")
        df.to_parquet(out, index=False)
        log.info("Saved Parquet → %s  (%d rows × %d cols)", out, len(df), len(df.columns))


def main() -> None:
    args = parse_args()

    if args.list_currencies:
        currencies_df = fetch_currencies()
        list_currencies(currencies_df)
        return

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    if start > end:
        sys.exit("--start must be before --end")

    global CHUNK_DAYS
    CHUNK_DAYS = args.chunk_days

    output = Path(args.output)

    if args.format == "excel":
        build_excel(
            start=start,
            end=end,
            output=output,
            closing_only=not args.all_bulletins,
        )
        log.info("Done.")
        return

    df = build_dataset(
        start=start,
        end=end,
        currencies=args.currencies,
        closing_only=not args.all_bulletins,
        parity=args.parity,
    )

    if df.empty:
        log.warning("Empty dataset – nothing saved.")
        return

    save(df, output, args.format)

    if args.wide:
        df_wide = pivot_wide(df)
        wide_path = output.parent / (output.stem + "_wide")
        save(df_wide, wide_path, args.format)

    log.info("Done. %d data points across %d currencies.", len(df), df["currency"].nunique())


if __name__ == "__main__":
    main()
