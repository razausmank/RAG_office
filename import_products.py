"""
import_products.py
-------------------
Loader that populates the `products` table from a raw ERP ICSP (product
master) CSV export.

Rows are keyed by (cono, prod), which is almost always unique — but a
handful of rows differ only by leading/trailing whitespace on `prod`
(e.g. "IV540701C" vs " IV540701C"), which collide once normalized. As with
the OEEH/OEEL exports, we keep only the highest-VariationId row per
normalized key.

Run standalone:

    python import_products.py path/to/icsp_export.csv

This does a full TRUNCATE + reload of `products`.
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
    ("company_no", "cono", _passthrough),
    ("product_code", "prod", _passthrough),
    ("lookup_name", "lookupnm", _passthrough),
    ("description_1", "descrip_1", _passthrough),
    ("description_2", "descrip_2", _passthrough),
    ("description_extended", "descrip3", _passthrough),
    ("category", "prodcat", _passthrough),
    ("product_type", "prodtype", _passthrough),
    ("status_code", "statustype", _passthrough),
    ("brand_code", "brandcode", _passthrough),
    ("manufacturer_product", "mfgprod", _passthrough),
    ("model_code", "modelcode", _passthrough),
    ("stocking_unit", "unitstock", _passthrough),
    ("selling_unit", "unitsell", _passthrough),
    ("counting_unit", "unitcnt", _passthrough),
    ("weight", "weight", _passthrough),
    ("height", "height", _passthrough),
    ("width", "width", _passthrough),
    ("length", "length", _passthrough),
    ("cubes", "cubes", _passthrough),
    ("country_of_origin", "countryoforigin", _passthrough),
    ("warranty_type", "warrtype", _passthrough),
    ("warranty_length", "warrlength", _passthrough),
    ("tariff_code", "tariffcd", _passthrough),
    ("unspsc", "unspsc", _passthrough),
    ("entered_date", "enterdt", _passthrough),
    ("last_change_date", "transdt", _passthrough),
    ("source_synced_at", "DCTransDate", _parse_flexible_datetime),
    ("erp_created_at", "_created", _parse_flexible_datetime),
    ("erp_modified_at", "_modified", _parse_flexible_datetime),
]

TABLE_COLUMNS = [table_col for table_col, _, _ in COLUMN_MAP]
CHUNK_SIZE = 50_000


def _dedupe_latest(csv_path: str) -> dict:
    """Keep only the highest-VariationId row per normalized (cono, prod)."""
    winners: dict[tuple[str, str], tuple[int, list]] = {}
    skipped = 0

    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        expected_cols = len(header)
        idx = {name: i for i, name in enumerate(header)}
        variation_idx = idx["VariationId"]
        key_idx = (idx["cono"], idx["prod"])
        source_idx = [idx[csv_col] for _, csv_col, _ in COLUMN_MAP]

        for row in reader:
            if len(row) != expected_cols:
                skipped += 1
                continue

            key = (row[key_idx[0]].strip(), row[key_idx[1]].strip())
            try:
                variation_id = int(row[variation_idx])
            except ValueError:
                variation_id = 0

            existing = winners.get(key)
            if existing is not None and existing[0] >= variation_id:
                continue

            winners[key] = (variation_id, [row[i] for i in source_idx])

    if skipped:
        print(f"  skipped {skipped:,} malformed row(s) (wrong column count).")

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


def import_products(csv_path: str) -> None:
    print(f"Reading {csv_path} and deduping by latest VariationId per (cono, prod)...")
    winners = _dedupe_latest(csv_path)
    print(f"Loaded {len(winners):,} distinct products.")

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            print("Truncating products table...")
            cur.execute("TRUNCATE TABLE products RESTART IDENTITY")

            copy_sql = (
                f"COPY products ({', '.join(TABLE_COLUMNS)}) "
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
        print("Usage: python import_products.py <path-to-icsp-export.csv>")
        sys.exit(1)
    import_products(sys.argv[1])
