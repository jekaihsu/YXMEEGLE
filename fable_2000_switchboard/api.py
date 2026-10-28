"""Card source of truth and role-filtered Canvas API. Tokens are provisioned by the trusted auth service."""
from __future__ import annotations
import hashlib, os
from typing import Literal
from uuid import UUID
import psycopg
from psycopg.rows import dict_row
from psycopg import sql
from canvas_policy import VIEWS,columns,project
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict

ROLE_COLUMNS={
 'sales':('id','name','floor_price','traffic_light'),
 'pm':('id','name','floor_price','traffic_light','standard_cost_price'),
 'vp':('id','name','floor_price','traffic_light','standard_cost_price'),
 'admin':('id','name','floor_price','traffic_light'),
 'finance':('id','name','floor_price','traffic_light'),
}
CARD_COLUMNS='id,org_id,case_id,kind,status,assignee_employee_id,proposed_fields,evidence_numbers,evidence_sql_ids,acted_at,action,canvas_view,canvas_ref'
class ActBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['confirm','approve','return_work','reject']

def create_app(dsn=None):
    database=dsn or os.environ.get('PG_DSN','dbname=yongxiang_plumb_r39_clone')
    app=FastAPI(title='Switchboard cards')
    def actor(authorization:str=Header(...)):
        if not authorization.startswith('Bearer '): raise HTTPException(401,'Bearer token required')
        token=authorization[7:]
        with psycopg.connect(database,row_factory=dict_row) as conn:
            session=conn.execute('''SELECT s.employee_id,s.org_id,s.role FROM api_session s JOIN employee e ON e.id=s.employee_id AND e.org_id=s.org_id
             WHERE s.token_sha256=%s AND s.expires_at>now() AND e.employment_status='active' AND e.identity_confirmed''',
             (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not session: raise HTTPException(401,'Invalid or expired token')
        return session
    @app.get('/canvas/2')
    def canvas(identity=Depends(actor)):
        columns=ROLE_COLUMNS[identity['role']]
        with psycopg.connect(database,row_factory=dict_row) as conn:
            # Projection and serializer both enforce the whitelist; no SELECT * or hr_private queries.
            rows=conn.execute('SELECT '+','.join(columns)+' FROM work_item_policy WHERE org_id=%s ORDER BY id',(identity['org_id'],)).fetchall()
        return [{key:row[key] for key in columns} for row in rows]
    @app.get('/inbox')
    def inbox(identity=Depends(actor)):
        with psycopg.connect(database,row_factory=dict_row) as conn:
            return conn.execute('SELECT '+CARD_COLUMNS+' FROM card WHERE org_id=%s AND assignee_employee_id=%s AND status=\'open\' ORDER BY created_at,id',(identity['org_id'],identity['employee_id'])).fetchall()
    @app.get('/cards/{card_id}')
    def get_card(card_id:UUID,identity=Depends(actor)):
        with psycopg.connect(database,row_factory=dict_row) as conn:
            card=conn.execute('SELECT '+CARD_COLUMNS+' FROM card WHERE id=%s AND org_id=%s AND assignee_employee_id=%s',(card_id,identity['org_id'],identity['employee_id'])).fetchone()
        if not card: raise HTTPException(404,'Card not found')
        return card
    @app.get('/canvas/{card_id}')
    def card_canvas(card_id:UUID,identity=Depends(actor)):
        with psycopg.connect(database,row_factory=dict_row) as conn:
            card=conn.execute('SELECT canvas_view,canvas_ref,case_id FROM card WHERE id=%s AND org_id=%s AND assignee_employee_id=%s',(card_id,identity['org_id'],identity['employee_id'])).fetchone()
            if not card:raise HTTPException(404,'Card not found')
            view_no=card['canvas_view']
            if not view_no:return {'card_id':str(card_id),'view':None,'row':None}
            if view_no not in VIEWS:raise HTTPException(404,'Canvas not found')
            view_name,key=VIEWS[view_no];keep=columns(view_no,identity['role'])
            query=sql.SQL('SELECT {} FROM public.{} WHERE {}=%s AND case_id=%s').format(sql.SQL(',').join(map(sql.Identifier,keep)),sql.Identifier(view_name),sql.Identifier(key))
            row=conn.execute(query,(card['canvas_ref'].get(key),card['case_id'])).fetchone()
            if row is None:raise HTTPException(404,'Canvas row not found')
            return {'card_id':str(card_id),'view':view_no,'row':project(view_no,identity['role'],row),'columns':list(keep)}
    @app.post('/cards/{card_id}/act')
    def act(card_id:UUID,body:ActBody,idempotency_key:str=Header(...,min_length=1,max_length=128),identity=Depends(actor)):
        try:
            with psycopg.connect(database) as conn:
                visible=conn.execute('SELECT 1 FROM card WHERE id=%s AND org_id=%s AND assignee_employee_id=%s',(card_id,identity['org_id'],identity['employee_id'])).fetchone()
                if not visible: raise HTTPException(404,'Card not found')
                return conn.execute('SELECT public.card_act(%s,%s,%s,%s)',(card_id,identity['employee_id'],body.action,idempotency_key)).fetchone()[0]
        except psycopg.errors.InsufficientPrivilege as exc:
            raise HTTPException(403,'Assignee authorization failed') from exc
        except (psycopg.errors.UniqueViolation,psycopg.errors.RaiseException) as exc:
            raise HTTPException(409,exc.diag.message_primary) from exc
    return app
app=create_app()
