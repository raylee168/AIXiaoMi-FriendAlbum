import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
storage_root = tempfile.mkdtemp(prefix="smart_album_plugin_")
os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
os.environ["STORAGE_ROOT"] = storage_root
os.environ["MOCK_ACCOUNT"] = "true"

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.core.config import get_settings
from app.models import AlbumCleanupTask, AlbumGenerationResult, AlbumGenerationTask, AlbumPushTask, PhotoFile, PluginEvent


Base.metadata.create_all(bind=engine)
client = TestClient(app)


def _seed_photos():
    db = SessionLocal()
    now = datetime.utcnow()
    base = Path(storage_root) / "uploads" / "u_album" / "batch_test"
    for folder in ["original", "compressed", "thumbnails"]:
        (base / folder).mkdir(parents=True, exist_ok=True)
    photo_ids = []
    for idx in range(6):
        photo_id = f"photo_{idx:03d}"
        photo_ids.append(photo_id)
        original = base / "original" / f"{photo_id}.jpg"
        compressed = base / "compressed" / f"{photo_id}.jpg"
        thumb = base / "thumbnails" / f"{photo_id}.jpg"
        img = Image.new("RGB", (900, 700), (80 + idx * 20, 120, 160))
        img.save(original)
        img.resize((600, 467)).save(compressed)
        img.resize((240, 186)).save(thumb)
        db.add(
            PhotoFile(
                photo_id=photo_id,
                user_id="u_album",
                upload_batch_id="batch_test",
                original_path=str(original),
                compressed_path=str(compressed),
                thumbnail_path=str(thumb),
                original_filename=f"{photo_id}.jpg",
                mime_type="image/jpeg",
                file_size=original.stat().st_size,
                width=900,
                height=700,
                uploaded_at=now,
                expire_at=now + timedelta(hours=3),
                preprocess_status="pending",
                cleanup_status="pending",
            )
        )
    db.add(
        PluginEvent(
            event_id="evt_batch_test",
            event_type="photo_uploaded",
            user_id="u_album",
            source_server="photo-upload-server",
            payload_json={"upload_batch_id": "batch_test", "photo_ids": photo_ids},
            status="pending",
            retry_count=0,
            max_retry=3,
            next_run_at=now,
        )
    )
    db.commit()
    db.close()


def test_full_mock_album_pipeline_and_cleanup():
    _seed_photos()
    response = client.post("/internal/schedulers/run-all")
    assert response.status_code == 200
    payload = response.json()
    assert payload["events"]["processed"] == 1
    assert payload["preprocess"]["processed"] == 6
    assert payload["decision"]["processed"] == 1
    assert payload["generation"]["processed"] == 2
    assert payload["push"]["processed"] == 2

    db = SessionLocal()
    results = list(db.scalars(select(AlbumGenerationResult)))
    pushes = list(db.scalars(select(AlbumPushTask)))
    assert len(results) == 2
    assert all(Path(result.image_path).exists() for result in results)
    assert all(push.status == "success" for push in pushes)

    cleanup_tasks = list(db.scalars(select(AlbumCleanupTask)))
    assert len(cleanup_tasks) == 2
    for task in cleanup_tasks:
        task.expire_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    db.close()

    cleanup = client.post("/internal/schedulers/cleanup").json()
    assert cleanup["processed"] == 2


def test_photo_reject_updates_only_specified_photos():
    db = SessionLocal()
    now = datetime.utcnow()
    for idx in range(3):
        db.add(
            PhotoFile(
                photo_id=f"reject_photo_{idx}",
                user_id="u_reject",
                upload_batch_id="reject_batch",
                original_path=str(Path(storage_root) / f"missing_{idx}.jpg"),
                compressed_path=str(Path(storage_root) / f"missing_{idx}.jpg"),
                thumbnail_path=str(Path(storage_root) / f"missing_{idx}.jpg"),
                original_filename=f"missing_{idx}.jpg",
                mime_type="image/jpeg",
                file_size=1,
                width=1,
                height=1,
                uploaded_at=now,
                expire_at=now + timedelta(hours=3),
                preprocess_status="success",
                cleanup_status="pending",
            )
        )
    db.commit()
    db.close()

    first = client.post(
        "/internal/photos/apply-rejects",
        json={"user_id": "u_reject", "reject_reasons": {"reject_photo_1": "模糊"}},
    ).json()
    assert first["updated"] == 1

    second = client.post(
        "/internal/photos/apply-rejects",
        json={"user_id": "u_reject", "reject_reasons": {"reject_photo_1": "仍然模糊"}},
    ).json()
    assert second["final_rejected"] == 1

    db = SessionLocal()
    photos = {p.photo_id: p for p in db.scalars(select(PhotoFile).where(PhotoFile.user_id == "u_reject"))}
    assert photos["reject_photo_0"].smart_reject_count == 0
    assert photos["reject_photo_1"].smart_reject_count == 2
    assert photos["reject_photo_1"].smart_reject_status == "rejected_final"
    assert photos["reject_photo_2"].smart_reject_count == 0
    db.close()


def test_push_uses_agent_message_id(monkeypatch):
    monkeypatch.setenv("AGENT_BASE_URL", "http://agent.local")
    monkeypatch.setenv("MOCK_PUSH", "false")
    get_settings.cache_clear()

    db = SessionLocal()
    task_id = "gen_agent_push"
    result_id = "result_agent_push"
    now = datetime.utcnow()
    db.add(
        AlbumGenerationTask(
            generation_task_id=task_id,
            user_id="u_agent",
            decision_job_id="decision_agent",
            template_id="mvp_grid_001",
            album_index=1,
            photo_ids_json=["p_agent"],
            main_photo_id="p_agent",
            status="success",
            result_dir=str(Path(storage_root) / "results" / task_id),
            actual_token_cost=12000,
        )
    )
    db.add(
        AlbumGenerationResult(
            result_id=result_id,
            generation_task_id=task_id,
            user_id="u_agent",
            album_title="title",
            copy_text="copy",
            copy_options_json=[{"style": "daily", "text": "copy"}],
            image_path=str(Path(storage_root) / "agent.jpg"),
            thumbnail_path=str(Path(storage_root) / "agent_thumb.jpg"),
            width=1,
            height=1,
            file_size=1,
            expire_at=now + timedelta(hours=3),
        )
    )
    db.add(
        AlbumPushTask(
            push_task_id="push_agent",
            user_id="u_agent",
            generation_task_id=task_id,
            result_id=result_id,
            push_channel="mock",
            push_payload_json={"type": "album_result", "text": "copy"},
            status="pending",
        )
    )
    db.commit()
    db.close()

    monkeypatch.setattr("app.services._send_via_agent", lambda task: "agent_msg_001")
    response = client.post("/internal/schedulers/push")
    assert response.status_code == 200

    db = SessionLocal()
    pushed = db.query(AlbumPushTask).filter(AlbumPushTask.push_task_id == "push_agent").one()
    assert pushed.status == "success"
    assert pushed.message_id == "agent_msg_001"
    db.close()
    monkeypatch.setenv("MOCK_PUSH", "true")
    get_settings.cache_clear()
