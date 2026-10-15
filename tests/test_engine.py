import datetime
import io
import tempfile
import unittest
from pathlib import Path
from openpyxl import Workbook
import engine


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db = engine.DB
        engine.DB = Path(self.tmp.name) / 'test.db'

    def tearDown(self):
        engine.DB = self.original_db
        self.tmp.cleanup()

    def ingest(self, kind, rows):
        fields = engine.SCHEMAS[kind]
        import csv
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerows(rows)
        return engine.ingest(kind, stream.getvalue().encode(), 'test.csv', {f: f for f in fields})

    def test_sample_matching(self):
        root = Path(__file__).resolve().parents[1]
        for kind, fields in engine.SCHEMAS.items():
            rows = engine.parse((root / 'sample_data' / (kind + '.csv')).read_bytes(), kind + '.csv')
            shift = datetime.date.today() - datetime.date(2026, 10, 14)
            for row in rows:
                for field in fields:
                    if field.endswith('_date'):
                        row[field] = (datetime.date.fromisoformat(row[field]) + shift).isoformat()
            result = self.ingest(kind, [[row[f] for f in fields] for row in rows])
            self.assertTrue(result['ok'])
        result = engine.matches()
        self.assertEqual(result['summary']['matches'], 5)
        self.assertEqual(result['summary']['shortages'], 0)

    def test_invalid_snapshot_preserves_previous_import(self):
        self.assertTrue(self.ingest('inventory', [['Orlando', 'P1', 'Frame', 10]])['ok'])
        self.assertFalse(self.ingest('inventory', [['Orlando', 'P1', 'Frame', -1]])['ok'])
        self.assertEqual(engine.records('inventory')[0]['quantity_available'], 10)

    def test_no_double_allocation_or_forecast_allocation(self):
        due = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
        self.ingest('inventory', [['Orlando', 'P1', 'Frame', 10]])
        self.ingest('projects', [['J1', 'Customer', 'Orlando', 'P1', 100, due]])
        self.ingest('reservations', [['R1', 'Orlando', 'P1', 8, due], ['R2', 'Orlando', 'P1', 8, due]])
        result = engine.matches()
        self.assertEqual(sum(r['quantity'] for r in result['opportunities'] if r['source_type'] != 'shortage'), 10)
        self.assertEqual(sum(r['quantity'] for r in result['opportunities'] if r['source_type'] == 'shortage'), 6)
        self.assertEqual(len(result['forecast']), 1)

    def test_return_inspection_delay(self):
        today = datetime.date.today()
        self.ingest('returns', [['J1', 'Orlando', 'P1', 10, today.isoformat()]])
        self.ingest('reservations', [['R1', 'Orlando', 'P1', 10, (today + datetime.timedelta(days=1)).isoformat()]])
        self.assertEqual(engine.matches()['summary']['shortages'], 1)

    def test_excel_dates_and_part_numbers(self):
        wb = Workbook()
        wb.active.append(engine.SCHEMAS['reservations'])
        wb.active.append(['R1', 'Orlando', '00123', 10, datetime.datetime(2026, 10, 20)])
        stream = io.BytesIO()
        wb.save(stream)
        fields = engine.SCHEMAS['reservations']
        self.assertTrue(engine.ingest('reservations', stream.getvalue(), 'test.xlsx', {f: f for f in fields})['ok'])
        row = engine.records('reservations')[0]
        self.assertEqual(row['part_number'], '00123')
        self.assertEqual(row['required_date'], '2026-10-20')

    def test_decision_persists(self):
        due = datetime.date.today().isoformat()
        self.ingest('inventory', [['Orlando', 'P1', 'Frame', 10]])
        self.ingest('reservations', [['R1', 'Orlando', 'P1', 10, due]])
        oid = engine.matches()['opportunities'][0]['id']
        engine.decision(oid, 'Investigating', 'Owner', 'Check availability')
        self.assertEqual(engine.matches()['opportunities'][0]['status'], 'Investigating')

    def test_opportunity_identity_survives_supply_reordering(self):
        due = datetime.date.today().isoformat()
        rows = [['Orlando', 'P1', 'Frame', 10], ['Tampa', 'P1', 'Frame', 10]]
        self.ingest('inventory', rows)
        self.ingest('reservations', [['R1', 'Orlando', 'P1', 10, due]])
        before = engine.matches()['opportunities']
        self.ingest('inventory', list(reversed(rows)))
        self.assertEqual(before, engine.matches()['opportunities'])

    def test_nonfinite_and_duplicate_quantities_rejected(self):
        for value in ['NaN', 'Infinity', '-Infinity']:
            self.assertFalse(self.ingest('inventory', [['Orlando', 'P1', 'Frame', value]])['ok'])
        self.assertFalse(self.ingest('inventory', [['Orlando', 'P1', 'Frame', 1]] * 2)['ok'])

    def test_overdue_return_is_not_assumed_received(self):
        today = datetime.date.today()
        self.ingest('returns', [['J1', 'Orlando', 'P1', 10, (today - datetime.timedelta(days=3)).isoformat()]])
        self.ingest('reservations', [['R1', 'Orlando', 'P1', 10, today.isoformat()]])
        self.assertEqual(engine.matches()['summary']['shortages'], 1)


if __name__ == '__main__':
    unittest.main()
