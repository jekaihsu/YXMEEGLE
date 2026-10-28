#!/usr/bin/env python3
"""Fill the R47 run from already-ingested genuine email rows. Never generate mail."""
from r47_launch import connection, RUN

def enroll(conn):
    conn.execute('SELECT id FROM annotation_run WHERE id=%s FOR UPDATE',(RUN,))
    if conn.execute('SELECT 1 FROM annotation_sample s JOIN switchboard_gold_label g USING(sample_id) WHERE run_id=%s AND (g.label_a IS NOT NULL OR g.label_b IS NOT NULL) LIMIT 1',(RUN,)).fetchone():
        raise RuntimeError('Cannot change a cohort once labeling starts; use a new run')
    candidates=conn.execute('''SELECT m.message_id FROM email_message m WHERE m.message_id IS NOT NULL AND m.body_new_text IS NOT NULL
      AND NOT EXISTS(SELECT 1 FROM switchboard_gold_label g WHERE g.message_id=m.message_id)
      ORDER BY md5(m.message_id)''').fetchall()
    n=conn.execute('SELECT count(*) n FROM annotation_sample WHERE run_id=%s',(RUN,)).fetchone()['n']
    if len(candidates)+n<200:raise RuntimeError(f'Need {200-n} additional ingested emails; only {len(candidates)} available. Nothing changed.')
    people=conn.execute("SELECT role,employee_id FROM annotation_assignment WHERE run_id=%s AND role IN ('a','b')",(RUN,)).fetchall();people={r['role']:r['employee_id'] for r in people}
    import hashlib
    for row in candidates[:200-n]:
        sample='R47-'+hashlib.sha256(row['message_id'].encode()).hexdigest()
        conn.execute("INSERT INTO switchboard_gold_label(sample_id,message_id,source_channel,stratum,annotator_a_employee_id,annotator_b_employee_id) VALUES(%s,%s,'email','unlabeled',%s,%s)",(sample,row['message_id'],people['a'],people['b']))
        conn.execute('INSERT INTO annotation_sample VALUES(%s,%s)',(RUN,sample))
    return 200

if __name__=='__main__':
    with connection() as conn:print(enroll(conn))
