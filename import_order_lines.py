"""
import_order_lines.py
----------------------
Loader that populates the `order_lines` table from a raw ERP OEEL
(order-entry line) CSV export — the product-line detail rows that belong to
each order in `orders` (see import_orders.py / OEEH export).

Like the OEEH export, this is a change-data-capture feed, so we keep only the
row with the highest VariationId per (orderno, ordersuf, lineno).

Run standalone:

    python import_order_lines.py path/to/oeel_export.csv

This does a full TRUNCATE + reload of `order_lines`. Orders referenced by a
line must already exist in `orders` (composite FK) — run import_orders.py
first if loading from scratch.
"""

import csv
import io
import sys
from dateutil import parser as dateutil_parser

import psycopg2

from database import DATABASE_URL


def _passthrough(value: str) -> str:
    return value.strip()


def _parse_flexible_datetime(value: str) -> str:
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
    ("line_number", "lineno", _passthrough),
    ("product_code", "shipprod", _passthrough),
    ("product_category", "prodcat", _passthrough),
    ("product_line", "prodline", _passthrough),
    ("unit", "unit", _passthrough),
    ("quantity_ordered", "qtyord", _passthrough),
    ("quantity_shipped", "qtyship", _passthrough),
    ("unit_price", "price", _passthrough),
    ("unit_cost", "prodcost", _passthrough),
    ("line_total", "netord", _passthrough),
    ("status_type", "statustype", _passthrough),
    ("transaction_type", "transtype", _passthrough),
    ("warehouse", "whse", _passthrough),
    ("sales_rep_in", "slsrepin", _passthrough),
    ("sales_territory", "salesterr", _passthrough),
    ("entered_date", "enterdt", _passthrough),
    ("promised_date", "promisedt", _passthrough),
    ("requested_ship_date", "reqshipdt", _passthrough),
    ("invoice_date", "invoicedt", _passthrough),
    ("cancel_date", "canceldt", _passthrough),
    ("source_synced_at", "DCTransDate", _parse_flexible_datetime),
    ("erp_created_at", "_created", _parse_flexible_datetime),
    ("erp_modified_at", "_modified", _parse_flexible_datetime),
]

TABLE_COLUMNS = [table_col for table_col, _, _ in COLUMN_MAP]
CHUNK_SIZE = 50_000


def _dedupe_latest(csv_path: str) -> dict:
    """Pass 1: keep only the highest-VariationId row per (orderno, ordersuf, lineno)."""
    winners: dict[tuple[str, str, str], tuple[int, list]] = {}

    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        variation_idx = idx["VariationId"]
        key_idx = (idx["orderno"], idx["ordersuf"], idx["lineno"])
        source_idx = [idx[csv_col] for _, csv_col, _ in COLUMN_MAP]

        for row in reader:
            key = (row[key_idx[0]], row[key_idx[1]], row[key_idx[2]])
            try:
                variation_id = int(row[variation_idx])
            except ValueError:
                variation_id = 0

            existing = winners.get(key)
            if existing is not None and existing[0] >= variation_id:
                continue

            winners[key] = (variation_id, [row[i] for i in source_idx])

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


def import_order_lines(csv_path: str) -> None:
    print(f"Reading {csv_path} and deduping by latest VariationId per line...")
    winners = _dedupe_latest(csv_path)
    print(f"Loaded {len(winners):,} distinct order lines.")

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            print("Truncating order_lines table...")
            cur.execute("TRUNCATE TABLE order_lines RESTART IDENTITY")

            copy_sql = (
                f"COPY order_lines ({', '.join(TABLE_COLUMNS)}) "
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
        print("Usage: python import_order_lines.py <path-to-oeel-export.csv>")
        sys.exit(1)
    import_order_lines(sys.argv[1])
