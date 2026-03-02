#!/usr/bin/env python3
"""Watch Codex activity and write Star Office `state.json`."""

import argparse
import json
import os
import time
from datetime import datetime

DEFAULT_STATE = {
    "state": "idle",
    "detail": "Codex 待命中",
    "progress": 0,
    "updated_at": datetime.now().isoformat(),
}


def load_state(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return dict(DEFAULT_STATE)


def save_state(path, data):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def tail_text(path, max_bytes=32768):
    try:
        with open(path, "rb") as file:
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(max(0, size - max_bytes), os.SEEK_SET)
            return file.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def find_latest_file(root_dir, suffix):
    latest_path = None
    latest_mtime = 0.0
    if not root_dir or not os.path.exists(root_dir):
        return latest_path, latest_mtime

    for root, _, files in os.walk(root_dir):
        for filename in files:
            if not filename.endswith(suffix):
                continue
            file_path = os.path.join(root, filename)
            try:
                mtime = os.path.getmtime(file_path)
            except Exception:
                continue
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest_path = file_path
    return latest_path, latest_mtime


def extract_recent_prompt(codex_global_state_path):
    if not os.path.exists(codex_global_state_path):
        return ""
    try:
        with open(codex_global_state_path, "r", encoding="utf-8") as file:
            data = json.load(file)
        prompt_history = data.get("electron-persisted-atom-state", {}).get("prompt-history")
        if isinstance(prompt_history, list) and prompt_history:
            text = str(prompt_history[-1]).strip()
            if len(text) > 32:
                return text[:32] + "..."
            return text
    except Exception:
        pass
    return ""


def infer_codex_state(
    codex_home,
    active_seconds,
    warm_seconds,
    idle_seconds,
):
    codex_global_state_path = os.path.join(codex_home, ".codex-global-state.json")
    latest_session_file, latest_session_mtime = find_latest_file(
        os.path.join(codex_home, "sessions"),
        ".jsonl",
    )

    global_mtime = 0.0
    if os.path.exists(codex_global_state_path):
        try:
            global_mtime = os.path.getmtime(codex_global_state_path)
        except Exception:
            global_mtime = 0.0

    newest_ts = max(global_mtime, latest_session_mtime)
    if newest_ts <= 0:
        return None

    age = time.time() - newest_ts
    prompt_summary = extract_recent_prompt(codex_global_state_path)

    error_detected = False
    if latest_session_file:
        last_text = tail_text(latest_session_file).lower()
        error_keywords = [
            "\"type\":\"error\"",
            "\"status\":\"error\"",
            "\"exit_code\":1",
            "traceback",
            "exception",
            "command failed",
        ]
        error_detected = any(word in last_text for word in error_keywords)

    if error_detected and age <= max(300, warm_seconds):
        return {"state": "error", "detail": "Codex 最近出现错误，请检查终端输出"}
    if age <= active_seconds:
        detail = "Codex 正在处理任务"
        if prompt_summary:
            detail = f"Codex 正在处理：{prompt_summary}"
        return {"state": "executing", "detail": detail}
    if age <= warm_seconds:
        detail = "Codex 最近活跃"
        if prompt_summary:
            detail = f"Codex 最近活跃：{prompt_summary}"
        return {"state": "writing", "detail": detail}
    if age <= idle_seconds:
        return {"state": "researching", "detail": "Codex 近期活跃，当前可能在思考/等待"}
    return {"state": "idle", "detail": "Codex 待命中"}


def update_state_file(state_file, inferred_state, interval_seconds, verbose):
    current_state = load_state(state_file)

    next_state = dict(current_state)
    next_state["state"] = inferred_state["state"]
    next_state["detail"] = inferred_state["detail"]
    next_state["progress"] = 0
    next_state["ttl_seconds"] = max(60, interval_seconds * 4)
    next_state["updated_at"] = datetime.now().isoformat()
    next_state["source"] = "codex-local"

    changed = (
        current_state.get("state") != next_state.get("state")
        or current_state.get("detail") != next_state.get("detail")
    )
    if changed:
        save_state(state_file, next_state)
        if verbose:
            print(
                f"[updated] state={next_state['state']} detail={next_state['detail']}"
            )
    elif verbose:
        print(f"[no-change] state={next_state['state']}")


def main():
    root_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(
        description="Watch Codex activity and sync it into Star Office state.json",
    )
    parser.add_argument(
        "--state-file",
        default=os.path.join(root_dir, "state.json"),
        help="Target state.json path",
    )
    parser.add_argument(
        "--codex-home",
        default=os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex")),
        help="Codex home path",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Polling interval seconds (default: 10)",
    )
    parser.add_argument(
        "--active-seconds",
        type=int,
        default=45,
        help="<= this age means executing",
    )
    parser.add_argument(
        "--warm-seconds",
        type=int,
        default=300,
        help="<= this age means writing",
    )
    parser.add_argument(
        "--idle-seconds",
        type=int,
        default=1800,
        help="<= this age means researching, else idle",
    )
    parser.add_argument("--once", action="store_true", help="Run one sync then exit")
    parser.add_argument("--verbose", action="store_true", help="Print debug logs")
    args = parser.parse_args()

    if args.verbose:
        print(f"[config] state_file={args.state_file}")
        print(f"[config] codex_home={args.codex_home}")

    while True:
        inferred = infer_codex_state(
            codex_home=args.codex_home,
            active_seconds=args.active_seconds,
            warm_seconds=args.warm_seconds,
            idle_seconds=args.idle_seconds,
        )

        if inferred:
            update_state_file(
                state_file=args.state_file,
                inferred_state=inferred,
                interval_seconds=args.interval,
                verbose=args.verbose,
            )
        elif args.verbose:
            print("[warn] no codex activity file found, skip this round")

        if args.once:
            return
        time.sleep(max(1, args.interval))


if __name__ == "__main__":
    main()
