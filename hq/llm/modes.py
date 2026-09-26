"""All eight provider combinations plus Auto. Local AI is an invariant."""
from itertools import combinations
from typing import Any

from hq.llm.providers import CLOUD, REGISTRY


def mode_for(providers) -> str:
    selected = set(providers)
    return "local" + "".join("_" + p for p in CLOUD if p in selected)


MODES = {"auto": {"id": "auto", "label": "Recommended / Auto", "providers": ["local", *CLOUD]}}
for n in range(len(CLOUD) + 1):
    for combo in combinations(CLOUD, n):
        key = mode_for(combo)
        MODES[key] = {"id": key, "label": "Local AI Only" if not combo else
                      "Local AI + " + " + ".join(REGISTRY[p].label for p in combo),
                      "providers": ["local", *combo]}


def current(s: dict[str, Any]) -> str:
    value = s.get("ai_mode", "auto")
    return value if isinstance(value, str) and value in MODES else "local"


def enabled(s: dict[str, Any], provider: str) -> bool:
    if provider == "local":
        return True
    return (provider in MODES[current(s)]["providers"] and
            s.get(f"llm_{provider}_enabled", True) is not False)


def normalize_patch(values: dict[str, Any], before: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    switches = {f"llm_{p}_enabled" for p in CLOUD}
    if "ai_mode" in out:
        mode = out["ai_mode"]
        if mode not in MODES:
            raise ValueError("unknown AI mode")
        if mode != "auto":
            out.update({f"llm_{p}_enabled": p in MODES[mode]["providers"] for p in CLOUD})
        # Auto respects existing OFF switches; choosing Auto never authorizes a disabled provider.
        out["llm_local_enabled"] = True
    elif switches.intersection(out):
        merged = {**before, **out}
        out["ai_mode"] = mode_for(p for p in CLOUD if merged.get(f"llm_{p}_enabled", True) is not False)
    if "llm_local_enabled" in out:
        out["llm_local_enabled"] = True
    return out

