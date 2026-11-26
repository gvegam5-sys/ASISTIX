from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import Lock
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .reporting_time import REPORTING_ZONE


MAX_PDF_RECORDS = 2_000
TITLES = {
    'admin': 'Reporte institucional de asistencia',
    'teacher': 'Reporte de asistencia de mis materias',
    'student': 'Mi reporte de asistencia',
}
NAVY = colors.HexColor('#12274B')
TEAL = colors.HexColor('#28B9A6')
MUTED = colors.HexColor('#4A607D')
PALE = colors.HexColor('#F3F7FB')
LINE = colors.HexColor('#DCE5EF')
WHITE = colors.white
REGULAR = 'AsistixNotoSans'
BOLD = 'AsistixNotoSansBold'
FONT_DIR = Path(__file__).with_name('assets')
FONT_LOCK = Lock()
PDF_SLOT = Lock()


def register_fonts():
    with FONT_LOCK:
        if BOLD not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(REGULAR, str(FONT_DIR / 'NotoSans-Regular.ttf')))
            pdfmetrics.registerFont(TTFont(BOLD, str(FONT_DIR / 'NotoSans-Bold.ttf')))


def local_time(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(REPORTING_ZONE)


def period_label(first: date | None, last: date | None) -> str:
    if first and last:
        return f'{first:%d/%m/%Y} al {last:%d/%m/%Y}'
    if first:
        return f'Desde el {first:%d/%m/%Y}'
    if last:
        return f'Hasta el {last:%d/%m/%Y}'
    return 'Todo el periodo'


def draw_page(canvas, doc, demo: bool):
    width, height = A4
    left, right = doc.leftMargin, width - doc.rightMargin
    top = height - 19 * mm
    canvas.setFillColor(NAVY)
    canvas.roundRect(left, top, 8 * mm, 8 * mm, 1.5 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(TEAL)
    canvas.setLineWidth(1)
    for x, y, dx, dy in ((2, 2, 1, 1), (6, 2, -1, 1), (2, 6, 1, -1), (6, 6, -1, -1)):
        cx, cy = left + x * mm, top + y * mm
        canvas.line(cx, cy, cx + dx * mm, cy)
        canvas.line(cx, cy, cx, cy + dy * mm)
    canvas.line(left + 2.5 * mm, top + 4 * mm, left + 5.5 * mm, top + 4 * mm)
    canvas.setFont(BOLD, 14)
    canvas.drawString(left + 10 * mm, top + 2 * mm, 'ASIST')
    canvas.setFillColor(TEAL)
    canvas.drawString(left + 10 * mm + pdfmetrics.stringWidth('ASIST', BOLD, 14), top + 2 * mm, 'IX')
    canvas.setFillColor(MUTED)
    canvas.setFont(BOLD, 8)
    if demo:
        canvas.drawRightString(right, top + 2.6 * mm, 'DATOS FICTICIOS · DEMOSTRACIÓN')
    canvas.setStrokeColor(LINE)
    canvas.line(left, top - 3 * mm, right, top - 3 * mm)
    canvas.line(left, 14 * mm, right, 14 * mm)
    canvas.setFont(REGULAR, 8)
    canvas.drawString(left, 9 * mm, 'ASISTIX · Sistema institucional de asistencia')
    canvas.drawRightString(right, 9 * mm, f'Página {doc.page}')


def render_attendance_pdf(
    rows, *, role: str, generated_by: str, generated_at: datetime, demo: bool,
    course: str | None, date_from: date | None, date_to: date | None,
) -> bytes:
    register_fonts()
    output = BytesIO()
    title = TITLES[role]
    doc = SimpleDocTemplate(
        output, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=28 * mm, bottomMargin=19 * mm, title=title, author='ASISTIX',
    )
    body = ParagraphStyle('body', fontName=REGULAR, fontSize=8, leading=11, textColor=NAVY, splitLongWords=True)
    label = ParagraphStyle('label', parent=body, fontName=BOLD)
    centered = ParagraphStyle('centered', parent=body, alignment=TA_CENTER)
    table_heading = ParagraphStyle('header', parent=label, textColor=WHITE)
    heading = ParagraphStyle('title', parent=label, fontSize=19, leading=23, alignment=TA_LEFT)
    total = ParagraphStyle('total', parent=label, fontSize=11, leading=15)

    def text(value, style=body):
        return Paragraph(escape(str(value)), style)

    generated = local_time(generated_at)
    metadata = Table([
        [text('Generado por', label), text(generated_by)],
        [text('Fecha y hora', label), text(f'{generated:%d/%m/%Y %H:%M:%S} · Ecuador continental')],
        [text('Materia', label), text(course or 'Todas las materias del alcance')],
        [text('Periodo', label), text(period_label(date_from, date_to))],
    ], colWidths=[33 * mm, 143 * mm], hAlign='LEFT')
    metadata.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    summary = Table([[text('Total de asistencias registradas', total), text(len(rows), total)]],
                    colWidths=[148 * mm, 28 * mm], hAlign='LEFT')
    summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), PALE),
        ('LINEBEFORE', (0, 0), (0, 0), 2, TEAL),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story = [text(title, heading), Spacer(1, 2 * mm), metadata,
             Spacer(1, 3 * mm), summary, Spacer(1, 4 * mm)]
    if not rows:
        story.append(text('No hay registros para los filtros aplicados.'))
    else:
        values = [[text(value, table_heading) for value in ('Estudiante', 'Materia', 'Sesión', 'Fecha', 'Hora', 'Estado')]]
        for row in rows:
            instant = local_time(datetime.fromisoformat(row['registered_at']))
            values.append([
                text(row['student']), text(row['course']), text(row['session_id'], centered),
                text(f'{instant:%d/%m/%Y}', centered), text(f'{instant:%H:%M:%S}', centered), text('Presente', centered),
            ])
        table = LongTable(values, colWidths=[v * mm for v in (46, 49, 16, 24, 19, 17)],
                          repeatRows=1, splitInRow=1, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), NAVY),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, PALE]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LINEBELOW', (0, 0), (-1, 0), 1, TEAL),
        ]))
        story.append(table)

    def page(canvas, template):
        draw_page(canvas, template, demo)

    doc.build(story, onFirstPage=page, onLaterPages=page)
    return output.getvalue()
