"""Capture one fixed-ID USDA response; never load the application or its DB."""

import argparse
import json
from pathlib import Path
import re
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.fooddata_central_client import FoodDataCentralClient, FoodDataCentralClientError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("--live authorizes one USDA Detail request, without retries")
    if args.output.exists():
        parser.error("Use the existing capture; refusing a duplicate provider request")
    private_text = (ROOT / "USDA KEY.txt").read_text(encoding="utf-8-sig")
    keys = re.findall(r"(?<![A-Za-z0-9])[A-Za-z0-9]{40}(?![A-Za-z0-9])", private_text)
    if len(keys) != 1:
        raise ValueError("Expected exactly one USDA API key in the private key file")
    client = FoodDataCentralClient(keys[0])
    try:
        document = client.get_food("171688", deadline=time.monotonic() + 25)
    except FoodDataCentralClientError as error:
        print(json.dumps({"status": "failed", "code": error.code, "requests": 1}))
        return 1
    finally:
        client.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=True, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    payload = document["payload"]
    print(json.dumps({"status": "captured_not_admitted", "requests": 1,
                      "fdc_id": payload["fdcId"], "description": payload.get("description"),
                      "data_type": payload.get("dataType"), "retrieved_at": document["retrieved_at"],
                      "payload_sha256": document["content_hash"],
                      "nutrient_rows": len(payload.get("foodNutrients", []))}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
