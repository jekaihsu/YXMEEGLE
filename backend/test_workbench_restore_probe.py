import base64
import json
from types import SimpleNamespace
import zlib
import pytest
from scripts import workbench_restore_probe as probe


def test_fixed_target_allowlist():
    with pytest.raises(ValueError):probe.command('6ab61834a4c05a5bcb57ad69',['python'])
    for ident in (probe.STAGING,probe.RESTORE):
        cmd=probe.command(ident,['python'])
        assert cmd[cmd.index('--env-id')+1]==probe.ENV
        assert '-i=false' in cmd


def test_launcher_contains_only_fixed_program():
    program=probe.launcher(probe.REMOTE_STDIN)
    assert 'password' not in program
    compile(program,'launcher','exec')
    compile(probe.REMOTE_READINESS,'readiness','exec')
    compile(probe.REMOTE_STDIN,'stdin','exec')


@pytest.mark.parametrize('step,interactive',[('stdin',False),('stdin-interactive',True)])
def test_nonsecret_stdin_is_sent_only_via_input(monkeypatch,step,interactive):
    def run(cmd,**kwargs):
        assert kwargs['input']==probe.NONCE+'\n'
        assert probe.NONCE not in ' '.join(cmd)
        assert ('-i=true' if interactive else '-i=false') in cmd
        assert cmd[cmd.index('--id')+1]==probe.STAGING
        return SimpleNamespace(returncode=0,stdout=probe.MARKER+json.dumps({'stdin_received':True,'stdin_isatty':False}),stderr='ignored')
    monkeypatch.setattr(probe.subprocess,'run',run)
    assert probe.run_probe(step)['ok'] is True


def test_unknown_transport_output_not_forwarded(monkeypatch):
    monkeypatch.setattr(probe.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=1,stdout='PRIVATE',stderr='PRIVATE'))
    result=probe.run_probe('readiness')
    assert not result['ok'] and 'PRIVATE' not in json.dumps(result)


def test_pg_readiness_does_not_claim_empty_database(monkeypatch):
    def run(cmd,**kw):
        assert cmd[cmd.index('--id')+1]==probe.RESTORE
        assert 'pg_isready' in cmd[-1] and 'psql' not in cmd[-1]
        assert kw['input'] is None
        return SimpleNamespace(returncode=0,stdout=probe.MARKER+'{"postgres_accepting_connections":true}',stderr='')
    monkeypatch.setattr(probe.subprocess,'run',run)
    result=probe.run_probe('postgres')
    assert result['ok'] and not result['database_empty_verified'] and not result['restore_performed']


def test_stdin_not_received_is_blocked(monkeypatch):
    monkeypatch.setattr(probe.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=probe.MARKER+'{"stdin_received":false}',stderr=''))
    assert not probe.run_probe('stdin')['ok']
