import base64
import copy
import unittest

from app import app, planning_day
from cloud_store import CloudError


class FakeStore:
    def __init__(self):
        self.data = {'revision': 1, 'reports': {}, 'imports': {}, 'decisions': []}
        self.saved = None

    def user(self, token):
        if token != 'valid-token':
            raise CloudError('Please sign in.', 401)
        return {'id': 'test-user', 'email': 'test@example.com'}

    def login(self, email, password):
        if password != 'correct':
            raise CloudError('Sign-in failed.', 401)
        return {'access_token': 'valid-token', 'expires_in': 3600}

    def snapshot(self, token):
        self.user(token)
        return copy.deepcopy(self.data)

    def replace(self, actor, revision, kind, rows, filename):
        if revision != self.data['revision']:
            raise CloudError('Data changed.', 409)
        self.data['reports'][kind] = rows
        self.data['revision'] += 1
        return {'revision': self.data['revision']}

    def decide(self, *args):
        self.saved = args


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        app.config.update(TESTING=True, STORE=self.store)
        self.client = app.test_client()

    def tearDown(self):
        app.config.pop('STORE', None)

    def post(self, path, body):
        return self.client.post('/api/' + path, json=body, headers={'Origin': 'http://localhost'})

    def login(self):
        response = self.post('login', {'email': 'test@example.com', 'password': 'correct'})
        self.assertEqual(response.status_code, 200)
        return response

    def seed(self):
        self.store.data['reports'] = {
            'inventory': [{'facility': 'Orlando', 'part_number': 'P1', 'quantity_available': 10}],
            'reservations': [{'reservation_id': 'R1', 'facility': 'Orlando', 'part_number': 'P1',
                              'quantity_required': 10, 'required_date': planning_day().isoformat()}]}

    def test_authentication_and_cookie(self):
        self.assertEqual(self.client.get('/api/dashboard').status_code, 401)
        response = self.login()
        cookie = response.headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)
        self.assertEqual(self.client.get('/api/dashboard').status_code, 200)
        self.assertEqual(self.post('logout', {}).status_code, 200)
        self.assertEqual(self.client.get('/api/dashboard').status_code, 401)

    def test_csrf_rejected_including_login(self):
        response = self.client.post('/api/login', json={}, headers={'Origin': 'https://attacker.example'})
        self.assertEqual(response.status_code, 403)

    def test_import_persists_cloud_snapshot_and_checks_revision(self):
        self.login()
        body = {'kind': 'inventory', 'filename': 'inventory.csv', 'revision': 1,
                'data': base64.b64encode(b'facility,part_number,description,quantity_available\nOrlando,P1,Frame,10\n').decode(),
                'mapping': {f: f for f in ['facility', 'part_number', 'description', 'quantity_available']}}
        self.assertEqual(self.post('import', body).status_code, 200)
        self.assertEqual(self.post('import', body).status_code, 409)
        self.assertEqual(self.client.get('/api/dashboard').json['summary']['inventory_rows'], 1)

    def test_approval_requires_current_revision_and_confirmation(self):
        self.login()
        self.seed()
        dashboard = self.client.get('/api/dashboard').json
        body = {'id': dashboard['opportunities'][0]['id'], 'status': 'Approved (internal only)',
                'plan_day': dashboard['plan_day'], 'revision': 0}
        self.assertEqual(self.post('decision', body).status_code, 409)
        body['revision'] = 1
        self.assertEqual(self.post('decision', body).status_code, 400)
        body['confirmed'] = True
        self.assertEqual(self.post('decision', body).status_code, 200)
        self.assertEqual(self.store.saved[2]['quantity'], 10)

    def test_unknown_opportunity_rejected(self):
        self.login()
        body = {'id': 'invented', 'status': 'Investigating', 'revision': 1,
                'plan_day': planning_day().isoformat()}
        self.assertEqual(self.post('decision', body).status_code, 400)

    def test_only_allowlisted_files_are_served(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/.env').status_code, 404)
        self.assertEqual(self.client.get('/engine.py').status_code, 404)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        response.close()
