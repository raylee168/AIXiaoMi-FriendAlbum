from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import PhotoRejectApply
from app.services import (
    apply_photo_rejects,
    cleanup_files,
    generate_albums,
    make_decisions,
    preprocess_photos,
    push_results,
    run_all,
    scan_events,
)

app = FastAPI(title="AIXiaoMi Friend Album", version="0.1.0")


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "aixiaomi-friend-album"}


@app.post("/internal/schedulers/events")
def post_scan_events(db: Session = Depends(get_db)) -> dict:
    return scan_events(db)


@app.post("/internal/schedulers/preprocess")
def post_preprocess(db: Session = Depends(get_db)) -> dict:
    return preprocess_photos(db)


@app.post("/internal/schedulers/decision")
def post_decision(db: Session = Depends(get_db)) -> dict:
    return make_decisions(db)


@app.post("/internal/schedulers/generation")
def post_generation(db: Session = Depends(get_db)) -> dict:
    return generate_albums(db)


@app.post("/internal/schedulers/push")
def post_push(db: Session = Depends(get_db)) -> dict:
    return push_results(db)


@app.post("/internal/schedulers/cleanup")
def post_cleanup(db: Session = Depends(get_db)) -> dict:
    return cleanup_files(db)


@app.post("/internal/photos/apply-rejects")
def post_apply_rejects(payload: PhotoRejectApply, db: Session = Depends(get_db)) -> dict:
    return apply_photo_rejects(db, payload)


@app.post("/internal/schedulers/run-all")
def post_run_all(db: Session = Depends(get_db)) -> dict:
    return run_all(db)
