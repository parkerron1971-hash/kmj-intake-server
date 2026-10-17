# __tests__/test_stream_relay_setup.py
#
# How the relay is deployed (stream_relay/): encrypted ingest only, on 443,
# with nothing else public (Codex R2); no public player or bucket (R7);
# both containers locked down, the media handled by a dedicated user, and
# SSH key-only (R8); deploy refuses unless it can see nobody is streaming
# (R10).

import importlib.util
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent / "stream_relay"
_spec = importlib.util.spec_from_file_location("busy_check", ROOT / "setup" / "busy_check.py")
busy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(busy)


def test_ingest_is_rtmps_only_and_everything_else_is_local():
    m = yaml.safe_load((ROOT / "mediamtx.yml").read_text())
    assert m["rtmpEncryption"] == "strict" and m["rtmpsAddress"] == ":443"
    assert m["rtmpServerKey"].startswith("/tls/") and m["rtmpServerCert"].startswith("/tls/")
    assert "rtmpAddress" not in m                       # no plain listener configured at all
    assert m["rtspAddress"].startswith("127.0.0.1:") and m["apiAddress"].startswith("127.0.0.1:")
    assert m["authMethod"] == "http" and m["authHTTPAddress"].startswith("http://127.0.0.1:")
    for off in ("hls", "webrtc", "srt", "metrics", "pprof", "playback"):
        assert m[off] is False
    assert m["paths"]["all_others"]["overridePublisher"] is True


def test_the_firewall_opens_ssh_443_and_80_only_and_ssh_takes_keys_only():
    c = yaml.safe_load((ROOT / "setup" / "cloud-init.yaml").read_text())
    allowed = [cmd for cmd in c["runcmd"] if isinstance(cmd, str) and cmd.startswith("ufw allow")]
    assert allowed == ["ufw allow OpenSSH", "ufw allow 80/tcp", "ufw allow 443/tcp"]
    assert c["ssh_pwauth"] is False
    sshd = [f for f in c["write_files"] if f["path"].startswith("/etc/ssh/")][0]["content"]
    assert "PasswordAuthentication no" in sshd and "PermitRootLogin prohibit-password" in sshd
    assert "chown 10001:10001 /var/relay" in c["runcmd"] and "certbot" in c["packages"]


def test_both_containers_are_locked_down():
    d = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    for name, s in d.items():
        assert s["read_only"] is True and s["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in s["security_opt"] and s["mem_limit"] and s["pids_limit"], name
    assert d["mediamtx"]["cap_add"] == ["NET_BIND_SERVICE"]
    assert d["agent"]["user"] == "10001:10001" and "cap_add" not in d["agent"]
    assert "./tls:/tls:ro" in d["mediamtx"]["volumes"]
    docker = (ROOT / "agent" / "Dockerfile").read_text()
    assert "USER 10001:10001" in docker and "player.html" not in docker


def test_there_is_no_public_player_or_bucket_address():
    assert not (ROOT / "player.html").exists()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "r2.dev" in readme and "CORS" in readme and "MEDIA_PUBLIC_BASE" not in readme
    env = (ROOT / ".env.example").read_text()
    assert "PRIVATE" in env and "MEDIA_PUBLIC_BASE" not in env


def test_deploy_goes_ahead_only_when_it_can_see_nobody_is_streaming():
    ok = {"ok": True, "recovered": True, "live": 0, "waiting": 0, "finishing": 0}
    assert busy.verdict(ok, 0) == "idle"
    assert busy.verdict({**ok, "live": 1}, 0) == "busy 1"
    assert busy.verdict({**ok, "waiting": 1}, 0) == "busy 1"            # a church waiting to reconnect
    assert busy.verdict(ok, 1) == "busy 1"                              # MediaMTX has a publisher the agent missed
    assert busy.verdict({**ok, "recovered": False}, 0).startswith("unknown")   # an agent that just restarted
    assert busy.verdict(ok, None).startswith("unknown")                 # MediaMTX didn't answer
    assert busy.verdict(None, 0).startswith("unknown")                  # no health at all (timeout)
    assert busy.verdict({"ok": True, "recovered": True}, 0).startswith("unknown")   # malformed
    deploy = (ROOT / "setup" / "deploy.sh").read_text()
    assert 'python3 - < setup/busy_check.py' in deploy and "idle) ;;" in deploy
