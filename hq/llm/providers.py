"""Provider metadata shared by policy and the control panel; no network access."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    execution: str
    strengths: tuple[str, ...]
    billing: str


REGISTRY = {
    "local": Provider("local", "Local AI", "local", ("filter", "parse", "classify", "rank", "store"),
                      "No API charge; uses this Mac's resources"),
    "claude": Provider("claude", "Claude CLI", "cloud", ("reasoning", "writing", "planning", "review"),
                       "CLI account limits apply; displayed dollar amounts are estimates"),
    "codex": Provider("codex", "ChatGPT / Codex CLI", "cloud", ("coding", "debugging", "automation"),
                      "CLI account limits apply; displayed dollar amounts are estimates"),
    "xai": Provider("xai", "Grok API", "cloud", ("external_reasoning",), "Metered API usage"),
}
CLOUD = tuple(p for p in REGISTRY if p != "local")

