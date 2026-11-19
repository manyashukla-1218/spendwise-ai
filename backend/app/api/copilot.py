from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_tenant
from ..models import Tenant
from ..services import copilot

router = APIRouter(prefix="/copilot", tags=["copilot"])


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@router.post("")
def ask(
    body: Question, t: Tenant = Depends(current_tenant), db: Session = Depends(get_db)
):
    return copilot.ask(body.question, db, t.id)
