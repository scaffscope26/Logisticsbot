"""Vercel Flask entrypoint. All operational storage lives in Supabase."""
import base64
import datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from cloud_store import CloudError, SupabaseStore
from engine import SCHEMAS, calculate, parse, validate_import

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 4_000_000
ROOT = Path(__file__).parent
COOKIE = 'logistics_access'
STATUSES = ['Proposed', 'Investigating', 'Approved (internal only)', 'Rejected', 'Completed']


def planning_day():
    return datetime.datetime.now(ZoneInfo('America/New_York')).date()


def store():
    return app.config.get('STORE') or SupabaseStore()


def session():
    adapter = store()
    token = request.cookies.get(COOKIE, '')
    user = adapter.user(token)
    return adapter, token, user


@app.before_request
def same_origin():
    if request.method == 'POST':
        # Required even at login: reject login CSRF and cross-site cookie requests.
        if request.headers.get('Origin') != request.host_url.rstrip('/'):
            raise CloudError('Request must come from this application.', 403)
        if not request.is_json:
            raise CloudError('Use JSON requests.', 415)


@app.after_request
def secure_response(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


@app.errorhandler(CloudError)
def cloud_error(error):
    return jsonify(error=str(error)), error.status


@app.errorhandler(ValueError)
def invalid(error):
    return jsonify(error=str(error)), 400


@app.errorhandler(Exception)
def unexpected(error):
    if isinstance(error, HTTPException):
        return jsonify(error=error.description), error.code
    app.logger.error('Request failed (%s)', type(error).__name__)
    return jsonify(error='Request could not be completed. Check project setup and try again.'), 500


@app.get('/')
def index():
    return send_file(ROOT / 'index.html')


@app.get('/api/health')
def health():
    return jsonify(ok=True, storage='supabase', version='0.2')


@app.post('/api/login')
def login():
    body = request.get_json()
    adapter = store()
    result = adapter.login(str(body.get('email', '')), str(body.get('password', '')))
    # Membership must exist before a session is accepted by this app.
    adapter.snapshot(result['access_token'])
    response = jsonify(ok=True)
    response.set_cookie(COOKIE, result['access_token'], httponly=True,
                        secure=request.is_secure, samesite='Strict',
                        max_age=min(int(result.get('expires_in', 3600)), 3600), path='/')
    return response


@app.post('/api/logout')
def logout():
    response = jsonify(ok=True)
    response.delete_cookie(COOKIE, path='/')
    return response


@app.get('/api/schema')
def schema():
    adapter, token, user = session()
    adapter.snapshot(token)
    return jsonify(SCHEMAS)


def dashboard_result(snapshot):
    today = planning_day()
    result = calculate(snapshot['reports'], today=today)
    decisions = {row['opportunity_id']: row for row in snapshot['decisions']
                 if row['plan_day'] == today.isoformat()}
    for row in result['opportunities']:
        decision = decisions.get(row['id'])
        if decision:
            row.update({key: decision[key] for key in ['status', 'owner', 'note']})
    result.update(revision=snapshot['revision'], plan_day=today.isoformat(),
                  imports=snapshot['imports'], decisions=snapshot['decisions'])
    return result


@app.get('/api/dashboard')
def dashboard():
    adapter, token, user = session()
    result = dashboard_result(adapter.snapshot(token))
    result['email'] = user.get('email', '')
    return jsonify(result)


def upload(body):
    filename = str(body.get('filename', ''))
    try:
        data = base64.b64decode(body.get('data', ''), validate=True)
    except Exception:
        raise ValueError('Invalid file encoding.') from None
    if not data or len(data) > 2_500_000:
        raise ValueError('Choose a CSV or XLSX file up to 2.5 MB.')
    return filename, data


@app.post('/api/preview')
def preview():
    adapter, token, user = session()
    adapter.snapshot(token)
    filename, data = upload(request.get_json())
    rows = parse(data, filename)
    return jsonify(headers=list(rows[0]) if rows else [], preview=rows[:5], count=len(rows))


@app.post('/api/import')
def import_report():
    adapter, token, user = session()
    body = request.get_json()
    filename, data = upload(body)
    result = validate_import(body.get('kind'), data, filename, body.get('mapping', {}))
    if not result['ok']:
        return jsonify(result), 400
    saved = adapter.replace(user['id'], body.get('revision'), body['kind'], result['rows'], filename[:200])
    return jsonify(ok=True, accepted=len(result['rows']), revision=saved['revision'])


@app.post('/api/decision')
def decision():
    adapter, token, user = session()
    body = request.get_json()
    snapshot = adapter.snapshot(token)
    result = dashboard_result(snapshot)
    if body.get('revision') != snapshot['revision'] or body.get('plan_day') != result['plan_day']:
        raise CloudError('Data changed. Refresh before saving a decision.', 409)
    status = body.get('status')
    if status not in STATUSES:
        raise ValueError('Invalid opportunity status.')
    if any(row['opportunity_id'] == body.get('id') and row['status'] == 'Completed'
           for row in snapshot['decisions']):
        raise ValueError('This movement is complete. Import refreshed reports before planning it again.')
    opportunity = next((row for row in result['opportunities']
                        if row['id'] == body.get('id') and row['source_type'] != 'shortage'), None)
    previous = next((row for row in snapshot['decisions']
                     if row['opportunity_id'] == body.get('id') and row['status'] == 'Approved (internal only)'), None)
    # An approval from an earlier day must still be releasable even if its proposal expired.
    if previous and previous['plan_day'] != result['plan_day']:
        if status not in ['Rejected', 'Completed']:
            raise ValueError('Resolve the earlier approval as Completed or Rejected.')
        opportunity = previous['opportunity']
    if opportunity is None:
        raise ValueError('Opportunity is no longer available. Refresh the dashboard.')
    if status == 'Approved (internal only)' and not body.get('confirmed'):
        raise ValueError('Confirm availability, inspection, transport, and Quantify commitments first.')
    adapter.decide(user['id'], snapshot['revision'], opportunity, status,
                   str(body.get('owner', ''))[:200], str(body.get('note', ''))[:2000], result['plan_day'])
    return jsonify(ok=True)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8765)
