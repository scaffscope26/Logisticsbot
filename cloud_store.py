"""Supabase REST adapter. User tokens authorize reads; only server credentials write.

No credentials are sent to the browser or stored in source control.
"""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class CloudError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class SupabaseStore:
    def __init__(self):
        self.url = os.environ.get('SUPABASE_URL', '').rstrip('/')
        self.key = os.environ.get('SUPABASE_PUBLISHABLE_KEY') or os.environ.get('SUPABASE_ANON_KEY', '')
        self.secret = os.environ.get('SUPABASE_SECRET_KEY') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
        self.workspace = os.environ.get('LOGISTICS_WORKSPACE_ID', '')
        if not all([self.url, self.key, self.secret, self.workspace]):
            raise CloudError('Project setup is incomplete. Configure the Supabase environment and workspace.', 503)
        if not self.url.startswith('https://'):
            raise CloudError('Supabase URL must use HTTPS.')

    def call(self, path, token=None, body=None, privileged=False, method=None):
        key = self.secret if privileged else self.key
        headers = {'apikey': key, 'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        elif privileged and not key.startswith('sb_secret_'):
            headers['Authorization'] = 'Bearer ' + key
        request = Request(self.url + path, headers=headers, method=method,
                          data=json.dumps(body, allow_nan=False).encode() if body is not None else None)
        try:
            with urlopen(request, timeout=20) as response:
                data = response.read()
                return json.loads(data) if data else None
        except HTTPError as error:
            # Never forward infrastructure errors, SQL details, or tokens to users.
            payload = error.read().decode(errors='replace')
            if error.code == 409 or 'stale_revision' in payload:
                raise CloudError('Data changed. Refresh the dashboard and try again.', 409) from None
            if 'approved_commitments' in payload:
                raise CloudError('Resolve the approved commitments before replacing reports.', 409) from None
            if error.code in [401, 403] or 'workspace_access' in payload:
                raise CloudError('Sign in with an account authorized for this workspace.', 403) from None
            if path.startswith('/auth/') and error.code == 400:
                raise CloudError('Sign-in failed. Check your email and password.', 401) from None
            raise CloudError('Supabase could not complete the request. Check project setup and logs.') from None
        except (URLError, TimeoutError):
            raise CloudError('Supabase is temporarily unavailable. Try again shortly.') from None

    def login(self, email, password):
        return self.call('/auth/v1/token?grant_type=password', body={'email': email, 'password': password})

    def recover(self, email):
        return self.call('/auth/v1/recover', body={'email': email})

    def set_password(self, token, password):
        return self.call('/auth/v1/user', token, {'password': password}, method='PUT')

    def user(self, token):
        if not token:
            raise CloudError('Please sign in.', 401)
        return self.call('/auth/v1/user', token)

    def snapshot(self, token):
        return self.call('/rest/v1/rpc/logistics_snapshot', token, {'p_workspace': self.workspace})

    def replace(self, actor, revision, kind, rows, filename):
        return self.call('/rest/v1/rpc/logistics_replace', body={
            'p_workspace': self.workspace, 'p_actor': actor, 'p_revision': revision,
            'p_kind': kind, 'p_rows': rows, 'p_filename': filename}, privileged=True)

    def decide(self, actor, revision, opportunity, status, owner, note, day):
        return self.call('/rest/v1/rpc/logistics_decide', body={
            'p_workspace': self.workspace, 'p_actor': actor, 'p_revision': revision,
            'p_opportunity': opportunity, 'p_status': status, 'p_owner': owner,
            'p_note': note, 'p_day': day}, privileged=True)
