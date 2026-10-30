"""Binds delivery dispatch to a consumed domain approval (mock/local only).

Authorization to dispatch an approval-gated command comes from the domain's consumed approval record, never from the
mere presence of an `approval_ref` string. `verify` reads the `domain` and `approval_bindings` keys of the same
`ops_sync` namespace the engine already transacts on, so the check and the state change it guards commit atomically
under the store's version CAS: no second lock, hence no lock-order to get wrong.

An approval is single-use: the first command that verifies against it is recorded in `approval_bindings[ref]`, and any
other command presenting the same ref is refused. The binding is kept when that command later fails, because the
approved baseline may no longer hold; a new proposal and approval are required.
"""
CONSUMED = 'confirmed'
NOT_CONSUMED, MISMATCH, ALREADY_BOUND, NOT_BOUND = 'approval_not_consumed', 'approval_mismatch', 'approval_already_bound', 'approval_not_bound'


def consumed_proposal(ns, entity_id, ref):
    """The domain proposal that consumed receipt `ref` for `entity_id`, or None."""
    dom = ns.get('domain') or {}
    rec = (dom.get('cases') or {}).get(entity_id) or (dom.get('nodes') or {}).get(entity_id)
    if not rec or not ref:
        return None
    dl = rec.get('deadline') or {}
    ledger = (dl.get('receipts') or {}).get(ref)
    if not ledger or (ledger.get('result') or {}).get('status') != CONSUMED:
        return None
    for prop in (dl.get('proposals') or {}).values():
        if prop.get('receipt_id') == ref and prop.get('state') == CONSUMED:
            return prop
    return None


def verify(ns, env, require_bound):
    """Reason the command may NOT use its approval, or None. `env` is the stored command envelope."""
    ref, command_id = env.get('approval_ref'), env['command_id']
    prop = consumed_proposal(ns, env['entity_id'], ref)
    if prop is None:
        return NOT_CONSUMED
    if prop['field_id'] != env['field_id'] or prop['intended'] != env['intended']:
        return MISMATCH
    bound = (ns.get('approval_bindings') or {}).get(ref)
    if bound is not None and bound != command_id:
        return ALREADY_BOUND
    if require_bound and bound != command_id:
        return NOT_BOUND
    return None


def bind(ns, env):
    ns.setdefault('approval_bindings', {})[env['approval_ref']] = env['command_id']
