# AIXiaoMi Friend Album

朋友圈智能相册 CowAgent 插件。

生产形态：把本仓库放到 `AIXiaoMi-Agent/plugins/moments_album`，由 CowAgent 加载。插件会复用 CowAgent 的通道能力，把相册图片和文案推送给用户。

当前仓库仍保留 `app.main` FastAPI 入口，只用于本地调试、接口联调和部署烟测；业务代码应继续保持插件可复用，不把相册逻辑写进 Agent 主流程。

## Install As CowAgent Plugin

```bash
cd AIXiaoMi-Agent/plugins
git clone https://github.com/raylee168/AIXiaoMi-FriendAlbum.git moments_album
pip install -r moments_album/requirements.txt
cd ..
python app.py
```

首次启动后，在 CowAgent 插件配置中启用 `moments_album`。

## Plugin Behavior

- 扫描 `core_album_db.plugin_events`。
- 执行照片预处理、智能判断、相册生成、推送、清理。
- 推送时优先使用 CowAgent 注入的通道发送能力。
- 如果 CowAgent 通道暂不可用，会写 fallback 日志，避免流水线中断。

## Standalone Debug Run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set DATABASE_URL=mysql+pymysql://user:password@host:3306/core_album_db?charset=utf8mb4
set STORAGE_ROOT=/data/smart-album
uvicorn app.main:app --host 0.0.0.0 --port 8003
```

## Scheduler Endpoints

- `POST /internal/schedulers/events`
- `POST /internal/schedulers/preprocess`
- `POST /internal/schedulers/decision`
- `POST /internal/schedulers/generation`
- `POST /internal/schedulers/push`
- `POST /internal/schedulers/cleanup`
- `POST /internal/schedulers/run-all`
