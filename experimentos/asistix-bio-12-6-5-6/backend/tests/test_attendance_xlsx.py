import csv
from datetime import datetime, time
from io import BytesIO, StringIO
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook

from test_attendance_filters import courses_with_attendance
from test_flow import client, login
from app import main
from app.attendance_xlsx import XLSX_MIME, render_attendance_xlsx
from app.reporting_time import REPORTING_ZONE


XLSX = '/reports/attendance.xlsx'
HEADERS = ('Estudiante', 'Materia', 'Sesión', 'Fecha', 'Hora', 'Estado')


def read_sheet(response):
    assert response.status_code == 200
    assert response.headers['content-type'] == XLSX_MIME
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['content-disposition'] == 'attachment; filename="asistix-asistencia.xlsx"'
    return load_workbook(BytesIO(response.content)).active


def assert_rows(sheet, history):
    assert sheet['B7'].value == len(history)
    assert tuple(cell.value for cell in sheet[9]) == HEADERS
    assert sheet.freeze_panes == 'A10'
    assert sheet.auto_filter.ref == f'A9:F{9 + len(history)}'
    for index, row in enumerate(history, 10):
        local = datetime.fromisoformat(row['registered_at']).astimezone(REPORTING_ZONE)
        assert tuple(cell.value for cell in sheet[index]) == (
            row['student'], row['course'], row['session_id'], datetime.combine(local.date(), time.min),
            local.time().replace(microsecond=0), 'Presente',
        )
        assert sheet[f'A{index}'].data_type == 's'
        assert sheet[f'C{index}'].data_type == 'n'
        assert sheet[f'D{index}'].number_format == 'dd/mm/yyyy'
        assert sheet[f'E{index}'].number_format == 'hh:mm:ss'


@pytest.mark.parametrize(('account', 'title', 'count'), [
    ('admin', 'Reporte institucional de asistencia', 157),
    ('docente', 'Reporte de asistencia de mis materias', 157),
    ('estudiante', 'Mi reporte de asistencia', 21),
])
def test_unfiltered_excel_matches_history_and_csv(client, monkeypatch, account, title, count):
    headers = login(client, account)
    user = client.get('/auth/me', headers=headers).json()
    history = client.get('/attendance', headers=headers).json()
    csv_response = client.get('/reports/attendance.csv', headers=headers)
    csv_rows = list(csv.reader(StringIO(csv_response.content.decode('utf-8-sig'))))[1:]
    assert csv_rows == [[r['student'], r['course'], str(r['session_id']), r['registered_at']] for r in history]
    assert len(history) == count
    monkeypatch.setattr(main, 'now', lambda: datetime(2026, 11, 25, 4, 59, 58))
    sheet = read_sheet(client.get(XLSX, headers=headers))
    assert sheet['A1'].value == 'ASISTIX' and sheet['B1'].value == title
    assert sheet['A2'].value == 'DATOS FICTICIOS · DEMOSTRACIÓN'
    assert sheet['B3'].value == user['name']
    assert sheet['B4'].value == '24/11/2026 23:59:58 · Ecuador continental'
    assert sheet['A9'].fill.fgColor.rgb.endswith('12274B')
    assert sheet['A10'].fill.fgColor.rgb != sheet['A11'].fill.fgColor.rgb
    assert sheet['A10'].alignment.wrap_text
    assert sheet.max_row == count + 9
    assert_rows(sheet, history)


def test_excel_permissions_dates_and_empty(client, courses_with_attendance, monkeypatch):
    own, foreign, _, student_id = courses_with_attendance
    assert client.get(XLSX).status_code in (401, 403)
    teacher, second, student = (login(client, name) for name in ('docente', 'docente2', 'estudiante'))
    for headers, denied in ((teacher, foreign), (second, own), (student, foreign)):
        assert client.get(XLSX, headers=headers, params={'course_id': denied}).status_code == 404
    invalid = {'date_from': '2035-01-02', 'date_to': '2035-01-01'}
    assert client.get(XLSX, headers=student, params=invalid).status_code == 422
    filters = {'course_id': own, 'date_from': '2035-01-01', 'date_to': '2035-01-01'}
    history = client.get('/attendance', headers=student, params=filters).json()
    assert len(history) == 1 and history[0]['student_id'] == student_id
    sheet = read_sheet(client.get(XLSX, headers=student, params=filters))
    assert_rows(sheet, history)
    assert sheet['B5'].value == 'FILTRO-1 · Materia de filtros'
    assert sheet['B6'].value == '01/01/2035 al 01/01/2035'
    assert sheet['D10'].value == datetime(2035, 1, 1) and sheet['E10'].value == time.min
    empty = read_sheet(client.get(XLSX, headers=student, params={'date_from': '2099-01-01'}))
    assert_rows(empty, [])
    assert empty['A11'].value == 'No hay registros para los filtros aplicados.'
    monkeypatch.setattr('app.attendance_xlsx.MAX_XLSX_RECORDS', 1)
    assert client.get(XLSX, headers=teacher, params=filters).status_code == 422


def test_excel_keeps_external_text_literal_and_contains_no_formula_or_link():
    names = ['=1+1', '+1', '-1', '@nombre', '\t=1+1', '＝1', 'María Núñez & <Equipo> ' + 'ApellidoLargo' * 24]
    document = render_attendance_xlsx([
        {'student': name, 'course': 'https://example.test', 'session_id': 123, 'registered_at': '2026-11-25T05:00:00Z'}
        for name in names
    ], role='admin', generated_by='=2+2', generated_at=datetime(2026, 11, 25, 5), demo=False,
       course='Diseño & Gestión', date_from=None, date_to=None)
    assert document.startswith(b'PK')
    sheet = load_workbook(BytesIO(document)).active
    assert sheet['A2'].value is None
    assert sheet['B3'].value == '=2+2' and sheet['B3'].data_type == 's'
    assert [sheet[f'A{i}'].value for i in range(10, 10 + len(names))] == names
    for row in sheet:
        assert all(cell.data_type != 'f' and not cell.hyperlink for cell in row)
    with ZipFile(BytesIO(document)) as archive:
        assert not any('externallink' in name.lower() or 'vbaproject' in name.lower() for name in archive.namelist())
        assert not any(b'TargetMode="External"' in archive.read(name) for name in archive.namelist() if name.endswith('.rels'))
