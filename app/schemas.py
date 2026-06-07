from pydantic import BaseModel


class PhotoRejectApply(BaseModel):
    user_id: str
    reject_reasons: dict[str, str]
