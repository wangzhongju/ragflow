"""Reserve model work before dispatch so retries cannot silently multiply cost."""

import json

from .source import FactoryError, canonical, digest
from .store import database


def invoke(ds, unit, kind, payload, config, operation, check):
    key = digest(canonical([unit, kind, payload]))
    reservation = len(payload.encode()) + config["output_tokens"] + 1024 if kind == "generate" else len(payload.encode()) + 1024
    with database(True) as db:
        check(db)
        prior = db.execute("SELECT * FROM invocation WHERE dataset=? AND id=?", (ds, key)).fetchone()
        if prior:
            if prior["state"] == "done":
                return json.loads(prior["result"])
            raise FactoryError("该调用未完成，已保留预算。请检查调用记录后创建新的作业。")
        spent = db.execute("SELECT count(*),coalesce(sum(reserved),0) FROM invocation WHERE dataset=?", (ds,)).fetchone()
        if spent[0] >= config["max_calls"] or spent[1] + reservation > config["token_budget"]:
            raise FactoryError("达到本作业调用次数或 token 预算上限")
        db.execute("INSERT INTO invocation VALUES(?,?,?,?,?,?,?,?)", (ds, key, kind, reservation, "pending", "", config["model_id"], canonical({"input_sha256": digest(payload)})))
    result = operation()
    with database(True) as db:
        check(db)
        db.execute("UPDATE invocation SET state='done',result=? WHERE dataset=? AND id=?", (canonical(result), ds, key))
    return result
