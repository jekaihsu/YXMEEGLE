from pathlib import Path
import pytest
import switchboard_engine as E
from ci.gen_guard_constants import DEFAULT_OUT,check,render,validate_python,corpus,rows,py_to_pg

def test_generated_sql_current():
    assert DEFAULT_OUT.read_text()==render()

def test_python_corpus():
    assert validate_python()>=100

def test_postgresql_exact_hit_parity(dsn):
    result=check(dsn)
    assert result['parity_percent']==100

def test_every_pattern_compiles_and_is_generated():
    for kind,name,pattern,flags in rows():
        assert name in render()
        assert py_to_pg(pattern,flags)

def test_engine_does_not_claim_authenticity():
    result=E.parse_satellite_command('yonginside@gmail.com','成果','請寄給 客戶\n\n成果如附件')
    assert result.is_internal_address
    assert not hasattr(result,'is_authentic_source')

def test_first_hit_order():
    assert E.check_outbound_body('成本','請寄給 客戶')[0].detail=='internal_03'
    assert E.check_outbound_body('成本','毛利')[0].detail=='forbidden_00'

def test_actual_outbound_trigger_uses_shared_guard(conn):
    from test_convergence import fixture,reject
    f=fixture(conn)
    # Exercise trigger, including NFKC, multiline, and first-hit identity.
    samples=[('internal','您好\n給恆安，'),('internal','寄件人 ：倢瑛'),('forbidden','Ａ／Ｂ／Ｃ'),('forbidden','點數單價')]
    for kind,text in samples:
        hit=E.guard_hit(kind,text)
        exc=reject(conn,'UPDATE outbound_message SET final_body=%s WHERE id=%s',(text,f['out']))
        assert hit in str(exc)
    conn.execute('UPDATE outbound_message SET draft_body=%s WHERE id=%s',('成果如附件',f['out']))


def test_outbound_trigger_entire_text_corpus(conn):
    from test_convergence import fixture,reject
    f=fixture(conn)
    for case in corpus():
        if case['kind'] not in ('internal','forbidden'):
            continue
        conn.execute("UPDATE outbound_message SET subject=NULL,draft_body='成果如附件',final_body=NULL WHERE id=%s",(f['out'],))
        expected=E.check_outbound_body('',case['text'])
        if expected:
            exc=reject(conn,'UPDATE outbound_message SET final_body=%s WHERE id=%s',(case['text'],f['out']))
            assert expected[0].detail in str(exc)
        else:
            conn.execute('UPDATE outbound_message SET draft_body=%s WHERE id=%s',(case['text'],f['out']))


def test_case_constraint_entire_corpus(conn):
    from test_convergence import reject
    for case in corpus():
        if case['kind']!='case_code':continue
        conn.execute('SAVEPOINT corpus_case')
        sql='INSERT INTO "case"(org_id,title,status,case_code) VALUES(\'YX\',\'R31B corpus\',\'contracted\',%s) ON CONFLICT (org_id, case_code) WHERE case_code IS NOT NULL AND status NOT IN (\'merged\', \'void\') DO UPDATE SET case_code = EXCLUDED.case_code'
        if case['expect']:conn.execute(sql,(case['text'],))
        else: assert reject(conn,sql,(case['text'],)).sqlstate=='23514'
        conn.execute('ROLLBACK TO SAVEPOINT corpus_case');conn.execute('RELEASE SAVEPOINT corpus_case')
