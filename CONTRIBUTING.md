# Contributing

Describe the problem or intended behavior in an issue, then make a focused change on a branch.
Include a concrete before/after example and the validation you ran in your pull request.

## Local checks

Run from the repository root with Python 3.11 or 3.12 on macOS (the primary supported host):

```bash
uv sync --frozen
uv run --frozen python -m pytest -q
cd web && npm ci && npm run build
```

Keep generated artifacts, caches, credentials and personal data out of commits. Dataset access and
trained results must be documented separately from software tests. Do not report synthetic test
metrics as real model performance. Keep setup commands and model limitations accurate when code changes.
