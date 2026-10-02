"""Agentcard.sh transport. Credentials stay server-side; no automatic write retries."""
import hashlib
import os
import re
import threading
import time
from urllib.parse import urlsplit, parse_qs

import httpx

BASE = "https://api.agentcard.sh"
_lock = threading.Lock()
_cached = {}


class AgentcardError(Exception):
    def __init__(self, message="The wallet provider could not complete the request. Check its status before retrying.", *, status=502, data=None):
        super().__init__(message)
        self.status = status
        self.data = data or {}


def mode():
    value = os.getenv("AGENTCARD_MODE", "sandbox")
    if value not in {"sandbox", "production"}:
        raise AgentcardError("Wallet mode is not configured.", status=503)
    return value


def configured():
    return all(os.getenv(k) for k in ("AGENTCARD_CLIENT_ID", "AGENTCARD_CLIENT_SECRET", "AGENTCARD_ENCRYPTION_KEY"))


def binding():
    return hashlib.sha256((mode() + ":" + os.environ.get("AGENTCARD_CLIENT_ID", "")).encode()).hexdigest()


def identifier(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(re.escape(prefix) + r"[A-Za-z0-9_-]{1,150}", value):
        raise AgentcardError("The provider returned an unsupported identifier.")
    return value


def safe_url(value, purpose):
    if not isinstance(value, str) or len(value) > 3000 or re.search(r"[\\\s\x00-\x1f]", value):
        return None
    try:
        u = urlsplit(value)
        if u.scheme != "https" or u.netloc != "vault.agentcard.sh" or u.fragment:
            return None
        args = parse_qs(u.query, strict_parsing=True)
        if purpose == "enroll" and u.path == "/v" and set(args) == {"vs"} and len(args["vs"]) == 1:
            return value
        if purpose == "approve" and u.path == "/authorize" and set(args) == {"id"} and len(args["id"]) == 1:
            identifier(args["id"][0], "cauth_")
            return value
    except (ValueError, AgentcardError):
        pass
    return None


def request(method, path, body=None, *, token=None, form=None, timeout=25):
    if not path.startswith("/") or path.startswith("//"):
        raise AgentcardError()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + token} if token else {},
                json=body, data=form)
        if len(response.content) > 2_000_000:
            raise AgentcardError()
        data = response.json()
        if not isinstance(data, dict):
            raise AgentcardError()
    except (httpx.HTTPError, ValueError):
        raise AgentcardError() from None
    if not 200 <= response.status_code < 300:
        # Never return provider prose or tokens in exception text.
        raise AgentcardError(status=response.status_code, data=data)
    return data


def org_token():
    key = binding() + hashlib.sha256(os.environ.get("AGENTCARD_CLIENT_SECRET", "").encode()).hexdigest()
    with _lock:
        if _cached.get("key") == key and _cached.get("until", 0) > time.time():
            return _cached["token"]
        data = request("POST", "/api/v2/oauth/token", form={"grant_type": "client_credentials",
            "client_id": os.environ.get("AGENTCARD_CLIENT_ID", ""),
            "client_secret": os.environ.get("AGENTCARD_CLIENT_SECRET", "")})
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise AgentcardError()
        info = request("GET", "/api/v2", token=token)
        if info.get("test_mode") is not (mode() == "sandbox"):
            raise AgentcardError("Wallet credentials do not match the configured mode.", status=503)
        expected = os.environ.get("AGENTCARD_ORGANIZATION_ID")
        if expected and info.get("organization_id") != expected:
            raise AgentcardError("Wallet organization does not match.", status=503)
        _cached.update(key=key, token=token, until=time.time() + min(int(data.get("expires_in", 3600)), 3600) - 60)
        return token


def call(method, path, body=None, **kwargs):
    return request(method, path, body, token=org_token(), **kwargs)
