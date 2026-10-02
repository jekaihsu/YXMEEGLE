import json
from types import SimpleNamespace
import pytest
from scripts import workbench_backup_roundtrip as tool

def test_key_generated_once_and_never_in_output(tmp_path,monkeypatch):
    monkeypatch.setattr(tool,'STATE',tmp_path)
    first=tool.prepare_key();saved=(tmp_path/'key-private.json').read_bytes()
    assert tool.prepare_key()==first and saved==(tmp_path/'key-private.json').read_bytes()
    assert json.loads(saved)['key'] not in json.dumps(first)
    assert first['custody_confirmed'] is False

def test_upload_pins_source_and_preserves_unknown_checkpoint(tmp_path,monkeypatch):
    monkeypatch.setattr(tool,'STATE',tmp_path)
    monkeypatch.setattr(tool,'configuration',lambda:{})
    receipt={'sha256':'abc','archive_path':'source'}
    monkeypatch.setattr(tool,'source',lambda:(tmp_path/'source',receipt))
    closed=[]
    monkeypatch.setattr(tool,'backup_adapter',lambda cfg:SimpleNamespace(client=SimpleNamespace(close=lambda:closed.append(True))))
    def replicate(*args):raise ValueError('unknown outcome')
    monkeypatch.setattr(tool,'replicate',replicate)
    with pytest.raises(ValueError):tool.upload()
    assert tool.read(tmp_path/'source-pin.json')==receipt and closed
    receipt['sha256']='other'
    with pytest.raises(ValueError,match='Pinned'):tool.upload()

def test_download_verifies_remote_ciphertext_without_database_claim(tmp_path,monkeypatch):
    monkeypatch.setattr(tool,'STATE',tmp_path)
    monkeypatch.setattr(tool,'configuration',lambda:{})
    for name,data in [('upload-receipt.json',{'source_sha256':'abc'}),('source-pin.json',{'sha256':'abc'})]:
        (tmp_path/name).write_text(json.dumps(data))
    bundle=tmp_path/'encrypted'/'one';bundle.mkdir(parents=True)
    (bundle/'receipt.json').write_text(json.dumps({'source_sha256':'abc','status':'verified','root':tool.FOLDER}))
    monkeypatch.setattr(tool,'backup_adapter',lambda cfg:SimpleNamespace(client=SimpleNamespace(close=lambda:None)))
    calls=[]
    monkeypatch.setattr(tool,'download_files',lambda adapter,state,target:calls.append('remote') or tmp_path/'manifest')
    monkeypatch.setattr(tool,'decrypt_bundle',lambda manifest,target,cfg:target.write_bytes(b'local-only'))
    monkeypatch.setattr(tool,'digest',lambda path:'abc')
    monkeypatch.setattr(tool,'validate_archive',lambda path:None)
    result=tool.download()
    assert calls==['remote'] and result['decrypted_archive_hash_equal']
    assert not result['database_restore_verified'] and not result['custody_confirmed']
    assert not (tmp_path/'downloaded-local-validation.zip').exists()
