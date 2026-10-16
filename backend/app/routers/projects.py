"""Open-source project registry and donations. A donation moves test credits from the donor's available account to
the project's own budget account; it is irrevocable and never returns to the donor's balance (idea.md section 4).
Spending a project budget on jobs is not built yet."""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import current_user
from ..database import get_db
from ..ledger import InsufficientFunds, balance, spend
from ..models import Account, Project, User
from ..models.ledger import now
from .users import require_admin, user_account

router = APIRouter()


class NewProject(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(pattern=r"^https://\S+$", max_length=300)
    description: str = Field(min_length=1, max_length=1000)


class Donation(BaseModel):
    amount: int = Field(gt=0, le=10**9)


def view(p: Project, db: Session):
    return {"id": p.id, "name": p.name, "url": p.url, "description": p.description,
            "verified": p.verified_at is not None, "budget": balance(db, p.account_id)}


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    """Auth: none, deliberately: the verified registry and its budgets are public."""
    q = select(Project).where(Project.verified_at.is_not(None)).order_by(Project.id).limit(100)
    return [view(p, db) for p in db.scalars(q)]


@router.post("/projects", status_code=201)
def submit_project(body: NewProject, u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Auth: any user, who becomes the maintainer. Unlisted until an admin verifies it after moderation."""
    acc = Account(type="project_budget")
    db.add(acc)
    db.flush()
    p = Project(name=body.name, url=body.url, description=body.description, maintainer_user_id=u.id, account_id=acc.id)
    db.add(p)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "project name taken")
    db.commit()
    return view(p, db)


@router.post("/admin/projects/{project_id}/verify", dependencies=[Depends(require_admin)])
def verify_project(project_id: int, db: Session = Depends(get_db)):
    """Auth: admin token. A human moderation decision; compare-and-set so a repeat is a no-op."""
    if not db.get(Project, project_id):
        raise HTTPException(404, "not found")
    db.execute(update(Project).where(Project.id == project_id, Project.verified_at.is_(None)).values(verified_at=now()))
    db.commit()
    return {"ok": True}


@router.post("/projects/{project_id}/donations")
def donate(project_id: int, body: Donation, idempotency_key: str = Header(""), u: User = Depends(current_user),
           db: Session = Depends(get_db)):
    """Auth: any user, from their own available balance. Idempotency-Key header required (a retry donates once)."""
    if not idempotency_key.strip() or len(idempotency_key) > 200:
        raise HTTPException(400, "Idempotency-Key header required")
    p = db.get(Project, project_id)
    if not p or not p.verified_at:
        raise HTTPException(404, "no such verified project")
    try:
        spend(db, user_account(db, u.id, "user_available").id, p.account_id, body.amount, "donate",
              f"donate:{u.id}:{idempotency_key}")
    except InsufficientFunds:
        db.rollback()
        raise HTTPException(402, "insufficient credits")
    db.commit()
    return view(p, db)
