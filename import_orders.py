"""
import_orders.py
-----------------
One-off / re-runnable loader that populates the `orders` table from a raw
ERP OEEH (order-entry-header) CSV export.

The export is a change-data-capture feed: the same (orderno, ordersuf) can
appear multiple times across snapshots taken at different times. For each
order we keep only the row with the highest VariationId (the ERP's
monotonically increasing CDC version marker), i.e. the latest known state.

Run standalone (not on every app startup, since this loads 800k+ rows):

    python import_orders.py path/to/export.csv

Usage note: this does a full TRUNCATE + reload of `orders`, so it's meant
for (re)seeding, not incremental sync.
"""

import csv
import io
import re
import sys
from dateutil import parser as dateutil_parser

import psycopg2

from database import DATABASE_URL

# ---------------------------------------------------------------------------
# CSV column -> table column mapping
# Each entry is (csv_column_name, transform_fn). transform_fn takes the raw
# string value and returns the string to write into the COPY buffer ('' = NULL).
# ---------------------------------------------------------------------------
_INT_LIKE_FLOAT = re.compile(r"^\d+\.0+$")


def _passthrough(value: str) -> str:
    return value.strip()


def _clean_int_like(value: str) -> str:
    """Progress OpenEdge exports some integer codes as floats, e.g. '39026.00000'."""
    value = value.strip()
    return value.split(".", 1)[0] if _INT_LIKE_FLOAT.match(value) else value


def _parse_flexible_datetime(value: str) -> str:
    """DCTransDate/_created/_modified mix 'M/D/YYYY h:mm:ss AM' and ISO formats."""
    value = value.strip()
    if not value:
        return ""
    try:
        return dateutil_parser.parse(value).isoformat(sep=" ")
    except (ValueError, OverflowError):
        return ""


COLUMN_MAP: list[tuple[str, str, callable]] = [
    # (table_column, csv_column, transform)
    ("row_pointer", "rowpointer", _passthrough),
    ("order_number", "orderno", _passthrough),
    ("order_suffix", "ordersuf", _passthrough),
    ("customer_no", "custno", _clean_int_like),
    ("customer_po", "custpo", _passthrough),
    ("ship_to_no", "shipto", _passthrough),
    ("customer_name", "shiptonm", _passthrough),
    ("contact_name", "contactnm", _passthrough),
    ("email", "email", _passthrough),
    ("address_line1", "shiptoaddr_1", _passthrough),
    ("address_line2", "shiptoaddr_2", _passthrough),
    ("address_line3", "shiptoaddr3", _passthrough),
    ("city", "shiptocity", _passthrough),
    ("state", "shiptost", _passthrough),
    ("postal_code", "shiptozip", _passthrough),
    ("country", "countrycd", _passthrough),
    ("status_code", "orderdisp", _passthrough),
    ("backorder_stage", "bostage", _passthrough),
    ("transaction_type", "transtype", _passthrough),
    ("order_source", "ordersource", _passthrough),
    ("entered_date", "enterdt", _passthrough),
    ("promised_date", "promisedt", _passthrough),
    ("requested_ship_date", "reqshipdt", _passthrough),
    ("ship_date", "shipdt", _passthrough),
    ("invoice_date", "invoicedt", _passthrough),
    ("cancel_date", "canceldt", _passthrough),
    ("total_order_amount", "totordamt", _passthrough),
    ("total_line_amount", "totlineamt", _passthrough),
    ("total_invoice_amount", "totinvamt", _passthrough),
    ("total_qty_ordered", "totqtyord", _passthrough),
    ("total_qty_shipped", "totqtyshp", _passthrough),
    ("ship_via", "shipviaty", _passthrough),
    ("warehouse", "whse", _passthrough),
    ("taken_by", "takenby", _passthrough),
    ("sales_rep_in", "slsrepin", _passthrough),
    ("terms_type", "termstype", _passthrough),
    ("source_synced_at", "DCTransDate", _parse_flexible_datetime),
    ("erp_created_at", "_created", _parse_flexible_datetime),
    ("erp_modified_at", "_modified", _parse_flexible_datetime),
]

TABLE_COLUMNS = [table_col for table_col, _, _ in COLUMN_MAP]
CHUNK_SIZE = 50_000


def _dedupe_latest(csv_path: str) -> dict:
    """Pass 1: keep only the highest-VariationId row per (orderno, ordersuf)."""
    winners: dict[tuple[str, str], tuple[int, list]] = {}

    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        variation_idx = idx["VariationId"]
        key_idx = (idx["orderno"], idx["ordersuf"])
        source_idx = [idx[csv_col] for _, csv_col, _ in COLUMN_MAP]

        for n, row in enumerate(reader, start=1):
            key = (row[key_idx[0]], row[key_idx[1]])
            try:
                variation_id = int(row[variation_idx])
            except ValueError:
                variation_id = 0

            existing = winners.get(key)
            if existing is not None and existing[0] >= variation_id:
                continue

            winners[key] = (variation_id, [row[i] for i in source_idx])

            if n % 200_000 == 0:
                print(f"  scanned {n:,} rows...")

    return winners


def _to_copy_buffer(rows: list[list[str]]) -> io.StringIO:
    buf = io.StringIO()
    writer = csv.writer(buf)
    for raw_values in rows:
        transformed = [
            transform(value) for (_, _, transform), value in zip(COLUMN_MAP, raw_values)
        ]
        writer.writerow(transformed)
    buf.seek(0)
    return buf


def import_orders(csv_path: str) -> None:
    print(f"Reading {csv_path} and deduping by latest VariationId per order...")
    winners = _dedupe_latest(csv_path)
    print(f"Loaded {len(winners):,} distinct orders.")

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            # order_lines has a composite FK into orders, so both must be
            # truncated together (Postgres refuses to truncate a table that's
            # FK-referenced unless the referencing table is truncated too).
            # Re-run import_order_lines.py afterward to reload line items.
            print("Truncating orders (and dependent order_lines) table...")
            cur.execute("TRUNCATE TABLE orders, order_lines RESTART IDENTITY")

            copy_sql = (
                f"COPY orders ({', '.join(TABLE_COLUMNS)}) "
                "FROM STDIN WITH (FORMAT CSV, NULL '')"
            )

            all_rows = list(winners.values())
            for start in range(0, len(all_rows), CHUNK_SIZE):
                chunk = [raw for _, raw in all_rows[start : start + CHUNK_SIZE]]
                buf = _to_copy_buffer(chunk)
                cur.copy_expert(copy_sql, buf)
                print(f"  loaded {min(start + CHUNK_SIZE, len(all_rows)):,} / {len(all_rows):,}")

        conn.commit()
        print("Import complete.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python import_orders.py <path-to-oeeh-export.csv>")
        sys.exit(1)
    import_orders(sys.argv[1])
