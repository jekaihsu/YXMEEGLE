"""As-of inbound routing. Historical evidence is text observed strictly earlier.

This path deliberately cannot read stored classifications, case links, backfill,
ledger, gold labels, or present-day business tables. Rule configuration is frozen
code; it is not historical truth. received_at is required, never replaced by now.
"""
from dataclasses import asdict
from datetime import datetime
from switchboard_engine import classify_inbound_email, extract_case_code, INTERNAL_MAILBOXES


def timestamp(value):
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not dt or dt.tzinfo is None:
        raise ValueError('An observed timezone-aware received_at is required')
    return dt


def related(m, h):
    mids = {m.get('message_id'), *(m.get('references') or []), m.get('in_reply_to')}
    hids = {h.get('message_id'), *(h.get('references') or []), h.get('in_reply_to')}
    return bool((mids - {None, ''}) & (hids - {None, ''}))


def predict_from_history(message, history):
    cutoff = timestamp(message['received_at'])
    # Defense in depth for alternate stores and explicit exclusion of equal times.
    history = [h for h in history if timestamp(h['received_at']) < cutoff]
    r = classify_inbound_email(message.get('from_addr',''), message.get('to_addrs') or [],
        message.get('subject') or '',message.get('body_new_text') or message.get('body_text') or '',
        dkim_pass=bool(message.get('dkim_pass')),spf_pass=bool(message.get('spf_pass')),
        dkim_domain=message.get('dkim_domain'))
    out = asdict(r)
    evidence = sorted([h for h in history if related(message,h)],key=lambda h:timestamp(h['received_at']),reverse=True)
    if not out['case_ref']:
        candidates={extract_case_code((h.get('subject') or '')+' '+(h.get('body_new_text') or '')) for h in evidence}
        candidates.discard(None)
        if len(candidates)==1: out['case_ref']=next(iter(candidates))
    out.update(history_N=len(history), history_max_received_at=max((timestamp(h['received_at']).isoformat() for h in history),default=None),
               related_history_ids=[h['message_id'] for h in evidence],cutoff=cutoff.isoformat())
    # A quarantine review is useful containment, but cannot count as successful
    # business-card recall: otherwise quarantining every email scores 100%.
    out['emit_quarantine_card'] = bool(out['quarantine_reason'])
    out['emit_card'] = not out['quarantine_reason'] and out['category'] in ('CAT-01','CAT-02','CAT-03','CAT-04','CAT-05','CAT-06','CAT-07','CAT-08')
    return out


class TemporalRouter:
    def __init__(self, connection):
        self.connection=connection

    def predict(self, message):
        from psycopg.rows import dict_row
        cutoff=timestamp(message['received_at'])
        with self.connection.cursor(row_factory=dict_row) as cur:
            cur.execute('''select message_id, "references", in_reply_to, received_at,
                from_addr, to_addrs, subject, body_new_text, body_text,
                dkim_pass, spf_pass, dkim_domain
                from public.email_message where received_at < %s
                order by received_at,message_id''',(cutoff,))
            return predict_from_history(message, cur.fetchall())
