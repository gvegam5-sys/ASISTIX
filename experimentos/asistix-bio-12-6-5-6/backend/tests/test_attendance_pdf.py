import csv
from datetime import datetime
from io import BytesIO, StringIO

import pytest
from pypdf import PdfReader

from test_attendance_filters import courses_with_attendance
from test_flow import client, login
from app import main
from app.attendance_pdf import render_attendance_pdf


PDF = '/reports/attendance.pdf'


def read_pdf(response):
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['content-disposition'] == 'attachment; filename="asistix-asistencia.pdf"'
    pages = PdfReader(BytesIO(response.content)).pages
    return [page.extract_text() for page in pages], pages


@pytest.mark.parametrize(('account', 'title', 'count'), [
    ('admin', 'Reporte institucional de asistencia', 157),
    ('docente', 'Reporte de asistencia de mis materias', 157),
    ('estudiante', 'Mi reporte de asistencia', 21),
])
def test_pdf_matches_history_csv_and_repeats_headers(client, monkeypatch, account, title, count):
    headers = login(client, account)
    monkeypatch.setattr(main, 'now', lambda: datetime(2026, 11, 25, 4, 59, 58))
    user = client.get('/auth/me', headers=headers).json()
    history = client.get('/attendance', headers=headers).json()
    export = client.get('/reports/attendance.csv', headers=headers)
    csv_rows = list(csv.reader(StringIO(export.content.decode('utf-8-sig'))))[1:]
    texts, pages = read_pdf(client.get(PDF, headers=headers))
    assert len(history) == len(csv_rows) == count
    assert sum(page.count('Presente') for page in texts) == count
    assert len(pages) > 1 if count == 157 else len(pages) >= 1
    for index, (page, text) in enumerate(zip(pages, texts), 1):
        assert abs(float(page.mediabox.width) - 595.276) < .1
        assert abs(float(page.mediabox.height) - 841.89) < .1
        assert 'DATOS FICTICIOS · DEMOSTRACIÓN' in text and f'Página {index}' in text
        assert all(label in text for label in ('Estudiante', 'Materia', 'Sesión', 'Fecha', 'Hora', 'Estado'))
    assert title in texts[0] and user['name'] in texts[0]
    assert '24/11/2026 23:59:58' in texts[0]
    assert f'Total de asistencias registradas\n{count}' in texts[0]
    assert [line.strip() for text in texts for line in text.splitlines() if line.strip().isdigit()][1:] == [
        row[2] for row in csv_rows
    ]


def test_pdf_filters_and_permissions(client, courses_with_attendance, monkeypatch):
    first, foreign, _, _ = courses_with_attendance
    assert client.get(PDF).status_code in (401, 403)
    teacher = login(client, 'docente')
    second = login(client, 'docente2')
    student = login(client, 'estudiante')
    for headers, denied in ((teacher, foreign), (second, first), (student, foreign)):
        assert client.get(PDF, headers=headers, params={'course_id': denied}).status_code == 404
    assert client.get(PDF, headers=teacher, params={'date_from': '2035-01-02', 'date_to': '2035-01-01'}).status_code == 422
    params = {'course_id': first, 'date_from': '2035-01-01', 'date_to': '2035-01-01'}
    (text,), _ = read_pdf(client.get(PDF, headers=student, params=params))
    assert 'FILTRO-1 · Materia de filtros' in text
    assert '01/01/2035 al 01/01/2035' in text and '00:00:00' in text
    assert text.count('Presente') == 1 and 'Total de asistencias registradas\n1' in text
    (empty,), _ = read_pdf(client.get(PDF, headers=student, params={**params, 'date_from': '2035-01-03', 'date_to': '2035-01-03'}))
    assert 'No hay registros para los filtros aplicados.' in empty and 'Total de asistencias registradas\n0' in empty
    monkeypatch.setattr('app.attendance_pdf.MAX_PDF_RECORDS', 1)
    assert client.get(PDF, headers=teacher, params=params).status_code == 422


def test_pdf_escapes_text_and_preserves_long_names():
    name = 'María Núñez & <Equipo> ' + ('ApellidoLargo' * 24)
    document = render_attendance_pdf(
        [{'student': name, 'course': 'Diseño & Gestión', 'session_id': 42, 'registered_at': '2026-11-25T05:00:00Z'}],
        role='admin', generated_by='Ana <Ríos> & León', generated_at=datetime(2026, 11, 25, 5),
        demo=False, course='Diseño & Gestión', date_from=None, date_to=None,
    )
    text = PdfReader(BytesIO(document)).pages[0].extract_text()
    assert 'DATOS FICTICIOS' not in text
    assert 'Ana <Ríos> & León' in text and 'Diseño & Gestión' in text
    assert ''.join(name.split()) in ''.join(text.split())
