"""Canonical database schema, importable without starting the application."""
from sqlalchemy import Column, String, Integer, JSON, Index, Boolean, Float, BigInteger, UniqueConstraint
from sqlalchemy.orm import declarative_base
from . import storage

Base=declarative_base()
class WorkspaceRow(Base):
    __tablename__='workspaces'
    id=Column(String(120),primary_key=True); version=Column(Integer,nullable=False); data=Column(JSON,nullable=False)
class Receipt(Base):
    __tablename__='receipts'
    id=Column(String(300),primary_key=True); fingerprint=Column(String(64)); result=Column(JSON)
class AuthRow(Base):
    __tablename__='auth_sessions'
    id=Column(String(100),primary_key=True); data=Column(JSON)
class CacheRow(Base):
    __tablename__='source_caches'
    id=Column(String(120),primary_key=True); data=Column(JSON)
class AuditRow(Base):
    __tablename__='action_audit'
    __table_args__=(Index('ix_action_audit_workspace_created_id','workspace_id','created_at','id'),)
    id=Column(String(64),primary_key=True)
    workspace_id=Column(String(120),nullable=False,index=True)
    actor_id=Column(String(120),nullable=False)
    action=Column(String(120),nullable=False)
    created_at=Column(String(64),nullable=False,index=True)
    data=Column(JSON,nullable=False)
class ProjectIndex(Base):
    """Queryable project card; derived from business_records, never authoritative."""
    __tablename__='project_index'
    __table_args__=(Index('ix_project_index_visibility_due','workspace_id','case_visibility','due_date','project_id'),
                    Index('ix_project_index_pm_status','workspace_id','pm_id','status'),
                    Index('ix_project_index_status_due','workspace_id','status','due_date','project_id'),
                    Index('ix_project_index_code','workspace_id','code'))
    workspace_id=Column(String(120),primary_key=True)
    project_id=Column(String(160),primary_key=True)
    ordinal=Column(Integer,nullable=False,default=0)
    code=Column(String(120),nullable=False,default='')
    name=Column(String(300),nullable=False,default='')
    client=Column(String(300),nullable=False,default='')
    pm_id=Column(String(120),nullable=False,default='')
    admin_id=Column(String(120),nullable=False,default='')
    supervisor_id=Column(String(120),nullable=False,default='')
    status=Column(String(60),nullable=False,default='')
    execution_status=Column(String(60),nullable=False,default='')
    priority=Column(String(30),nullable=False,default='')
    case_type=Column(String(60),nullable=False,default='')
    case_visibility=Column(String(60),nullable=False,default='')
    source_kind=Column(String(60),nullable=False,default='')
    source_status=Column(String(120),nullable=False,default='')
    execution_system=Column(String(60),nullable=False,default='')
    due_date=Column(String(32),nullable=False,default='')
    created_at=Column(String(64),nullable=False,default='')
    concurrency_version=Column(Integer,nullable=False,default=0)
    nodes_total=Column(Integer,nullable=False,default=0)
    nodes_completed=Column(Integer,nullable=False,default=0)
    tasks_total=Column(Integer,nullable=False,default=0)
    tasks_completed=Column(Integer,nullable=False,default=0)
    summary=Column(JSON)
    source_version=Column(Integer,nullable=False,default=0)

class TaskIndex(Base):
    """One row per task; due_date is stored so overdue is a read-time COUNT."""
    __tablename__='task_index'
    __table_args__=(Index('ix_task_index_assignee_status_due','workspace_id','assignee_id','status','due_date'),
                    Index('ix_task_index_status_due','workspace_id','status','due_date'),
                    Index('ix_task_index_project','workspace_id','project_id'))
    workspace_id=Column(String(120),primary_key=True)
    task_id=Column(String(160),primary_key=True)
    project_id=Column(String(160),nullable=False)
    node_id=Column(String(160),nullable=False)
    node_key=Column(String(60),nullable=False,default='')
    node_ordinal=Column(Integer,nullable=False,default=0)
    ordinal=Column(Integer,nullable=False,default=0)
    assignee_id=Column(String(120),nullable=False,default='')
    status=Column(String(60),nullable=False,default='')
    due_date=Column(String(32),nullable=False,default='')
    required=Column(Boolean,nullable=False,default=True)
    node_name=Column(String(200),nullable=True)  # node title shown on the dashboard; NULL until re-backfilled

class WorkspaceCounter(Base):
    """Stored non-time-dependent counts; subject_id is '' for workspace-wide keys."""
    __tablename__='workspace_counters'
    workspace_id=Column(String(120),primary_key=True)
    key=Column(String(60),primary_key=True)
    subject_id=Column(String(120),primary_key=True,default='')
    value=Column(Integer,nullable=False,default=0)
    source_version=Column(Integer,nullable=False,default=0)


class DispatchLockRow(Base):
    """One row per workspace; updating it first serializes dispatch writes across processes."""
    __tablename__='dispatch_locks'
    workspace_id=Column(String(120),primary_key=True)
    counter=Column(Integer,nullable=False,default=0)

class DispatchPreviewRow(Base):
    __tablename__='dispatch_previews'
    __table_args__=(Index('ix_dispatch_previews_hash','workspace_id','preview_hash'),)
    id=Column(String(64),primary_key=True)
    workspace_id=Column(String(120),nullable=False)
    preview_hash=Column(String(64),nullable=False)
    task_id=Column(String(64),nullable=True)
    draft_id=Column(String(64),nullable=True)
    actor_id=Column(String(120),nullable=False)
    created_at=Column(Float,nullable=False)
    expires_at=Column(Float,nullable=False)
    data=Column(JSON,nullable=False)

class DispatchDraftRow(Base):
    __tablename__='dispatch_drafts'
    workspace_id=Column(String(120),primary_key=True)
    id=Column(String(64),primary_key=True)
    actor_id=Column(String(120),nullable=False)
    task_id=Column(String(64),nullable=True)
    version=Column(Integer,nullable=False)
    updated_at=Column(Float,nullable=False)
    data=Column(JSON,nullable=False)

class DispatchDecisionRow(Base):
    """Append-only; at most one decision per seat on one proposal hash."""
    __tablename__='dispatch_decisions'
    __table_args__=(UniqueConstraint('workspace_id','preview_hash','seat',name='uq_dispatch_decision_seat'),)
    id=Column(String(64),primary_key=True)
    workspace_id=Column(String(120),nullable=False)
    preview_hash=Column(String(64),nullable=False)
    preview_id=Column(String(64),nullable=False)
    seat=Column(String(40),nullable=False)
    actor_id=Column(String(120),nullable=False)
    decision=Column(String(20),nullable=False)
    reason=Column(String(500),nullable=True)
    at=Column(Float,nullable=False)

class DispatchCommandRow(Base):
    __tablename__='dispatch_commands'
    __table_args__=(Index('ix_dispatch_commands_hash','workspace_id','preview_hash'),
                    Index('ix_dispatch_commands_task','workspace_id','task_id'))
    workspace_id=Column(String(120),primary_key=True)
    command_id=Column(String(64),primary_key=True)
    preview_id=Column(String(64),nullable=False)
    preview_hash=Column(String(64),nullable=False)
    action=Column(String(10),nullable=False)
    task_id=Column(String(64),nullable=True)
    actor_id=Column(String(120),nullable=False)
    state=Column(String(30),nullable=False)
    revision=Column(Integer,nullable=False)
    attempt=Column(Integer,nullable=False,default=1)
    payload=Column(JSON,nullable=False)
    receipt=Column(JSON,nullable=True)
    created_at=Column(Float,nullable=False)
    updated_at=Column(Float,nullable=False)

class DispatchReservationRow(Base):
    __tablename__='dispatch_reservations'
    __table_args__=(Index('ix_dispatch_reservations_resource','workspace_id','state','resource_kind','ref'),)
    id=Column(String(64),primary_key=True)
    workspace_id=Column(String(120),nullable=False)
    resource_kind=Column(String(20),nullable=False)
    ref=Column(String(64),nullable=False)
    start_ms=Column(BigInteger,nullable=False)
    end_ms=Column(BigInteger,nullable=False)
    command_id=Column(String(64),nullable=False)
    task_id=Column(String(64),nullable=True)
    state=Column(String(20),nullable=False)

BusinessRow,PersonRow=storage.models(Base)
