from pydantic import BaseModel


class PhotoRejectApply(BaseModel):
    user_id: str
    reject_reasons: dict[str, str]


class AlbumTemplateCreate(BaseModel):
    name: str
    category: str = "daily"
    min_photo_count: int = 1
    max_photo_count: int = 9
    theme_tags: list[str] = []
    style_tags: list[str] = []
    description: str | None = None
    template_json: dict
    llm_prompt: str
    matching_rules: dict = {}
    render_params: dict = {}
    created_by: str = "admin"


class AlbumTemplateUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    min_photo_count: int | None = None
    max_photo_count: int | None = None
    theme_tags: list[str] | None = None
    style_tags: list[str] | None = None
    description: str | None = None
    template_json: dict | None = None
    llm_prompt: str | None = None
    matching_rules: dict | None = None
    render_params: dict | None = None


class AlbumTemplateSeasonalGenerate(BaseModel):
    festival: str = "端午节"
    target_count: int = 8
    photo_count_min: int = 1
    photo_count_max: int = 12
    style_direction: str = "朋友圈、清新、节日氛围、适合自动生成"
    created_by: str = "admin"


class AlbumTemplateFactoryGenerate(BaseModel):
    prompt: str
    target_count: int | None = None
    photo_count_min: int | None = None
    photo_count_max: int | None = None
    theme: str | None = None
    created_by: str = "admin"


class AlbumTemplateMatchTest(BaseModel):
    upload_batch_id: str | None = None
    user_id: str | None = None
    photo_count: int | None = None
    scene_tags: list[str] = []
    mood: str | None = None
    limit: int = 6
