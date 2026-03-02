#!/usr/bin/env python3
"""
Star Office UI - Agent 状态主动推送脚本（Codex 友好版）

用法：
1. 填入 JOIN_KEY（从办公室管理员获得）
2. 填入 AGENT_NAME（在办公室里显示的名字）
3. 运行：python office-agent-push.py
4. 脚本会自动先 join，然后周期性 push 当前状态
"""

import json
import os
import sys
import time

# === 必填配置 ===
JOIN_KEY = ""   # 必填：你的 join key
AGENT_NAME = "" # 必填：在办公室显示的名字
OFFICE_URL = "https://office.example.com"

# === 推送配置 ===
PUSH_INTERVAL_SECONDS = int(os.environ.get("OFFICE_PUSH_INTERVAL", "15"))
JOIN_ENDPOINT = "/join-agent"
PUSH_ENDPOINT = "/agent-push"

# 状态源模式：
# - auto: 先读 state.json，再读 Codex 活跃度，再读本地 /status
# - state: 只读 state.json
# - codex: 只读 Codex 活跃度
# - http: 只读本地 /status
SOURCE_MODE = os.environ.get("OFFICE_SOURCE_MODE", "auto").strip().lower()

# 本地状态缓存（用于保存 join 后得到的 agentId）
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "office-agent-state.json")

# 本地状态文件候选（优先显式指定）
LOCAL_STATE_FILE = os.environ.get("OFFICE_LOCAL_STATE_FILE", "")
DEFAULT_STATE_CANDIDATES = [
    os.path.join(os.getcwd(), "state.json"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"),
]

# 本地 /status 可选鉴权
LOCAL_STATUS_TOKEN = os.environ.get("OFFICE_LOCAL_STATUS_TOKEN", "")
LOCAL_STATUS_URL = os.environ.get("OFFICE_LOCAL_STATUS_URL", "http://127.0.0.1:18791/status")

# Codex 活跃度探针配置
CODEX_HOME = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
CODEX_GLOBAL_STATE_FILE = os.path.join(CODEX_HOME, ".codex-global-state.json")
CODEX_ACTIVE_SECONDS = int(os.environ.get("OFFICE_CODEX_ACTIVE_SECONDS", "45"))
CODEX_WARM_SECONDS = int(os.environ.get("OFFICE_CODEX_WARM_SECONDS", "300"))
CODEX_IDLE_SECONDS = int(os.environ.get("OFFICE_CODEX_IDLE_SECONDS", "1800"))

VERBOSE = os.environ.get("OFFICE_VERBOSE", "0").strip().lower() in {"1", "true", "yes"}


def load_local_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "agentId": None,
        "joined": False,
        "joinKey": JOIN_KEY,
        "agentName": AGENT_NAME
    }


def save_local_state(data):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_state(state_name):
    s = (state_name or "").strip().lower()
    if s in {"writing", "researching", "executing", "syncing", "error", "idle"}:
        return s
    if s in {"working", "busy", "write"}:
        return "writing"
    if s in {"run", "running", "execute", "exec"}:
        return "executing"
    if s in {"research", "search"}:
        return "researching"
    if s in {"sync"}:
        return "syncing"
    return "idle"


def map_detail_to_state(detail, fallback_state="idle"):
    d = (detail or "").lower()
    if any(k in d for k in ["报错", "error", "bug", "异常", "报警"]):
        return "error"
    if any(k in d for k in ["同步", "sync", "备份"]):
        return "syncing"
    if any(k in d for k in ["调研", "research", "搜索", "查资料"]):
        return "researching"
    if any(k in d for k in ["执行", "run", "推进", "处理任务", "工作中", "writing"]):
        return "writing"
    if any(k in d for k in ["待命", "休息", "idle", "完成", "done"]):
        return "idle"
    return fallback_state


def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def tail_text(path, max_bytes=24576):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            seek_pos = max(0, size - max_bytes)
            f.seek(seek_pos, os.SEEK_SET)
            return f.read().decode("utf-8", errors="ignore")
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


def extract_recent_prompt():
    data = load_json_file(CODEX_GLOBAL_STATE_FILE)
    if not isinstance(data, dict):
        return ""
    prompt_history = data.get("electron-persisted-atom-state", {}).get("prompt-history")
    if isinstance(prompt_history, list) and prompt_history:
        prompt = str(prompt_history[-1]).strip()
        return prompt
    return ""


def infer_codex_status():
    session_file, session_mtime = find_latest_file(os.path.join(CODEX_HOME, "sessions"), ".jsonl")
    global_mtime = 0.0
    if os.path.exists(CODEX_GLOBAL_STATE_FILE):
        try:
            global_mtime = os.path.getmtime(CODEX_GLOBAL_STATE_FILE)
        except Exception:
            global_mtime = 0.0

    newest_ts = max(session_mtime, global_mtime)
    if newest_ts <= 0:
        return None

    now_ts = time.time()
    age = now_ts - newest_ts
    prompt = extract_recent_prompt()
    prompt_summary = ""
    if prompt:
        prompt_summary = prompt.replace("\n", " ").strip()
        if len(prompt_summary) > 32:
            prompt_summary = prompt_summary[:32] + "..."

    error_detected = False
    if session_file:
        tail = tail_text(session_file).lower()
        error_keywords = [
            "\"type\":\"error\"",
            "\"status\":\"error\"",
            "\"exit_code\":1",
            "traceback",
            "exception",
            "command failed"
        ]
        if any(k in tail for k in error_keywords):
            error_detected = True

    if error_detected and age <= max(300, CODEX_WARM_SECONDS):
        return {"state": "error", "detail": "Codex 最近出现错误，请检查终端输出"}
    if age <= CODEX_ACTIVE_SECONDS:
        detail = f"Codex 正在处理：{prompt_summary}" if prompt_summary else "Codex 正在处理任务"
        return {"state": "executing", "detail": detail}
    if age <= CODEX_WARM_SECONDS:
        detail = f"Codex 最近活跃：{prompt_summary}" if prompt_summary else "Codex 最近活跃"
        return {"state": "writing", "detail": detail}
    if age <= CODEX_IDLE_SECONDS:
        return {"state": "researching", "detail": "Codex 近期活跃，当前可能在思考/等待"}
    return {"state": "idle", "detail": "Codex 待命中"}


def fetch_status_from_files():
    candidate_files = []
    if LOCAL_STATE_FILE:
        candidate_files.append(LOCAL_STATE_FILE)
    for path in DEFAULT_STATE_CANDIDATES:
        if path not in candidate_files:
            candidate_files.append(path)

    for path in candidate_files:
        if not path or not os.path.exists(path):
            continue
        data = load_json_file(path)
        if not isinstance(data, dict):
            continue
        if ("state" not in data) and ("detail" not in data):
            continue

        state = normalize_state(data.get("state", "idle"))
        detail = data.get("detail", "") or ""
        state = map_detail_to_state(detail, fallback_state=state)
        if VERBOSE:
            print(f"[status-source:file] path={path} state={state} detail={detail[:60]}")
        return {"state": state, "detail": detail}
    return None


def fetch_status_from_http():
    try:
        import requests
        headers = {}
        if LOCAL_STATUS_TOKEN:
            headers["Authorization"] = f"Bearer {LOCAL_STATUS_TOKEN}"
        resp = requests.get(LOCAL_STATUS_URL, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            state = normalize_state(data.get("state", "idle"))
            detail = data.get("detail", "") or ""
            state = map_detail_to_state(detail, fallback_state=state)
            if VERBOSE:
                print(f"[status-source:http] url={LOCAL_STATUS_URL} state={state} detail={detail[:60]}")
            return {"state": state, "detail": detail}
        if resp.status_code == 401:
            return {"state": "idle", "detail": "本地/status需要鉴权（401），请设置 OFFICE_LOCAL_STATUS_TOKEN"}
    except Exception:
        pass
    return None


def fetch_local_status():
    mode = SOURCE_MODE if SOURCE_MODE in {"auto", "state", "codex", "http"} else "auto"

    if mode in {"auto", "state"}:
        data = fetch_status_from_files()
        if data:
            return data

    if mode in {"auto", "codex"}:
        data = infer_codex_status()
        if data:
            if VERBOSE:
                print(f"[status-source:codex] state={data['state']} detail={data['detail'][:60]}")
            return data

    if mode in {"auto", "http"}:
        data = fetch_status_from_http()
        if data:
            return data

    if VERBOSE:
        print("[status-source:fallback] state=idle detail=待命中")
    return {"state": "idle", "detail": "待命中"}


def do_join(local):
    import requests
    payload = {
        "name": local.get("agentName", AGENT_NAME),
        "joinKey": local.get("joinKey", JOIN_KEY),
        "state": "idle",
        "detail": "刚刚加入"
    }
    resp = requests.post(f"{OFFICE_URL}{JOIN_ENDPOINT}", json=payload, timeout=10)
    if resp.status_code in (200, 201):
        data = resp.json()
        if data.get("ok"):
            local["joined"] = True
            local["agentId"] = data.get("agentId")
            save_local_state(local)
            print(f"已加入办公室，agentId={local['agentId']}")
            return True
    print(f"加入失败：{resp.text}")
    return False


def do_push(local, status_data):
    import requests
    payload = {
        "agentId": local.get("agentId"),
        "joinKey": local.get("joinKey", JOIN_KEY),
        "state": status_data.get("state", "idle"),
        "detail": status_data.get("detail", ""),
        "name": local.get("agentName", AGENT_NAME)
    }
    resp = requests.post(f"{OFFICE_URL}{PUSH_ENDPOINT}", json=payload, timeout=10)
    if resp.status_code in (200, 201):
        data = resp.json()
        if data.get("ok"):
            area = data.get("area", "breakroom")
            print(f"状态已同步，当前区域={area}")
            return True

    if resp.status_code in (403, 404):
        try:
            msg = (resp.json() or {}).get("msg", "")
        except Exception:
            msg = resp.text
        print(f"访问拒绝或已移出房间（{resp.status_code}），停止推送：{msg}")
        local["joined"] = False
        local["agentId"] = None
        save_local_state(local)
        sys.exit(1)

    print(f"推送失败：{resp.text}")
    return False


def main():
    local = load_local_state()

    if not JOIN_KEY or not AGENT_NAME:
        print("请先在脚本开头填入 JOIN_KEY 和 AGENT_NAME")
        sys.exit(1)

    if not local.get("joined") or not local.get("agentId"):
        if not do_join(local):
            sys.exit(1)

    print(f"开始持续推送状态，间隔={PUSH_INTERVAL_SECONDS} 秒")
    print(f"状态源模式：{SOURCE_MODE}")
    print("状态逻辑：任务中->工作区；待命/完成->休息区；异常->bug区")

    try:
        while True:
            try:
                status_data = fetch_local_status()
                do_push(local, status_data)
            except Exception as exc:
                print(f"推送异常：{exc}")
            time.sleep(PUSH_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n停止推送")
        sys.exit(0)


if __name__ == "__main__":
    main()
