"""Logical reports fingerprint on a common fixed fixture for cross-engine comparison."""
import csv
from datetime import datetime
from hashlib import sha256
from io import StringIO
import json

from app import main
from test_attendance_filters import courses_with_attendance
from test_attendance_pdf import PDF, read_pdf
from test_attendance_xlsx import XLSX, read_sheet
from test_flow import login


def test_logical_report_fingerprint(client, courses_with_attendance, monkeypatch):
    course, _, _, _ = courses_with_attendance
    monkeypatch.setattr(main, 'now', lambda: datetime(2035, 1, 2, 12))
    payload = []
    params = {'course_id': course, 'date_from': '2035-01-01', 'date_to': '2035-01-01'}
    for role in ('admin', 'docente', 'estudiante'):
        headers = login(client, role)
        response = client.get('/reports/attendance.csv', headers=headers, params=params)
        assert response.status_code == 200
        rows = list(csv.reader(StringIO(response.content.decode('utf-8-sig'))))
        assert len(rows) > 1
        pages, _ = read_pdf(client.get(PDF, headers=headers, params=params))
        sheet = read_sheet(client.get(XLSX, headers=headers, params=params))
        payload.append((rows, pages, list(sheet.values)))
    encoded = json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8')
    print('REPORT_PARITY', sha256(encoded).hexdigest(), flush=True)
