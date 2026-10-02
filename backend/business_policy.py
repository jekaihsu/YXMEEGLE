"""Business authority is explicit and independent of the system-admin role."""
ORDINARY_BACKUP_SCOPE = 'company:ordinary_business_backup'


def can_manage_roles(user):
    return bool(user and user.get('active', True) and not user.get('manager_revoked')
                and (user.get('role') == 'manager' or 'manage_roles' in user.get('capabilities', [])))


def can_business_override(user):
    """Ordinary work only; never substitutes a financial/native approval seat.

    _business_authority is rebuilt from server configuration at every load and
    identity lookup. Client actions must never accept this field.
    """
    if not user or not user.get('active', True) or user.get('manager_revoked'):
        return False
    authority = user.get('_business_authority') or {}
    proof = user.get('oauth_identity') or {}
    return bool(authority.get('source') == 'server_company_admin_grant'
                and ORDINARY_BACKUP_SCOPE in authority.get('scopes', [])
                and authority.get('open_id') == user.get('id') == proof.get('open_id')
                and authority.get('app_id') == user.get('identity_app_id') == proof.get('app_id')
                and authority.get('tenant') == proof.get('tenant')
                and proof.get('source') == 'oauth_user_info'
                and authority.get('grant_id') and authority.get('decision_ref'))


def refresh_business_authority(person, cfg):
    from .production_access import company_admin_grant
    person.pop('_business_authority', None)
    grant = company_admin_grant(person, cfg)
    scopes = grant.get('scopes', []) if grant else []
    if grant and isinstance(scopes, list) and all(isinstance(scope, str) for scope in scopes) and ORDINARY_BACKUP_SCOPE in scopes:
        person['_business_authority'] = {
            **{k: grant[k] for k in ('open_id', 'app_id', 'tenant', 'grant_id', 'decision_ref')},
            'source': 'server_company_admin_grant', 'scopes': [ORDINARY_BACKUP_SCOPE],
        }
    return person
