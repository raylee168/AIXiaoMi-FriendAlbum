# AIXiaoMi Friend Album

朋友圈智能相册插件服务的独立仓库版本。第一版使用 Mock LLM、Mock 推送和 Mock 账号结算跑通完整流水线。

## Run

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
