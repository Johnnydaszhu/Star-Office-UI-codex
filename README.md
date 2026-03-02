# Star Office UI (Codex Edition)

一个给 **Codex** 用的像素办公室看板：把 Codex 的工作状态实时可视化（谁在忙、是否在线、昨天做了什么）。

![Star Office UI 预览](docs/screenshots/office-preview-20260301.jpg)

## 快速开始

```bash
cd Star-Office-UI
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cp -n state.sample.json state.json
./backend/service.sh start
```

打开：`http://127.0.0.1:18791`

查看运行状态：

```bash
./backend/service.sh status
./backend/service.sh logs
```

停止服务：

```bash
./backend/service.sh stop
```

## Codex 状态监控

后端默认内置 Codex 自动监控（读取 `~/.codex`），并自动映射为办公室状态。

- 关闭自动监控：`STAR_OFFICE_AUTO_CODEX=0`
- 手动单次同步：

```bash
.venv/bin/python codex-state-watcher.py --once
```

## 状态映射

- `executing` / `writing` / `researching` / `syncing` -> 工作区
- `idle` -> 休息区
- `error` -> 故障区

## 常用命令

手动切主 Agent 状态：

```bash
.venv/bin/python set_state.py writing "正在处理任务"
.venv/bin/python set_state.py idle "待命中"
```

## 主要 API

- `GET /health`
- `GET /status`
- `POST /set_state`
- `GET /agents`
- `POST /join-agent`
- `POST /agent-push`
- `POST /leave-agent`
- `GET /yesterday-memo`

## 对外访问（可选）

```bash
cloudflared tunnel --url http://127.0.0.1:18791
```

## 项目结构

```text
star-office-ui/
  backend/
    app.py
    service.sh
    requirements.txt
  frontend/
    index.html
    join.html
    invite.html
  codex-state-watcher.py
  office-agent-push.py
  set_state.py
  state.sample.json
  join-keys.json
```

## 许可与资源说明

- **Code / Logic：MIT**（见 `LICENSE`）
- **Art Assets：非商用，仅学习/演示用途**

若你计划商用，请替换为你自己的原创美术资产。
