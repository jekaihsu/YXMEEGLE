import pytest
from scripts import run_service as service


def simulate(monkeypatch,uid=0):
 monkeypatch.setattr(service.sys,'platform','linux');monkeypatch.setenv('APP_ENV','production')
 current={'uid':uid,'gid':0,'groups':[0,10]};calls=[]
 for name,key in [('getuid','uid'),('geteuid','uid'),('getgid','gid'),('getegid','gid'),('getgroups','groups')]:
  monkeypatch.setattr(service.os,name,lambda k=key:current[k],raising=False)
 for name,key in [('setgroups','groups'),('setgid','gid'),('setuid','uid')]:
  def setter(value,k=key,n=name):calls.append((n,value));current[k]=value
  monkeypatch.setattr(service.os,name,setter,raising=False)
 return current,calls


def test_linux_production_drops_before_children(monkeypatch):
 state,calls=simulate(monkeypatch)
 service.drop_runtime_privileges()
 assert calls==[('setgroups',[]),('setgid',10001),('setuid',10001)]
 assert state=={'uid':10001,'gid':10001,'groups':[]}


def test_already_nonroot_never_attempts_elevation(monkeypatch):
 _,calls=simulate(monkeypatch,uid=10002)
 service.drop_runtime_privileges();assert calls==[]


@pytest.mark.parametrize('platform,environment',[('win32','production'),('linux','development')])
def test_windows_and_development_unchanged(monkeypatch,platform,environment):
 _,calls=simulate(monkeypatch)
 monkeypatch.setattr(service.sys,'platform',platform);monkeypatch.setenv('APP_ENV',environment)
 service.drop_runtime_privileges();assert calls==[]


def test_drop_error_stops_before_web_or_worker(monkeypatch):
 simulate(monkeypatch)
 monkeypatch.setattr(service.os,'setuid',lambda _:(_ for _ in ()).throw(PermissionError()),raising=False)
 monkeypatch.setattr(service,'supervise',lambda *a,**kw:pytest.fail('must not start children'))
 assert service.main()==1


def test_ineffective_drop_is_not_accepted(monkeypatch):
 simulate(monkeypatch)
 monkeypatch.setattr(service.os,'setuid',lambda _:None,raising=False)
 with pytest.raises(RuntimeError):service.drop_runtime_privileges()
