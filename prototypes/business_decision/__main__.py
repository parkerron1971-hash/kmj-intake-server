"""Run with python -m prototypes.business_decision --help from the repo root."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
MODEL = BASE / "artifacts" / "model.json"


def main():
    parser = argparse.ArgumentParser(description="Local business decision prototype. No paid API calls.")
    parser.add_argument("command", choices=("train", "demo", "predict", "evaluate", "benchmark", "serve"))
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--message")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--iterations", type=int, default=10000)
    parser.add_argument("--http-requests", type=int, default=500)
    args = parser.parse_args()
    from .evaluate import load_engine, run_evaluation, train_and_select, write_report
    from .engine import demo_context

    if args.command == "train":
        result = train_and_select(args.model)
    elif args.command == "evaluate":
        result = run_evaluation(args.model)
    elif args.command == "benchmark":
        from .benchmark import run_benchmark
        result = run_benchmark(args.model, args.iterations, args.http_requests)
    else:
        engine = load_engine(args.model)
        if args.command == "serve":
            from .server import make_server
            server = make_server(engine, args.port)
            print(f"Fictional local demo: http://127.0.0.1:{args.port}/health (POST /decide)", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return
        if args.command == "predict":
            if not args.message:
                parser.error("predict requires --message")
            result = engine.decide(args.message, business_id="demo-salon", context=demo_context())
        else:
            result = [engine.decide(message, business_id="demo-salon", context=demo_context()) for message in (
                "What are your opening hours?", "Can I move my appointment to Friday?",
                "Cancel my appointment but refund the deposit too", "Write me a poem about space")]
    if args.out:
        write_report(result, args.out)
        if isinstance(result, dict):
            brief = {k: v for k, v in result.items() if k not in ("validation", "model", "rules_baseline")}
            for key in ("validation", "model", "rules_baseline"):
                if key in result:
                    brief[key] = {k: v for k, v in result[key].items() if k not in ("results", "failures")}
            result = brief
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
