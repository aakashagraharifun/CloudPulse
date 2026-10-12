"""Write the synthetic CloudPulse billing dataset to a CSV file.

Usage (from the backend directory, with the virtualenv active):
    python -m scripts.generate_sample_data
    python -m scripts.generate_sample_data --end-date 2026-10-11 --days 120 --out data.csv

The output is SYNTHETIC data containing deliberately injected anomalies; see
app/services/ingestion/sample_data.py for exactly what is injected.
"""

import argparse
from datetime import date
from pathlib import Path

from app.services.ingestion.sample_data import default_end_date, generate_sample_csv

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "sample-data" / "synthetic_billing_90d.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--end-date", type=date.fromisoformat, default=None)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days must be at least 1")
    end = args.end_date or default_end_date()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(generate_sample_csv(end, args.days, args.seed), encoding="utf-8")
    print(f"Wrote {args.days} days ending {end.isoformat()} to {args.out}")


if __name__ == "__main__":
    main()
