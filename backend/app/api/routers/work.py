from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routers.portal import get_current_contact
from app.db import get_db
from app.models.contact import Contact
from app.models.ticket import Ticket
from app.models.user import User
from app.models.work import WorkApproval, WorkComment, WorkProject, WorkTicketLink
from app.schemas.work import (ApprovalDecision, ApprovalRequest, CommentCreate, ProjectCreate, ProjectStatus,
                              ProjectTransition, ProjectUpdate, TaskCreate, TaskUpdate, TicketLink, Versioned)
from app.services import ticket_access, work

router = APIRouter(tags=['projects'])


def view(db, project, actor):
    db.expire_all()
    return work.project_view(db, db.get(WorkProject, project.id), actor)


@router.get('/projects')
def list_projects(response: Response, q: str = Query(default='', max_length=300), status: ProjectStatus | None = None,
                  mine: bool = False, overdue: bool = False, limit: int = Query(default=50, ge=1, le=200),
                  offset: int = Query(default=0, ge=0), db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    query = work.visible_query(db, actor)
    if q.strip():
        query = query.filter(WorkProject.title.ilike('%' + q.strip().replace('%', r'\%').replace('_', r'\_') + '%'))
    if status:
        query = query.filter(WorkProject.status == status)
    if mine:
        from app.models.work import WorkTask
        from sqlalchemy import or_
        query = query.filter(or_(WorkProject.owner_id == actor.id, WorkProject.id.in_(db.query(WorkTask.project_id).filter(WorkTask.assignee_id == actor.id)),
                                WorkProject.id.in_(db.query(WorkApproval.project_id).filter(WorkApproval.user_id == actor.id, WorkApproval.state == 'pending'))))
    if overdue:
        from datetime import date
        query = query.filter(WorkProject.due_date < date.today(), WorkProject.status.notin_(['completed', 'cancelled']))
    response.headers['X-Total-Count'] = str(query.count())
    return [work.project_view(db, p, actor, detail=False) for p in query.order_by(WorkProject.updated_at.desc(), WorkProject.id.desc()).offset(offset).limit(limit)]


@router.post('/projects', status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return view(db, work.create_project(db, payload, actor), actor)


@router.get('/projects/{project_id}')
def get_project(project_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return work.project_view(db, work.get_project(db, project_id, actor), actor)


@router.patch('/projects/{project_id}')
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    project = work.get_project(db, project_id, actor, payload.version, manage=True)
    work.update_project(db, project, payload, actor)
    return view(db, project, actor)


@router.post('/projects/{project_id}/status')
def transition_project(project_id: int, payload: ProjectTransition, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    project = work.get_project(db, project_id, actor, payload.version, manage=True)
    work.transition(db, project, payload, actor)
    return view(db, project, actor)


@router.post('/projects/{project_id}/tasks', status_code=201)
def create_task(project_id: int, payload: TaskCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    project = work.get_project(db, project_id, actor, payload.version, manage=True)
    work.create_task(db, project, payload, actor)
    return view(db, project, actor)


@router.patch('/projects/{project_id}/tasks/{task_id}')
def update_task(project_id: int, task_id: int, payload: TaskUpdate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    project = work.get_project(db, project_id, actor, payload.version)
    work.update_task(db, project, task_id, payload, actor)
    return view(db, project, actor)


@router.post('/projects/{project_id}/approvals', status_code=201)
def request_approval(project_id: int, payload: ApprovalRequest, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    project = work.get_project(db, project_id, actor, payload.version, manage=True)
    work.request_approval(db, project, payload, actor)
    return view(db, project, actor)


@router.post('/projects/{project_id}/approvals/{approval_id}/decision')
def decision(project_id: int, approval_id: int, payload: ApprovalDecision, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    project = work.get_project(db, project_id, actor, payload.version)
    work.decide(db, project, approval_id, payload, actor=actor)
    return view(db, project, actor)


@router.post('/projects/{project_id}/tickets', status_code=201)
def link_ticket(project_id: int, payload: TicketLink, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    project = work.get_project(db, project_id, actor, payload.version, manage=True)
    work.require_plan(project)
    ticket = ticket_access.visible_tickets_query(db, actor).filter(Ticket.id == payload.ticket_id).first()
    if ticket is None:
        work.fail('Заявка не найдена', 404)
    if project.organization_id is not None and project.organization_id != ticket.organization_id:
        work.fail('Заявка должна принадлежать организации проекта')
    if db.get(WorkTicketLink, (project.id, ticket.id)) is None:
        db.add(WorkTicketLink(project_id=project.id, ticket_id=ticket.id))
        work.record(db, project, 'ticket_linked', actor, {'ticket_id': ticket.id})
        db.commit()
    return view(db, project, actor)


@router.delete('/projects/{project_id}/tickets/{ticket_id}')
def unlink_ticket(project_id: int, ticket_id: int, payload: Versioned, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    project = work.get_project(db, project_id, actor, payload.version, manage=True)
    work.require_plan(project)
    link = db.get(WorkTicketLink, (project.id, ticket_id))
    if link is None:
        work.fail('Связь не найдена', 404)
    db.delete(link)
    work.record(db, project, 'ticket_unlinked', actor, {'ticket_id': ticket_id})
    db.commit()
    return view(db, project, actor)


@router.post('/projects/{project_id}/comments', status_code=201)
def add_comment(project_id: int, payload: CommentCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    project = work.get_project(db, project_id, actor)
    db.add(WorkComment(project_id=project.id, user_id=actor.id, body=payload.body))
    db.commit()
    return view(db, project, actor)


def portal_view(approval, project):
    return {key: getattr(approval, key) for key in ('id', 'project_id', 'round', 'state', 'snapshot', 'comment', 'requested_at', 'decided_at')} | {
        'project_version': project.version, 'project_status': project.status,
        'can_decide': project.status == 'approval' and approval.round == project.approval_round and approval.state == 'pending'}


@router.get('/portal/project-approvals')
def portal_approvals(db: Session = Depends(get_db), contact: Contact = Depends(get_current_contact)):
    rows = db.query(WorkApproval, WorkProject).join(WorkProject).filter(WorkApproval.contact_id == contact.id,
            WorkProject.organization_id == contact.organization_id).order_by(WorkApproval.id.desc()).limit(100).all()
    # Only the explicitly submitted, immutable plan. No live plan, staff notes, ticket links or other approvers.
    return [portal_view(a, p) for a, p in rows]


@router.post('/portal/project-approvals/{approval_id}/decision')
def portal_decision(approval_id: int, payload: ApprovalDecision, db: Session = Depends(get_db), contact: Contact = Depends(get_current_contact)):
    approval = db.query(WorkApproval).join(WorkProject).filter(WorkApproval.id == approval_id, WorkApproval.contact_id == contact.id,
            WorkProject.organization_id == contact.organization_id).first()
    if approval is None:
        work.fail('Согласование не найдено', 404)
    project = work.get_project(db, approval.project_id, version=payload.version)
    work.decide(db, project, approval.id, payload, contact=contact)
    return portal_view(approval, project)


@router.get('/tickets/{ticket_id}/projects')
def ticket_projects(ticket_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    if ticket_access.visible_tickets_query(db, actor).filter(Ticket.id == ticket_id).first() is None:
        work.fail('Заявка не найдена', 404)
    projects = work.visible_query(db, actor).filter(WorkProject.id.in_(
        db.query(WorkTicketLink.project_id).filter(WorkTicketLink.ticket_id == ticket_id))).order_by(WorkProject.id.desc()).all()
    return [{'id': p.id, 'title': p.title, 'status': p.status} for p in projects]
