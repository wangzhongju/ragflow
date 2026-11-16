"""Cell cache keys.

The key covers the column config, the dependency values, the model fingerprint,
the generation settings and the prompt resource hash. Changing any of them
misses the cache, which is what makes "edit one column, rerun one column" true.
"""

import hashlib
import json

from datafactory.engine.recipe import Column, dependencies_of


def cache_key(column: Column, dependency_values: dict, model_fingerprint: str, gen_conf: dict, prompt_hash: str) -> str:
    """A stable hash for one cell. Key order in the inputs does not matter."""
    payload = {
        "column": column.model_dump(),
        "deps": {name: dependency_values.get(name) for name in sorted(dependencies_of(column))},
        "model_fingerprint": model_fingerprint,
        "gen_conf": gen_conf,
        "prompt_hash": prompt_hash,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
