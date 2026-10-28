"""Stable read-only owner ledger contract shared by the PM workspaces.

The R50 workflow state has its own finalization and telemetry schema. Keep the
owner ledger projection explicit so workflow extensions cannot overwrite it.
"""
import json
from lark_cli_watcher_agent import sql, literal


def snapshot(case_code=None):
    where = (' WHERE case_code=' + literal(case_code)) if case_code else ''
    raw = sql(f"""SELECT jsonb_build_object(
      'ok',true,'mode','SANDBOX_LOOPBACK',
      'trigger_architecture','EVENT_DRIVEN_INBOX_WEBHOOK',
      'external_messages_sent',(SELECT coalesce(sum(actual_sends),0) FROM public.outbound_message),
      'usage',coalesce((SELECT jsonb_agg(to_jsonb(t)) FROM (
        SELECT * FROM colleague_agent_usage_summary_v ORDER BY total_interactions DESC,employee_name
      ) t),'[]'::jsonb),
      'records',coalesce((SELECT jsonb_agg(to_jsonb(t)) FROM (
        SELECT * FROM pm_solution_owner_comm_v{where} ORDER BY jk_final_sent_at DESC NULLS LAST
      ) t),'[]'::jsonb),
      'watcher',coalesce((SELECT jsonb_agg(to_jsonb(t)) FROM (
        SELECT *, (now()-last_poll_at < interval '60 seconds') AS alive
        FROM r50_lark_watcher_heartbeat ORDER BY last_poll_at DESC
      ) t),'[]'::jsonb)
    );""", readonly=True)
    return json.loads(raw.splitlines()[-1])
