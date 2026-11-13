"""Recover tracked sessions after preparation failed, without retrying an outage."""

import argparse
import csv
import json
from pathlib import Path

from remote_population_test import Log, now, records_match, save_json, session


def recover(out, source):
    # This recovery path is only for runs that never started business writes.
    originals = list(out.glob("load_requests_*.csv"))
    for path in originals:
        with path.open(encoding="utf-8-sig", newline="") as f:
            if any(r["step"] in ("temp_create", "temp_update", "temp_delete") for r in csv.DictReader(f)):
                raise RuntimeError("Business writes exist; use the full pending-record cleanup instead")
    population = json.loads((source/"population.json").read_text(encoding="utf-8"))
    accounts = {item["account"]: item for item in population["accounts"]}
    log = Log(out, "recovery_requests.csv")
    result = {"started_at": now(), "operation": "verify original seed records and logout tracked preparation tokens",
        "tokens_before": len(log.tokens), "checks": [], "completed": False, "pending_temporary_records": 0}
    try:
        with session() as client:
            ok,health,status,_ = log.call(client,"GET","/health",phase="recovery",step="recovery_health",
                validate=lambda d:isinstance(d,dict) and d.get("status")=="ok")
            result["health_status"] = status
            if not ok:
                result["reason"] = "Service unhealthy; no per-account verification or logout requests attempted"
                return result
            for account in list(log.tokens):
                item = accounts[account]
                client.headers["Authorization"] = "Bearer "+log.tokens[account]["token"]
                ok,data,status,_ = log.call(client,"GET",f"/records/{item['uid']}",account,
                    phase="recovery",step="recover_seed_verification",params={"limit":500},
                    validate=lambda d,a=item:records_match(d,a["records"]) and len(d["records"])==3)
                check = {"account":account,"seed_valid":ok,"logout_ok":False}
                result["checks"].append(check)
                if not ok:
                    result["reason"] = f"Verification failed with status {status}; recovery stopped"
                    break
                ok,_,status,_ = log.call(client,"POST","/auth/logout",account,phase="recovery",step="recover_logout")
                check["logout_ok"] = ok
                if not ok:
                    result["reason"] = f"Logout failed with status {status}; recovery stopped"
                    break
                with log.lock:
                    log.tokens.pop(account)
                    save_json(log.tokens_path,log.tokens)
                save_json(out/"recovery_summary.json",{**result,"outstanding_tokens":len(log.tokens)})
            result["completed"] = not log.tokens
        return result
    finally:
        result["finished_at"] = now()
        result["outstanding_tokens"] = len(log.tokens)
        save_json(out/"recovery_summary.json",result)
        log.close()
        print(json.dumps({k:v for k,v in result.items() if k!="checks"},ensure_ascii=True),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--source",type=Path,required=True)
    args=parser.parse_args()
    outcome=recover(args.out.resolve(),args.source.resolve())
    raise SystemExit(0 if outcome["completed"] else 2)
