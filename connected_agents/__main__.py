"""python -m connected_agents --help"""
import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from .contracts import Provider, RehearsalError
from .runtime import auth_status, executable, login_command, provider_env, rehearse


def main() -> int:
    parser = argparse.ArgumentParser(description="Solutionist local AI connection rehearsal")
    parser.add_argument("action", choices=["check", "login", "status", "draft"])
    parser.add_argument("--provider", required=True, choices=[p.value for p in Provider])
    parser.add_argument("--state-dir", type=Path, required=True,
                        help="Private local directory for native provider sign-in; never commit it")
    parser.add_argument("--executable", help="Path to the provider's unmodified native executable")
    parser.add_argument("--timeout", type=int, choices=range(1, 301), default=180, metavar="1..300")
    args = parser.parse_args()
    provider = Provider(args.provider)
    try:
        binary = executable(provider, args.executable)
        if args.action == "check":
            # Version does not imply account access, capacity, or successful execution.
            result = subprocess.run([binary, "--version"], capture_output=True,
                                    text=True, timeout=15, check=True)
            print(json.dumps({"provider": provider.value, "installed": True,
                              "version": result.stdout.strip()[:120],
                              "connection_verified": False}))
        elif args.action == "status":
            print(json.dumps({"provider": provider.value,
                              **asyncio.run(auth_status(provider, args.state_dir, binary))}))
        elif args.action == "login":
            # Native interactive sign-in. We do not intercept credentials or tokens.
            with TemporaryDirectory(prefix="solutionist-login-") as work:
                return subprocess.call(login_command(provider, binary),
                                       env=provider_env(provider, args.state_dir), cwd=work)
        else:
            status = asyncio.run(auth_status(provider, args.state_dir, binary))
            if not status["authenticated"]:
                raise RehearsalError("login_required")
            result = asyncio.run(rehearse(provider, args.state_dir, binary, args.timeout,
                progress=lambda status: print(json.dumps({"status": status}), file=sys.stderr)))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except RehearsalError as exc:
        print(json.dumps({"provider": provider.value, "error": str(exc)}), file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError):
        print(json.dumps({"provider": provider.value, "error": "provider_unavailable"}), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled"}), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
