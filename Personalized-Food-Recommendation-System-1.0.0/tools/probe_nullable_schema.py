"""Small counterexamples for relay schema preservation (explicit paid opt-in)."""

import argparse
import json

from probe_food_nutrition import ROOT, call, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to make three real relay calls")
    prompt = ('Return exactly this JSON, preserving null and all three array entries: '
              '{"missing":null,"items":[{"id":"A","value":null},{"id":"B","value":2},{"id":"C","value":null}]}')
    results = []
    for name in ["union_type", "anyof_type", "json_object_control"]:
        nullable = {"type": ["number", "null"]} if name != "anyof_type" else {"anyOf": [{"type": "number"}, {"type": "null"}]}
        schema = {"type": "object", "properties": {
            "missing": nullable, "items": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "value": nullable}, "required": ["id", "value"], "additionalProperties": False}}},
            "required": ["missing", "items"], "additionalProperties": False}
        override = {} if name == "json_object_control" else {"response_format": {"type": "json_schema", "json_schema": {
            "name": "nullable_counterexample", "strict": True, "schema": schema}}}
        result = call(prompt, overrides=override, timeout=35)
        result["case"] = name
        result["preserves_expected_json"] = result.get("json") == {"missing": None, "items": [
            {"id": "A", "value": None}, {"id": "B", "value": 2}, {"id": "C", "value": None}]}
        results.append(result)
        save(ROOT / "docs/food-nutrition-evaluation/2026-11-13/nullable-schema.json", results)
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
