"""Canonical database schema, importable without starting the application."""
from sqlalchemy import Column, String, Integer, JSON
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
    id=Column(String(64),primary_key=True)
    workspace_id=Column(String(120),nullable=False,index=True)
    actor_id=Column(String(120),nullable=False)
    action=Column(String(120),nullable=False)
    created_at=Column(String(64),nullable=False,index=True)
    data=Column(JSON,nullable=False)

BusinessRow,PersonRow=storage.models(Base)
