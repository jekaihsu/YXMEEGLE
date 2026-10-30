import pytest

from backend.avatar import avatar_url
from backend.node_assignment.lark_table import parse_node, parse_task, users
from backend.node_assignment.roster import parse_roster
from backend.node_assignment.domain import NodeKey
from backend.workspace_projection import public_person

PHOTO = 'https://s16-imfile-sg.feishucdn.com/static-resource/photo?image_size=72x72'
PERSON = {'id': 'ou_abc', 'name': '王怡婷', 'avatar_url': PHOTO}
PUBLIC = {'open_id': 'ou_abc', 'name': '王怡婷', 'avatar_url': PHOTO}


@pytest.mark.parametrize('value', [None, '', 'http://s16-imfile-sg.feishucdn.com/a',
    'https://feishucdn.com.evil.test/a', 'https://evilfeishucdn.com/a',
    'https://user:secret@s16-imfile-sg.feishucdn.com/a', 'https://s16-imfile-sg.feishucdn.com:8080/a',
    'https://s16-imfile-sg.feishucdn.com/a#secret', 'https://s16-imfile-sg.feishucdn.com/a b',
    'https://s16-imfile-sg.feishucdn.com:bad/a', 'data:image/png;base64,abc'])
def test_reject_avatar(value):
    assert avatar_url(value) is None
    assert avatar_url(PHOTO) == 'https://s16-imfile-sg.feishucdn.com/static-resource/photo?image_size=72x72'


def test_node_and_task_people():
    node = parse_node({'record_id': 'rec1', 'fields': {'負責人': [PERSON], '指派人': [PERSON], '核准人': [PERSON]}})
    assert node.owners[0].public() == PUBLIC
    assert node.assigned_by.public() == PUBLIC
    assert node.approver.public() == PUBLIC
    task = parse_task({'record_id': 'rec2', 'fields': {'負責人': [PERSON], '指派人': [PERSON]}})
    assert task.assignee.public() == PUBLIC
    assert task.assigned_by.public() == PUBLIC
    assert users([{'id': 'ou_abc', 'name': '王怡婷', 'avatar_url': 'https://evil.test/a'}])[0].public() == {'open_id': 'ou_abc', 'name': '王怡婷'}


def test_roster_and_public_person():
    roster = parse_roster([{'fields': {'姓名': '王怡婷', 'Lark帳號': [PERSON], '所屬組別': ['控制'], '在職': True}}])
    assert roster.public(roster.person('ou_abc'), NodeKey.CONTROL) == {'open_id': 'ou_abc', 'name': '王怡婷', 'departments': ['控制'], 'avatar_url': PHOTO}
    assert public_person({'id': 'ou_abc', 'name': '王怡婷', 'avatar_url': PHOTO, 'access_token': 'secret'}) == {'id': 'ou_abc', 'name': '王怡婷', 'avatar_url': PHOTO}
    assert public_person({'id': 'ou_abc', 'avatar_url': 'https://evil.test/a'}) == {'id': 'ou_abc'}


def test_directory_photo_reaches_public_profile():
    from backend.test_people_directory import Pages, page, row, schema, snapshot
    from backend.people_directory import fetch_directory, merge_directory, TABLE_ID
    record = row('r1', 'ou_abc', name='王怡婷')
    record['fields']['人員'][0]['avatar_url'] = PHOTO
    adapter = Pages([page([{'table_id': TABLE_ID, 'name': '人員名單及資料'}]), page(schema()), page([record])])
    incoming = fetch_directory(adapter, 'app1')
    assert incoming['people'][0]['avatar_url'] == 'https://s16-imfile-sg.feishucdn.com/static-resource/photo?image_size=72x72'
    merged, _ = merge_directory([], snapshot(incoming['people']))
    assert public_person(merged[0])['avatar_url'] == 'https://s16-imfile-sg.feishucdn.com/static-resource/photo?image_size=72x72'


def test_weekly_people_carries_only_safe_photo():
    from backend.live_read.datasets.weekly_attendance import project_people
    from backend.test_people_attendance import person
    assert project_people([person(avatar_url=PHOTO)], 'app') == [{'id': 'ou_one', 'name': '合成人員', 'group': '控制組', 'in_service': True, 'avatar_url': PHOTO}]
    assert project_people([person(avatar_url='https://evil.test/a')], 'app') == [{'id': 'ou_one', 'name': '合成人員', 'group': '控制組', 'in_service': True}]
