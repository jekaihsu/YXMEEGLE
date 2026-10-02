from copy import deepcopy
from . import audit


def test_child_changes_and_removed_comments_retain_project_scope():
    state={'projects':[{'id':'case1','nodes':[{'id':'node1','tasks':[{'id':'task1','status':'pending'}]}],
                        'comments':[{'id':'comment1','body':'old'}], 'files':[]}]}
    before=audit.entities(state)
    changed=deepcopy(state)
    changed['projects'][0]['nodes'][0]['tasks'][0]['status']='completed'
    changed['projects'][0]['comments']=[]
    diffs=audit.changes(before,changed)
    assert {(d['kind'],d['id'],d['project_id']) for d in diffs}=={
        ('task','task1','case1'),('comment','comment1','case1')}
    assert 'project_id' not in state['projects'][0]['nodes'][0]['tasks'][0]
