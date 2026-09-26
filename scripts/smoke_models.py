"""Phase-0 smoke test: load each complete MLX chat model, generate a short reply, record speed and peak memory.

Each model runs in its own subprocess so memory is fully released between models.
Usage: .venv/bin/python scripts/smoke_models.py [--out data/smoke/models.json]
"""
import json
import subprocess
import sys
import time
from pathlib import Path

MODELS = [
    "mlx-community/Qwen3-0.6B-4bit",
    "mlx-community/Qwen2.5-3B-Instruct-4bit",
    "mlx-community/Qwen3-4B-Instruct-2507-4bit",
    "mlx-community/Qwen2.5-7B-Instruct-4bit",
    "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-DWQ",
]

CHILD = r"""
import json, sys, time
import mlx.core as mx
from mlx_lm import load, stream_generate
repo = sys.argv[1]
t0 = time.time()
model, tok = load(repo)
load_s = time.time() - t0
msgs = [{"role": "user", "content": "In one sentence, what is item-based collaborative filtering?"}]
kwargs = {"enable_thinking": False} if "Qwen3" in repo else {}
prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False, **kwargs)
text, last = "", None
for r in stream_generate(model, tok, prompt, max_tokens=80):
    text += r.text
    last = r
print(json.dumps({
    "repo": repo, "load_s": round(load_s, 1),
    "gen_tps": round(last.generation_tps, 1), "prompt_tps": round(last.prompt_tps, 1),
    "peak_gb": round(mx.get_peak_memory() / 1e9, 2), "reply": text.strip()[:160],
}))
"""


def main():
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else Path("data/smoke/models.json")
    results = []
    for repo in MODELS:
        started = time.time()
        proc = subprocess.run([sys.executable, "-c", CHILD, repo], capture_output=True, text=True, timeout=900)
        line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            row = {"repo": repo, "error": (proc.stderr or proc.stdout)[-400:]}
        row["wall_s"] = round(time.time() - started, 1)
        results.append(row)
        print(json.dumps(row))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
