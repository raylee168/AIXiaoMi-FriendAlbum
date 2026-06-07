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
import httpx
from PIL import Image
from sqlalchemy import select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.core.config import get_settings
from app.channel_bridge import set_channel_sender
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


def test_cleanup_removes_expired_upload_files_but_keeps_metadata():
    db = SessionLocal()
    now = datetime.utcnow()
    base = Path(storage_root) / "uploads" / "u_cleanup" / "batch_cleanup"
    original = base / "original" / "expired.jpg"
    compressed = base / "compressed" / "expired.jpg"
    thumb = base / "thumbnails" / "expired.jpg"
    for path in [original, compressed, thumb]:
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (20, 20), (120, 120, 120)).save(path)
    db.add(
        PhotoFile(
            photo_id="expired_photo",
            user_id="u_cleanup",
            upload_batch_id="batch_cleanup",
            original_path=str(original),
            compressed_path=str(compressed),
            thumbnail_path=str(thumb),
            original_filename="expired.jpg",
            mime_type="image/jpeg",
            file_size=original.stat().st_size,
            width=20,
            height=20,
            uploaded_at=now - timedelta(hours=4),
            expire_at=now - timedelta(hours=1),
            preprocess_status="success",
            cleanup_status="pending",
        )
    )
    db.commit()
    db.close()

    cleanup = client.post("/internal/schedulers/cleanup").json()
    assert cleanup["expired_photos"]["processed"] >= 1
    assert not original.exists()
    assert not compressed.exists()
    assert not thumb.exists()

    db = SessionLocal()
    photo = db.scalars(select(PhotoFile).where(PhotoFile.photo_id == "expired_photo")).one()
    assert photo.cleanup_status == "cleaned"
    assert photo.cleaned_at is not None
    db.close()


def test_decision_skips_when_smart_generation_not_enabled(monkeypatch):
    monkeypatch.setenv("MOCK_ACCOUNT", "false")
    monkeypatch.setenv("ACCOUNT_SERVER_BASE_URL", "http://account.local")
    get_settings.cache_clear()

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"smart_generation_enabled": 0, "auto_charge_agreed": 0}

    def fake_get(self, url):
        return FakeResponse()

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    db = SessionLocal()
    now = datetime.utcnow()
    base = Path(storage_root) / "uploads" / "u_disabled" / "batch_disabled"
    for folder in ["original", "compressed", "thumbnails"]:
        (base / folder).mkdir(parents=True, exist_ok=True)
    for idx in range(6):
        photo_id = f"disabled_photo_{idx}"
        original = base / "original" / f"{photo_id}.jpg"
        compressed = base / "compressed" / f"{photo_id}.jpg"
        thumb = base / "thumbnails" / f"{photo_id}.jpg"
        Image.new("RGB", (30, 30), (120, 120, 120)).save(original)
        Image.new("RGB", (30, 30), (120, 120, 120)).save(compressed)
        Image.new("RGB", (30, 30), (120, 120, 120)).save(thumb)
        db.add(
            PhotoFile(
                photo_id=photo_id,
                user_id="u_disabled",
                upload_batch_id="batch_disabled",
                original_path=str(original),
                compressed_path=str(compressed),
                thumbnail_path=str(thumb),
                original_filename=f"{photo_id}.jpg",
                mime_type="image/jpeg",
                file_size=original.stat().st_size,
                width=30,
                height=30,
                uploaded_at=now,
                expire_at=now + timedelta(hours=3),
                preprocess_status="success",
                cleanup_status="pending",
            )
        )
    db.commit()
    db.close()

    response = client.post("/internal/schedulers/decision")
    assert response.status_code == 200
    assert response.json()["processed"] == 0

    db = SessionLocal()
    created = list(db.scalars(select(AlbumGenerationTask).where(AlbumGenerationTask.user_id == "u_disabled")))
    assert created == []
    db.close()
    monkeypatch.setenv("MOCK_ACCOUNT", "true")
    monkeypatch.delenv("ACCOUNT_SERVER_BASE_URL")
    get_settings.cache_clear()


def test_push_uses_cowagent_channel_message_id(monkeypatch):
    monkeypatch.setenv("COWAGENT_CHANNEL_BASE_URL", "http://cowagent.local")
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

    monkeypatch.setattr("app.services._send_via_cowagent_channel", lambda task: "cowagent_msg_001")
    response = client.post("/internal/schedulers/push")
    assert response.status_code == 200

    db = SessionLocal()
    pushed = db.query(AlbumPushTask).filter(AlbumPushTask.push_task_id == "push_agent").one()
    assert pushed.status == "success"
    assert pushed.message_id == "cowagent_msg_001"
    db.close()
    monkeypatch.setenv("MOCK_PUSH", "true")
    monkeypatch.delenv("COWAGENT_CHANNEL_BASE_URL")
    get_settings.cache_clear()


def test_push_does_not_resend_when_message_id_exists(monkeypatch):
    monkeypatch.setenv("COWAGENT_CHANNEL_BASE_URL", "http://cowagent.local")
    monkeypatch.setenv("MOCK_PUSH", "false")
    get_settings.cache_clear()

    db = SessionLocal()
    task_id = "gen_channel_retry"
    result_id = "result_channel_retry"
    now = datetime.utcnow()
    db.add(
        AlbumGenerationTask(
            generation_task_id=task_id,
            user_id="u_channel_retry",
            decision_job_id="decision_channel_retry",
            template_id="mvp_grid_001",
            album_index=1,
            photo_ids_json=["p_retry"],
            main_photo_id="p_retry",
            status="success",
            result_dir=str(Path(storage_root) / "results" / task_id),
            account_hold_id="hold_retry",
            actual_token_cost=12000,
        )
    )
    db.add(
        AlbumGenerationResult(
            result_id=result_id,
            generation_task_id=task_id,
            user_id="u_channel_retry",
            album_title="title",
            copy_text="copy",
            copy_options_json=[{"style": "daily", "text": "copy"}],
            image_path=str(Path(storage_root) / "retry.jpg"),
            thumbnail_path=str(Path(storage_root) / "retry_thumb.jpg"),
            width=1,
            height=1,
            file_size=1,
            expire_at=now + timedelta(hours=3),
        )
    )
    db.add(
        AlbumPushTask(
            push_task_id="push_channel_retry",
            user_id="u_channel_retry",
            generation_task_id=task_id,
            result_id=result_id,
            push_channel="mock",
            push_payload_json={"type": "album_result", "text": "copy"},
            status="pending",
            message_id="existing_msg_001",
        )
    )
    db.commit()
    db.close()

    def fail_if_called(task):
        raise AssertionError("channel should not resend")

    monkeypatch.setattr("app.services._send_via_cowagent_channel", fail_if_called)
    response = client.post("/internal/schedulers/push")
    assert response.status_code == 200

    db = SessionLocal()
    pushed = db.query(AlbumPushTask).filter(AlbumPushTask.push_task_id == "push_channel_retry").one()
    assert pushed.status == "success"
    assert pushed.message_id == "existing_msg_001"
    db.close()
    monkeypatch.setenv("MOCK_PUSH", "true")
    monkeypatch.delenv("COWAGENT_CHANNEL_BASE_URL")
    get_settings.cache_clear()


def test_push_uses_injected_cowagent_sender(monkeypatch):
    monkeypatch.setenv("MOCK_PUSH", "false")
    get_settings.cache_clear()
    sent = []

    def sender(payload):
        sent.append(payload)
        return "injected_msg_001"

    set_channel_sender(sender)
    db = SessionLocal()
    task_id = "gen_injected_channel"
    result_id = "result_injected_channel"
    now = datetime.utcnow()
    db.add(
        AlbumGenerationTask(
            generation_task_id=task_id,
            user_id="u_injected",
            decision_job_id="decision_injected",
            template_id="mvp_grid_001",
            album_index=1,
            photo_ids_json=["p_injected"],
            main_photo_id="p_injected",
            status="success",
            result_dir=str(Path(storage_root) / "results" / task_id),
            actual_token_cost=12000,
        )
    )
    db.add(
        AlbumGenerationResult(
            result_id=result_id,
            generation_task_id=task_id,
            user_id="u_injected",
            album_title="title",
            copy_text="copy",
            copy_options_json=[{"style": "daily", "text": "copy"}],
            image_path=str(Path(storage_root) / "injected.jpg"),
            thumbnail_path=str(Path(storage_root) / "injected_thumb.jpg"),
            width=1,
            height=1,
            file_size=1,
            expire_at=now + timedelta(hours=3),
        )
    )
    db.add(
        AlbumPushTask(
            push_task_id="push_injected",
            user_id="u_injected",
            generation_task_id=task_id,
            result_id=result_id,
            push_channel="mock",
            push_payload_json={"type": "album_result", "text": "copy"},
            status="pending",
        )
    )
    db.commit()
    db.close()

    response = client.post("/internal/schedulers/push")
    assert response.status_code == 200
    assert sent and sent[0]["user_id"] == "u_injected"

    db = SessionLocal()
    pushed = db.query(AlbumPushTask).filter(AlbumPushTask.push_task_id == "push_injected").one()
    assert pushed.status == "success"
    assert pushed.message_id == "injected_msg_001"
    db.close()
    set_channel_sender(None)
    monkeypatch.setenv("MOCK_PUSH", "true")
    get_settings.cache_clear()
