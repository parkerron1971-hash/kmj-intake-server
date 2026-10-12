"""lane_registry.py — which provider and model serve each lane (Layer Two seam).

Layer Two workstream D, 2026-10-11. chief_models already names the lanes and
their Claude defaults (`model_for(lane, plan)`, env CHIEF_MODEL_<LANE>). This
adds the one thing it could not express: a lane served by a provider other
than Anthropic, with Claude as the fallback. Moving a lane becomes a config
change, never a rebuild:

    CHIEF_PROVIDER_<LANE>=openai_compatible
    CHIEF_PROVIDER_MODEL_<LANE>=<the provider's model id>
    CHIEF_PROVIDER_URL_<LANE>=https://<host>/v1        (OpenAI-compatible root)
    CHIEF_PROVIDER_KEY_ENV_<LANE>=<NAME of the env var holding its key>

Unset = Anthropic, exactly as before. The model must have a row in
api_usage_logger.MODEL_PRICING_CENTS; an unknown one is priced high and
announced by the meter, never silently cheap.

CLIENT DATA. Every lane carries some business's data, so moving a lane sends
that data to a new company. A lane may only move to a host the privacy policy
names as a subprocessor:

    CHIEF_SUBPROCESSOR_HOSTS=api.example-provider.com,other.example   (a listed
                                                 host also covers its subdomains)

A host that is not listed, or a URL that is not https, keeps the lane on
Claude and says so on stdout. Listing a host is the record that the policy
covers it, so the policy changes first and the list second.

What this does NOT do: decide which lanes are ready to move. That is the
lane-graduation bench's job (workstream G), and Kevin's call. Chief's main
lanes depend on Anthropic-only features (prompt caching, thinking, native
tools); llm_call.post_lane keeps any call that uses them on Claude, whatever
the config says.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import urlparse

PROVIDERS = ("anthropic", "openai_compatible")


@dataclass(frozen=True)
class Route:
    lane: str
    provider: str
    model: str
    base_url: Optional[str] = None
    key_env: Optional[str] = None
    # The Claude model a non-Anthropic lane falls back to on any failure.
    fallback_model: Optional[str] = None

    @property
    def is_anthropic(self) -> bool:
        return self.provider == "anthropic"


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def subprocessor_hosts() -> Tuple[str, ...]:
    """The hosts the privacy policy names as AI subprocessors (env)."""
    raw = _env("CHIEF_SUBPROCESSOR_HOSTS")
    return tuple(h.strip().lower().strip(".") for h in raw.split(",") if h.strip().strip("."))


def listed_subprocessor(url: str) -> bool:
    """True when `url` is https and its host is a listed subprocessor, or a
    subdomain of one. `models.example` does not cover `evilmodels.example`."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host:
        return False
    return any(host == h or host.endswith("." + h) for h in subprocessor_hosts())


def route_for(lane: str, plan: Optional[str] = None) -> Route:
    """The route for a lane, read per call (a config change needs no
    restart). An incomplete non-Anthropic config falls back to Anthropic
    and says so on stdout, because a half-set lane must never fail closed."""
    import chief_models
    claude = chief_models.model_for(lane, plan)
    key = lane.upper()
    provider = _env(f"CHIEF_PROVIDER_{key}").lower() or "anthropic"
    if provider == "anthropic":
        return Route(lane=lane, provider="anthropic", model=claude)
    if provider not in PROVIDERS:
        print(f"[route] CHIEF_PROVIDER_{key}={provider!r} is not a known provider; "
              f"lane {lane} stays on {claude}", flush=True)
        return Route(lane=lane, provider="anthropic", model=claude)
    model = _env(f"CHIEF_PROVIDER_MODEL_{key}")
    base = _env(f"CHIEF_PROVIDER_URL_{key}").rstrip("/")
    key_env = _env(f"CHIEF_PROVIDER_KEY_ENV_{key}")
    missing = [n for n, v in (("MODEL", model), ("URL", base), ("KEY_ENV", key_env)) if not v]
    if missing or not _env(key_env):
        what = ", ".join(f"CHIEF_PROVIDER_{m}_{key}" for m in missing) or f"the key in {key_env}"
        print(f"[route] lane {lane} is set to {provider} but {what} is missing; "
              f"staying on {claude}", flush=True)
        return Route(lane=lane, provider="anthropic", model=claude)
    if not listed_subprocessor(base):
        print(f"[route] lane {lane} points at {base}, which is not an https host listed "
              f"in CHIEF_SUBPROCESSOR_HOSTS; client data stays on {claude}", flush=True)
        return Route(lane=lane, provider="anthropic", model=claude)
    return Route(lane=lane, provider=provider, model=model, base_url=base,
                 key_env=key_env, fallback_model=claude)


def describe() -> dict:
    """Every lane's current route, for the platform console and the docs."""
    import chief_models
    lanes = sorted(getattr(chief_models, "_LANE_DEFAULTS", {}).keys())
    out = {}
    for lane in lanes:
        r = route_for(lane)
        out[lane] = {"provider": r.provider, "model": r.model,
                     **({"fallback": r.fallback_model, "base_url": r.base_url}
                        if not r.is_anthropic else {})}
    return out
