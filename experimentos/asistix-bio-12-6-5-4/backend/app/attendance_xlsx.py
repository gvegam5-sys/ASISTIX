from datetime import datetime, timezone
from io import BytesIO
from threading import Lock

from xlsxwriter import Workbook

from .reporting_time import REPORTING_ZONE


XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
MAX_XLSX_RECORDS = 10_000
XLSX_SLOT = Lock()
TITLES = {
    'admin': 'Reporte institucional de asistencia',
    'teacher': 'Reporte de asistencia de mis materias',
    'student': 'Mi reporte de asistencia',
}
NAVY = '#12274B'
TEAL = '#28B9A6'


def local_time(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(REPORTING_ZONE)


def period_label(first, last):
    if first and last:
        return f'{first:%d/%m/%Y} al {last:%d/%m/%Y}'
    if first:
        return f'Desde el {first:%d/%m/%Y}'
    if last:
        return f'Hasta el {last:%d/%m/%Y}'
    return 'Todo el periodo'


def render_attendance_xlsx(rows, *, role, generated_by, generated_at, demo, course, date_from, date_to):
    output = BytesIO()
    with Workbook(output, {
        'in_memory': True, 'strings_to_formulas': False,
        'strings_to_urls': False, 'strings_to_numbers': False,
    }) as book:
        book.set_properties({'title': TITLES[role], 'author': 'ASISTIX'})
        sheet = book.add_worksheet('Asistencias')
        sheet.hide_gridlines(2)
        sheet.set_tab_color(TEAL)
        for col, width in enumerate((34, 42, 12, 15, 14, 16)):
            sheet.set_column(col, col, width)

        logo = book.add_format({'bg_color': NAVY, 'font_color': TEAL, 'bold': True, 'font_size': 17, 'valign': 'vcenter'})
        title = book.add_format({'bg_color': NAVY, 'font_color': '#FFFFFF', 'bold': True, 'font_size': 14, 'valign': 'vcenter'})
        accent = book.add_format({'bg_color': '#E5F7F4', 'font_color': NAVY, 'bold': True})
        label = book.add_format({'font_color': NAVY, 'bold': True, 'valign': 'top'})
        detail = book.add_format({'font_color': NAVY, 'text_wrap': True, 'valign': 'top'})
        header = book.add_format({'bg_color': NAVY, 'font_color': '#FFFFFF', 'bold': True, 'valign': 'vcenter'})

        def merged_text(row, first, last, value, style):
            sheet.merge_range(row, first, row, last, '', style)
            sheet.write_string(row, first, value, style)

        sheet.set_row(0, 32)
        sheet.write_string(0, 0, 'ASISTIX', logo)
        merged_text(0, 1, 5, TITLES[role], title)
        if demo:
            merged_text(1, 0, 5, 'DATOS FICTICIOS · DEMOSTRACIÓN', accent)
        generated = local_time(generated_at)
        for index, (key, value) in enumerate((
            ('Generado por', generated_by),
            ('Fecha y hora de generación', f'{generated:%d/%m/%Y %H:%M:%S} · Ecuador continental'),
            ('Materia', course or 'Todas las materias del alcance'),
            ('Periodo', period_label(date_from, date_to)),
        ), 2):
            sheet.write_string(index, 0, key, label)
            merged_text(index, 1, 5, value, detail)
            sheet.set_row(index, 30)
        sheet.write_string(6, 0, 'Total de asistencias registradas', accent)
        sheet.write_number(6, 1, len(rows), accent)

        header_row = 8
        sheet.set_row(header_row, 24)
        for col, value in enumerate(('Estudiante', 'Materia', 'Sesión', 'Fecha', 'Hora', 'Estado')):
            sheet.write_string(header_row, col, value, header)
        sheet.freeze_panes(header_row + 1, 0)
        sheet.autofilter(header_row, 0, header_row + len(rows), 5)
        formats = []
        for background in ('#FFFFFF', '#F3F7FB'):
            base = {'bg_color': background, 'valign': 'top', 'font_color': NAVY}
            formats.append((
                book.add_format({**base, 'text_wrap': True}), book.add_format(base),
                book.add_format({**base, 'num_format': 'dd/mm/yyyy'}),
                book.add_format({**base, 'num_format': 'hh:mm:ss'}),
            ))
        for index, row in enumerate(rows):
            target = header_row + 1 + index
            text, number, day, hour = formats[index % 2]
            stamp = local_time(datetime.fromisoformat(row['registered_at']))
            sheet.write_string(target, 0, row['student'], text)
            sheet.write_string(target, 1, row['course'], text)
            sheet.write_number(target, 2, row['session_id'], number)
            sheet.write_datetime(target, 3, stamp.date(), day)
            sheet.write_datetime(target, 4, stamp.time().replace(microsecond=0), hour)
            sheet.write_string(target, 5, 'Presente', text)
        if not rows:
            merged_text(header_row + 2, 0, 5, 'No hay registros para los filtros aplicados.', detail)
    return output.getvalue()
