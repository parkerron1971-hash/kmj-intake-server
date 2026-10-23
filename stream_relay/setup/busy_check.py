"""Is anyone streaming on this relay? Run ON the droplet by deploy.sh
(`ssh host python3 - < busy_check.py`). Prints `idle`, `busy <n>` or
`unknown <why>`; deploy.sh deploys only on `idle` (Codex R10: a health
check that times out, or an agent that has only just restarted, is not
"nobody is live"). Standard library only."""
import json
import urllib.error
import urllib.request

AGENT = "http://127.0.0.1:9100/health"
MTX = "http://127.0.0.1:9997/v3/{kind}/list"


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.load(r)


def verdict(health, publishers):
    """health: the agent's /health JSON; publishers: how many MediaMTX lists
    as publishing (None when MediaMTX couldn't be asked)."""
    if not isinstance(health, dict) or health.get("ok") is not True:
        return "unknown health"
    if health.get("recovered") is not True:
        return "unknown agent-starting"
    if publishers is None:
        return "unknown mediamtx"
    try:
        busy = int(health["live"]) + int(health["waiting"]) + int(publishers)
    except (KeyError, TypeError, ValueError):
        return "unknown health"
    return "idle" if busy == 0 else f"busy {busy}"


def publishing():
    total = 0
    for kind in ("rtmpsconns", "rtmpconns"):
        try:
            items = get(MTX.format(kind=kind)).get("items") or []
        except urllib.error.HTTPError as e:
            if e.code == 404:          # that listener is switched off
                continue
            return None
        except Exception:
            return None
        total += sum(1 for i in items if i.get("state") == "publish")
    return total


def main():
    try:
        health = get(AGENT)
    except Exception as e:
        print("unknown " + type(e).__name__)
        return
    print(verdict(health, publishing()))


if __name__ == "__main__":
    main()
