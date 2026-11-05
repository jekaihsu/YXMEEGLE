"""Conflict scopes for administration commands, independent of workspace housekeeping."""
import hashlib
import json

from .workflow import require

PERSON_FIELDS=('id','name','department','role','capabilities','active','default_workspace','authz_version')


def revision(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def person_revision(person):
    return revision({key:person.get(key) for key in PERSON_FIELDS}) if person else revision(None)


def revisions(state):
    return {'people':{u['id']:person_revision(u) for u in state['users']},
            'settings':{key:revision(value) for key,value in state['settings'].items()},
            'new_person':person_revision(None)}


def check(state,action,payload,expected):
    if action=='admin_person':
        target=next((u for u in state['users'] if u['id']==str(payload.get('id','')).strip()),None)
        valid=set(expected)=={'person'} and expected['person']==person_revision(target)
    else:
        require(set(payload)<=set(state['settings']),'未知設定',422)
        valid=set(expected)==set(payload) and all(key in state['settings'] and expected[key]==revision(state['settings'][key]) for key in payload)
    require(valid,'此人員或設定已被更新，請核對最新內容後再儲存',409)
