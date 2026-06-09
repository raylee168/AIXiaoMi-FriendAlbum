from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import (
    AlbumTemplateCreate,
    AlbumTemplateFactoryGenerate,
    AlbumTemplateMatchTest,
    AlbumTemplateSeasonalGenerate,
    AlbumTemplateUpdate,
    PhotoRejectApply,
)
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
from app.template_services import (
    archive_template,
    create_template,
    generate_templates_from_dialog,
    generate_seasonal_templates,
    generate_template_preview,
    get_template,
    list_base_templates,
    list_templates,
    match_templates,
    publish_template,
    update_template,
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


@app.get("/internal/templates")
def get_templates(status: str | None = None, category: str | None = None, q: str | None = None, db: Session = Depends(get_db)) -> dict:
    return list_templates(db, status=status, category=category, q=q)


@app.get("/internal/templates/base")
def get_base_templates() -> dict:
    return list_base_templates()


@app.post("/internal/templates")
def post_template(payload: AlbumTemplateCreate, db: Session = Depends(get_db)) -> dict:
    try:
        return create_template(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/internal/templates/{template_id}")
def get_template_detail(template_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        return get_template(db, template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/internal/templates/{template_id}")
def put_template(template_id: str, payload: AlbumTemplateUpdate, db: Session = Depends(get_db)) -> dict:
    try:
        return update_template(db, template_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/internal/templates/{template_id}/publish")
def post_template_publish(template_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        return publish_template(db, template_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/internal/templates/{template_id}/archive")
def post_template_archive(template_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        return archive_template(db, template_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/internal/templates/{template_id}/preview")
def post_template_preview(template_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        return generate_template_preview(db, template_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/internal/templates/generate-seasonal")
def post_templates_generate_seasonal(payload: AlbumTemplateSeasonalGenerate, db: Session = Depends(get_db)) -> dict:
    return generate_seasonal_templates(db, payload)


@app.post("/internal/templates/factory/generate")
def post_templates_factory_generate(payload: AlbumTemplateFactoryGenerate, db: Session = Depends(get_db)) -> dict:
    return generate_templates_from_dialog(db, payload)


@app.post("/internal/templates/match-test")
def post_template_match_test(payload: AlbumTemplateMatchTest, db: Session = Depends(get_db)) -> dict:
    return match_templates(db, payload)
