"""Seed demo datasets into the SQLite store.

Usage: pixi run seed [data_dir]
Parses all fixture forms from each demo dataset and inserts them.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pisa.config import load_config
from pisa.parser.markdown import parse_file
from pisa.store.db import get_connection, init_db, save_applicant


def main():
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(load_config().app.data_dir)

    if not data_dir.exists():
        print(f"Data directory not found: {data_dir}")
        sys.exit(1)

    config = load_config()
    conn = get_connection(Path(config.app.db_path))
    init_db(conn)

    datasets = sorted(p for p in data_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
    total = 0

    for dataset_dir in datasets:
        forms_dir = dataset_dir / "forms"
        if not forms_dir.exists():
            continue

        dataset_name = dataset_dir.name
        forms = sorted(forms_dir.glob("applicant_*.md"))

        print(f"\n{dataset_name}: {len(forms)} forms")
        for form_path in forms:
            record = parse_file(form_path)
            save_applicant(conn, record, dataset=dataset_name)
            print(f"  {record.display_name} ({record.applicant_id[:8]}...)")
            total += 1

    conn.close()
    print(f"\nSeeded {total} applicants from {len(datasets)} datasets into {config.app.db_path}")


if __name__ == "__main__":
    main()
