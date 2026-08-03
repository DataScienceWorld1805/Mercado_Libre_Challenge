"""End-to-end reproduction: synthetic data → features → train → metrics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.generate_synthetic import generate_orders, save_orders
from src.models.train import train_and_persist


def main() -> None:
    print("1) Generating synthetic orders...")
    orders = generate_orders(n_orders=12000, seed=42)
    full_path, sample_path = save_orders(
        orders,
        ROOT / "data" / "synthetic",
        ROOT / "data" / "sample",
        sample_n=500,
    )
    print(f"   Full:   {full_path} ({len(orders)} rows)")
    print(f"   Sample: {sample_path}")

    print("2) Training quantile models + evaluating...")
    result = train_and_persist(orders, ROOT / "artifacts")
    metrics = result["metrics"]

    print("3) Metrics (temporal holdout):")
    print(json.dumps(metrics, indent=2))
    print(f"\nArtifacts written to {ROOT / 'artifacts'}")
    print("Next: uvicorn src.api.main:app --reload --port 8000")


if __name__ == "__main__":
    main()
