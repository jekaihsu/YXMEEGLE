"""Prevent partial replacement of the workbench's Zeabur environment."""
import re

APP_SERVICE='6ab61834a4c05a5bcb57ad69'
REQUIRED_KEYS=frozenset({'APP_ENV','DATABASE_URL','SESSION_SECRET','UPLOAD_DIR','PORT',
    'PUBLIC_ORIGIN','DEMO_MODE','LARK_APP_ID','LARK_APP_SECRET','LARK_ALLOWED_TENANTS',
    'LARK_REDIRECT_URI','LARK_ROLE_MAP_JSON','LARK_SOURCE_TABLES_JSON'})


def validate_environment(values):
    if not isinstance(values,dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in values.items()):
        raise ValueError('Environment must be a complete string map')
    if any(not values.get(key,'').strip() for key in REQUIRED_KEYS):
        raise ValueError('Complete environment is missing required nonempty settings')
    if not values['DATABASE_URL'].startswith(('postgresql://','postgresql+psycopg://','postgres://')):
        raise ValueError('Application environment requires PostgreSQL')
    if len(values['SESSION_SECRET'])<32:
        raise ValueError('Application session secret is too short')
    if values['DEMO_MODE'].lower()=='true' and values.get('ALLOW_CLOUD_DEMO','').lower()!='true':
        raise ValueError('Cloud demo requires its explicit allow setting')
    return values


def validate_request(request):
    query=request.get('query','')
    if 'updateEnvironmentVariable' not in query: return
    variables=request.get('variables',{})
    calls=re.findall(r'\bupdateEnvironmentVariable\s*\(([^)]*)\)',query)
    if not calls: raise ValueError('Environment update could not be validated')
    for call in calls:
        service=re.search(r'\bserviceID\s*:\s*\$(\w+)',call)
        data=re.search(r'\bdata\s*:\s*\$(\w+)',call)
        if not service or not data:
            raise ValueError('Environment updates require explicit service and data variables')
        if variables.get(service[1])!=APP_SERVICE:
            raise ValueError('Environment replacement for this service is not reviewed by this repository')
        validate_environment(variables.get(data[1]))
