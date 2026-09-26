"""Pull a JSON value out of model text and validate it (CONTRACT_B §2).

MLX servers have no `response_format`, so models wrap JSON in prose, code fences or `<think>` blocks.
`extract_json` strips those and returns the first complete object/array; `validate` checks it against a JSON
schema; `repair_message` is the one follow-up turn the router sends when the first answer was invalid.
"""
from __future__ import annotations

import json
import re
from typing import Any

import jsonschema

THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
UNCLOSED_THINK = re.compile(r"^\s*<think>.*?(?=[{\[])", re.DOTALL | re.IGNORECASE)
FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


class JSONExtractError(ValueError):
    pass


def strip_think(text: str) -> str:
    text = THINK.sub("", text or "")
    return UNCLOSED_THINK.sub("", text).strip()


def _scan(text: str, start: int) -> int | None:
    """Index just past the JSON value starting at text[start] ('{' or '['), honouring strings/escapes."""
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def _loads_lenient(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    fixed = re.sub(r",\s*([}\]])", r"\1", raw)                      # trailing commas
    fixed = fixed.replace("“", '"').replace("”", '"')      # smart quotes around keys
    return json.loads(fixed)


def extract_json(text: str) -> Any:
    body = strip_think(text)
    candidates = [m.group(1) for m in FENCE.finditer(body)] + [body]
    last_error = "no JSON object or array found"
    for cand in candidates:
        for i, ch in enumerate(cand):
            if ch not in "{[":
                continue
            end = _scan(cand, i)
            if end is None:
                last_error = "unterminated JSON value"
                break
            try:
                return _loads_lenient(cand[i:end])
            except json.JSONDecodeError as exc:
                last_error = f"invalid JSON: {exc.msg} at char {exc.pos}"
                continue
    raise JSONExtractError(last_error)


def validate(value: Any, schema: dict[str, Any] | None) -> list[str]:
    if not schema:
        return []
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
            for e in sorted(validator.iter_errors(value), key=lambda e: list(e.absolute_path))][:8]


def parse_and_validate(text: str, schema: dict[str, Any] | None) -> tuple[Any | None, list[str]]:
    try:
        value = extract_json(text)
    except JSONExtractError as exc:
        return None, [str(exc)]
    return value, validate(value, schema)


def repair_message(errors: list[str], schema: dict[str, Any] | None) -> str:
    detail = "; ".join(errors[:5])
    shape = f"\nThe schema is:\n{json.dumps(schema)}" if schema else ""
    return (f"Your previous output was invalid: {detail}. Return only valid JSON matching the schema, with no "
            f"prose, no code fences and no <think> block.{shape}")
