from sqlalchemy import Column, String, Integer, JSON, Float, Boolean, UniqueConstraint, ForeignKeyConstraint, Enum
from ..models import Base
from .domain import Disposition, Applicability, Lifecycle


def enum_type(cls, name=None):
    return Enum(cls, name=name or cls.__name__.lower(), values_callable=lambda values: [v.value for v in values], native_enum=False,
                create_constraint=True, validate_strings=True)


class Family(Base):
    __tablename__ = 'sop_template_families'
    workspace_id = Column(String(120), primary_key=True)
    id = Column(String(120), primary_key=True)
    name = Column(String(300), nullable=False)
    is_default = Column(Boolean, nullable=False, default=False)
    lifecycle = Column(String(20), nullable=False, default='active')


class Version(Base):
    __tablename__ = 'sop_template_versions'
    __table_args__ = (ForeignKeyConstraint(['workspace_id', 'family_id'],
                                        ['sop_template_families.workspace_id', 'sop_template_families.id']),
                      UniqueConstraint('workspace_id', 'family_id', 'revision'))
    workspace_id = Column(String(120), primary_key=True)
    id = Column(String(120), primary_key=True)
    family_id = Column(String(120), nullable=False)
    revision = Column(String(120), nullable=False)
    mapping_revision = Column(String(120), nullable=False)
    content_hash = Column(String(64), nullable=False)
    source_hash = Column(String(64), nullable=False)
    source_verified = Column(Boolean, nullable=False, default=False)
    catalog_manifest = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False)
    published_by = Column(String(120))
    published_at = Column(Float)


class TemplateRow(Base):
    __tablename__ = 'sop_template_rows'
    __table_args__ = (ForeignKeyConstraint(['workspace_id', 'version_id'],
                                        ['sop_template_versions.workspace_id', 'sop_template_versions.id']),)
    workspace_id = Column(String(120), primary_key=True)
    version_id = Column(String(120), primary_key=True)
    source_row_key = Column(String(160), primary_key=True)
    ordinal = Column(Integer, nullable=False)
    disposition = Column(enum_type(Disposition), nullable=False)
    snapshot = Column(JSON, nullable=False)


class CaseState(Base):
    __tablename__ = 'sop_case_state'
    workspace_id = Column(String(120), primary_key=True)
    project_id = Column(String(160), primary_key=True)
    checklist_revision = Column(Integer, nullable=False, default=0)
    identity_revision = Column(Integer, nullable=False, default=0)
    lock_counter = Column(Integer, nullable=False, default=0)


class LocalTask(Base):
    __tablename__ = 'sop_local_tasks'
    __table_args__ = (UniqueConstraint('workspace_id', 'project_id', 'template_family_id', 'source_row_key',
                                      'instance_scope', name='uq_sop_task_origin'),
                      UniqueConstraint('workspace_id', 'project_id', 'id'),
                      ForeignKeyConstraint(['workspace_id', 'project_id'],
                                           ['sop_case_state.workspace_id', 'sop_case_state.project_id']))
    workspace_id = Column(String(120), primary_key=True)
    id = Column(String(64), primary_key=True)
    project_id = Column(String(160), nullable=False, index=True)
    template_family_id = Column(String(120), nullable=False)
    source_row_key = Column(String(160), nullable=False)
    instance_scope = Column(String(40), nullable=False)
    imported_version_id = Column(String(120))
    snapshot = Column(JSON, nullable=False)
    title = Column(String(500), nullable=False)
    instructions = Column(String(20000), nullable=False)
    participants = Column(JSON, nullable=False)
    applicability = Column(enum_type(Applicability), nullable=False)
    state = Column(enum_type(Lifecycle, 'sop_task_state'), nullable=False, default=Lifecycle.PENDING)
    previous_state = Column(enum_type(Lifecycle, 'sop_task_previous_state'))
    revision = Column(Integer, nullable=False, default=1)
    local = Column(JSON, nullable=False)


class TaskNodeLink(Base):
    __tablename__ = 'sop_task_node_links'
    __table_args__ = (ForeignKeyConstraint(['workspace_id', 'project_id', 'task_id'],
                                         ['sop_local_tasks.workspace_id', 'sop_local_tasks.project_id', 'sop_local_tasks.id']),
                      UniqueConstraint('workspace_id', 'task_id', 'node_key'))
    workspace_id = Column(String(120), primary_key=True)
    task_id = Column(String(64), primary_key=True)
    node_id = Column(String(160), primary_key=True)
    project_id = Column(String(160), nullable=False, index=True)
    node_key = Column(String(60), nullable=False)
    ordinal = Column(Integer, nullable=False)


class Preview(Base):
    __tablename__ = 'sop_import_previews'
    workspace_id = Column(String(120), primary_key=True)
    id = Column(String(64), primary_key=True)
    project_id = Column(String(160), nullable=False, index=True)
    actor_id = Column(String(120), nullable=False)
    expires_at = Column(Float, nullable=False)
    context_hash = Column(String(64), nullable=False)
    data = Column(JSON, nullable=False)


class ImportRun(Base):
    __tablename__ = 'sop_import_runs'
    workspace_id = Column(String(120), primary_key=True)
    project_id = Column(String(160), primary_key=True)
    request_id = Column(String(120), primary_key=True)
    id = Column(String(64), nullable=False)
    actor_id = Column(String(120), nullable=False)
    request_hash = Column(String(64), nullable=False)
    receipt = Column(JSON, nullable=False)


class TaskEvent(Base):
    __tablename__ = 'sop_task_events'
    __table_args__ = (ForeignKeyConstraint(['workspace_id', 'project_id', 'task_id'],
                                         ['sop_local_tasks.workspace_id', 'sop_local_tasks.project_id', 'sop_local_tasks.id']),)
    workspace_id = Column(String(120), primary_key=True)
    id = Column(String(64), primary_key=True)
    project_id = Column(String(160), nullable=False, index=True)
    task_id = Column(String(64), nullable=False)
    actor_id = Column(String(120), nullable=False)
    at = Column(Float, nullable=False)
    kind = Column(String(40), nullable=False)
    revision = Column(Integer, nullable=False)
    changes = Column(JSON, nullable=False)


from sqlalchemy import event, inspect
from sqlalchemy.orm import Session
from .domain import Failure


@event.listens_for(Session, 'before_flush')
def protect_history(session, flush_context, instances):
    for obj in session.dirty | session.deleted:
        if isinstance(obj, Version):
            history = inspect(obj).attrs.status.history
            previous = history.deleted[0] if history.deleted else obj.status
            if previous in {'published', 'retired'}:
                changes = {a.key for a in inspect(obj).attrs if a.history.has_changes()}
                if obj in session.deleted or changes - {'status'} or obj.status not in {'published', 'retired'}:
                    raise Failure('immutable_template_version', 409)
        if isinstance(obj, TemplateRow):
            version = session.get(Version, (obj.workspace_id, obj.version_id))
            if version and version.status != 'draft':
                raise Failure('immutable_template_version', 409)
        if isinstance(obj, LocalTask):
            immutable = {'project_id', 'template_family_id', 'source_row_key', 'instance_scope',
                         'imported_version_id', 'snapshot', 'workspace_id', 'id'}
            if obj in session.deleted or any(inspect(obj).attrs[k].history.has_changes() for k in immutable):
                raise Failure('immutable_task_origin', 409)
        if isinstance(obj, TaskEvent):
            raise Failure('immutable_task_event', 409)
