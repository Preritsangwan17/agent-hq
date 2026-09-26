"""JSON that never fails on odd numbers: NaN / ±Infinity (e.g. from a pay parse or a division) become null.

Starlette's JSONResponse refuses non-finite floats with a 500, and the browser's JSON.parse rejects `Infinity`
in SSE payloads, so one bad value in one row used to blank the whole dashboard."""
from __future__ import annotations

import json
import math
from typing import Any

from fastapi.responses import JSONResponse


def clean(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def dumps(value: Any) -> str:
    return json.dumps(clean(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=str)


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return dumps(content).encode("utf-8")
