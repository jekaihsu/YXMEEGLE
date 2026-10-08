"""Canonical database schema, importable without starting the application."""
from sqlalchemy import Column, String, Integer, JSON, Index, Boolean
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
    shell_facts=Column(JSON(none_as_null=True))  # SQL NULL until re-backfilled
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

BusinessRow,PersonRow=storage.models(Base)
