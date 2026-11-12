"""Settings preserve their declared scalar types at the action boundary."""
import pytest
from .test_backend import app, client, act, role, workspace


@pytest.mark.parametrize('payload', [
    {'external_enabled': 'true'}, {'external_enabled': 1},
    {'test_base': {}}, {'test_input_table': []}, {'input_base': ['bad']}, {'input_table': 5},
    {'daily_backup_days': '30'}, {'daily_backup_days': True}, {'daily_backup_days': 0},
    {'monthly_backup_months': -1}, {'rpo_hours': None}, {'rto_hours': 1.5},
    {'field_weekday': True}, {'monthly_workday': True},
])
def test_admin_settings_rejects_invalid_scalar_types(client, payload):
    role(client, 'u-manager')
    before = workspace(client)
    reply = act(client, 'admin_settings', payload, project=None)
    assert reply.status_code == 422
    after = workspace(client)
    assert after['settings'] == before['settings']
    assert after['version'] == before['version']


def test_admin_settings_accepts_valid_connection_and_schedule_values(client):
    role(client, 'u-manager')
    reply = act(client, 'admin_settings', {'external_enabled': True, 'test_base': 'isolated-base',
                                         'field_weekday': 0, 'daily_backup_days': 31}, project=None)
    assert reply.status_code == 200
    settings = reply.json()['settings']
    assert settings['external_enabled'] is True
    assert settings['test_base'] == 'isolated-base'
    assert settings['field_weekday'] == 0
    assert settings['daily_backup_days'] == 31
