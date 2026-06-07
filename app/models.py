from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

IdType = BigInteger().with_variant(Integer, "sqlite")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PhotoFile(Base, TimestampMixin):
    __tablename__ = "photo_files"

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    photo_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    upload_batch_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    original_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    compressed_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    thumbnail_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    renamed_filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    expire_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    preprocess_status: Mapped[str] = mapped_column(String(32), default="pending", index=True, nullable=False)
    smart_reject_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    smart_reject_status: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    used_in_generation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cleanup_status: Mapped[str] = mapped_column(String(32), default="pending", index=True, nullable=False)
    cleaned_at: Mapped[datetime | None] = mapped_column(DateTime)


class PluginEvent(Base, TimestampMixin):
    __tablename__ = "plugin_events"

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    source_server: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retry: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    next_run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)


class PhotoPreprocessResult(Base, TimestampMixin):
    __tablename__ = "photo_preprocess_results"

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    photo_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime)
    quality_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    sharpness_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    brightness_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    colorfulness_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    is_blurry: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_duplicate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_of_photo_id: Mapped[str | None] = mapped_column(String(64))
    is_screenshot: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_document: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_qrcode: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_person: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    face_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    main_face_score: Mapped[float] = mapped_column(Numeric(5, 4), default=0, nullable=False)
    object_detection_json: Mapped[dict | None] = mapped_column(JSON)
    person_boxes_json: Mapped[dict | None] = mapped_column(JSON)
    face_boxes_json: Mapped[dict | None] = mapped_column(JSON)
    scene_tags_json: Mapped[list | None] = mapped_column(JSON)
    scene_candidates_json: Mapped[list | None] = mapped_column(JSON)
    mood_hint: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    dominant_colors_json: Mapped[list | None] = mapped_column(JSON)
    phash: Mapped[str | None] = mapped_column(String(128))
    preprocess_pipeline_version: Mapped[str] = mapped_column(String(32), default="mvp-local-cv-v1", nullable=False)
    local_cv_cost_tokens: Mapped[int] = mapped_column(BigInteger, default=100, nullable=False)
    system_reject_level: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    system_reject_reason: Mapped[str | None] = mapped_column(String(512))
    processed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AlbumDecisionJob(Base, TimestampMixin):
    __tablename__ = "album_decision_jobs"

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    decision_job_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    decision_window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    decision_window_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    since_last_album_at: Mapped[datetime | None] = mapped_column(DateTime)
    photo_count: Mapped[int] = mapped_column(Integer, nullable=False)
    usable_photo_count: Mapped[int] = mapped_column(Integer, nullable=False)
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    llm_stage: Mapped[str] = mapped_column(String(32), default="summary_only", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="success", index=True, nullable=False)
    decision_result: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), default=0, nullable=False)
    template_matches_json: Mapped[list | None] = mapped_column(JSON)
    suggested_album_count: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    created_generation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)


class AlbumDecisionJobPhoto(Base):
    __tablename__ = "album_decision_job_photos"

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    decision_job_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    photo_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    photo_role: Mapped[str] = mapped_column(String(32), nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(String(512))
    is_main_candidate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score: Mapped[float] = mapped_column(Numeric(5, 4), default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AlbumGenerationTask(Base, TimestampMixin):
    __tablename__ = "album_generation_tasks"
    __table_args__ = (UniqueConstraint("decision_job_id", "album_index", name="uq_generation_decision_album_index"),)

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    generation_task_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    decision_job_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    album_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True, nullable=False)
    photo_ids_json: Mapped[list] = mapped_column(JSON, nullable=False)
    main_photo_id: Mapped[str | None] = mapped_column(String(64))
    copy_style: Mapped[str] = mapped_column(String(64), default="daily", nullable=False)
    generation_params_json: Mapped[dict | None] = mapped_column(JSON)
    estimated_token_cost: Mapped[int] = mapped_column(BigInteger, default=220000, nullable=False)
    max_frozen_tokens: Mapped[int] = mapped_column(BigInteger, default=300000, nullable=False)
    frozen_token_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    actual_token_cost: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    account_hold_id: Mapped[str | None] = mapped_column(String(64))
    has_watermark: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    result_dir: Mapped[str | None] = mapped_column(String(1024))
    result_album_path: Mapped[str | None] = mapped_column(String(1024))
    result_copy_json: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retry: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)


class AlbumGenerationTaskPhoto(Base):
    __tablename__ = "album_generation_task_photos"

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    generation_task_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    photo_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    slot_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    crop_params_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AlbumGenerationResult(Base, TimestampMixin):
    __tablename__ = "album_generation_results"

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    result_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    generation_task_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    album_title: Mapped[str] = mapped_column(String(255), nullable=False)
    copy_text: Mapped[str] = mapped_column(Text, nullable=False)
    copy_options_json: Mapped[list | None] = mapped_column(JSON)
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    thumbnail_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    has_watermark: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    expire_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cleanup_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)


class AlbumCostItem(Base):
    __tablename__ = "album_cost_items"

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    generation_task_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    cost_type: Mapped[str] = mapped_column(String(64), nullable=False)
    cost_name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128))
    usage_json: Mapped[dict | None] = mapped_column(JSON)
    actual_cost_yuan: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    charged_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    visible_to_user: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AlbumPushTask(Base, TimestampMixin):
    __tablename__ = "album_push_tasks"

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    push_task_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    generation_task_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    result_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    push_channel: Mapped[str] = mapped_column(String(32), default="mock", nullable=False)
    push_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True, nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(128))
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retry: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)


class AlbumCleanupTask(Base, TimestampMixin):
    __tablename__ = "album_cleanup_tasks"

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    cleanup_task_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    generation_task_id: Mapped[str | None] = mapped_column(String(64), index=True)
    upload_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    cleanup_scope_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    expire_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True, nullable=False)
    cleaned_file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cleaned_at: Mapped[datetime | None] = mapped_column(DateTime)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retry: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class SchedulerRunLog(Base):
    __tablename__ = "scheduler_run_logs"

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    scheduler_name: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    scanned_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
