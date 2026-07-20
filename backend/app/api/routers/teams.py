from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.db import get_db
from app.models.team import Team
from app.models.user import User, TeamMembership
from app.schemas.team import TeamCreate, TeamRead, TeamUpdate

router = APIRouter(prefix="/teams", tags=["teams"])


def _to_read(team: Team) -> TeamRead:
    return TeamRead(
        id=team.id,
        name=team.name,
        lead_user_id=team.lead_user_id,
        member_user_ids=[m.user_id for m in team.memberships],
    )


@router.get("", response_model=list[TeamRead])
def list_teams(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[TeamRead]:
    return [_to_read(t) for t in db.query(Team).order_by(Team.name).all()]


@router.post("", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
def create_team(
    payload: TeamCreate, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)
) -> TeamRead:
    team = Team(name=payload.name, lead_user_id=payload.lead_user_id)
    db.add(team)
    db.flush()
    for user_id in payload.member_user_ids:
        db.add(TeamMembership(user_id=user_id, team_id=team.id))
    db.commit()
    db.refresh(team)
    return _to_read(team)


@router.get("/{team_id}", response_model=TeamRead)
def get_team(team_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> TeamRead:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Команда не найдена")
    return _to_read(team)


@router.patch("/{team_id}", response_model=TeamRead)
def update_team(
    team_id: int,
    payload: TeamUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager_or_above),
) -> TeamRead:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Команда не найдена")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(team, field, value)
    db.add(team)
    db.commit()
    db.refresh(team)
    return _to_read(team)


@router.put("/{team_id}/members", response_model=TeamRead)
def set_team_members(
    team_id: int,
    member_user_ids: list[int],
    db: Session = Depends(get_db),
    _: User = Depends(require_manager_or_above),
) -> TeamRead:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Команда не найдена")
    db.query(TeamMembership).filter(TeamMembership.team_id == team_id).delete()
    for user_id in member_user_ids:
        db.add(TeamMembership(user_id=user_id, team_id=team_id))
    db.commit()
    db.refresh(team)
    return _to_read(team)
