import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { CircleCheck, Download } from 'lucide-react'
import { api, attendanceQuery, exportCSV, fetchAttendanceExcel, fetchAttendancePDF } from './api'
import type { AttendanceFilters } from './api'
import { formatReportingInstant } from './reporting-time'
import { workspaceCopy } from './workspace-copy'
import type { WorkspaceRole } from './workspace-copy'
import './attendance-history.css'

type CourseOption = { id: number; name: string; code: string }
type RecordRow = { id: number; student: string; course: string; registered_at: string; session_id: number }
type HistoryResult = { filters: AttendanceFilters; rows: RecordRow[]; error?: string }

const emptyFilters: AttendanceFilters = { course_id: '', date_from: '', date_to: '' }

export function AttendanceHistory({ courses, role, timeZone }: {
  courses: CourseOption[]; role: WorkspaceRole; timeZone?: string
}) {
  const copy = workspaceCopy[role]
  const [draft, setDraft] = useState(emptyFilters)
  const [applied, setApplied] = useState(emptyFilters)
  const [result, setResult] = useState<HistoryResult>()
  const [filterError, setFilterError] = useState('')
  const [exportError, setExportError] = useState<{ filters: AttendanceFilters; message: string }>()
  const [exporting, setExporting] = useState(false)
  const [generatingPdf, setGeneratingPdf] = useState(false)
  const [pdf, setPdf] = useState<{ filters: AttendanceFilters; blob: Blob }>()
  const [pdfLink, setPdfLink] = useState<{ blob: Blob; url: string }>()
  const [pdfError, setPdfError] = useState<{ filters: AttendanceFilters; message: string }>()
  const [generatingExcel, setGeneratingExcel] = useState(false)
  const [excel, setExcel] = useState<{ filters: AttendanceFilters; blob: Blob }>()
  const [excelLink, setExcelLink] = useState<{ blob: Blob; url: string }>()
  const [excelError, setExcelError] = useState<{ filters: AttendanceFilters; message: string }>()
  const current = result?.filters === applied ? result : undefined

  useEffect(() => {
    if (!pdf || pdf.filters !== applied) return
    const url = URL.createObjectURL(pdf.blob)
    setPdfLink({ blob: pdf.blob, url })
    return () => URL.revokeObjectURL(url)
  }, [applied, pdf])

  useEffect(() => {
    if (!excel || excel.filters !== applied) return
    const url = URL.createObjectURL(excel.blob)
    setExcelLink({ blob: excel.blob, url })
    return () => URL.revokeObjectURL(url)
  }, [applied, excel])

  useEffect(() => {
    let active = true
    let pending = false
    async function refresh() {
      if (pending) return
      pending = true
      try {
        const rows = await api<RecordRow[]>('/attendance' + attendanceQuery(applied))
        if (active) setResult({ filters: applied, rows })
      } catch (error) {
        if (active) setResult({ filters: applied, rows: [], error: (error as Error).message })
      } finally {
        pending = false
      }
    }
    void refresh()
    const timer = setInterval(() => void refresh(), 5000)
    return () => { active = false; clearInterval(timer) }
  }, [applied])

  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) {
      setFilterError('La fecha inicial debe ser igual o anterior a la fecha final.')
      return
    }
    setFilterError('')
    setApplied({ ...draft })
  }

  function clear() {
    setDraft(emptyFilters)
    setFilterError('')
    setApplied({ ...emptyFilters })
  }

  async function download() {
    setExporting(true)
    setExportError(undefined)
    try {
      await exportCSV(applied)
    } catch (error) {
      setExportError({ filters: applied, message: (error as Error).message })
    } finally {
      setExporting(false)
    }
  }

  async function generatePdf() {
    setGeneratingPdf(true)
    setPdf(undefined)
    setPdfError(undefined)
    try {
      setPdf({ filters: applied, blob: await fetchAttendancePDF(applied) })
    } catch (error) {
      setPdfError({ filters: applied, message: (error as Error).message })
    } finally {
      setGeneratingPdf(false)
    }
  }

  async function generateExcel() {
    setGeneratingExcel(true)
    setExcel(undefined)
    setExcelError(undefined)
    try {
      setExcel({ filters: applied, blob: await fetchAttendanceExcel(applied) })
    } catch (error) {
      setExcelError({ filters: applied, message: (error as Error).message })
    } finally {
      setGeneratingExcel(false)
    }
  }

  const courseName = courses.find(course => String(course.id) === applied.course_id)?.name
  const appliedSummary = [
    applied.course_id && (courseName || 'Materia seleccionada'),
    applied.date_from && `Desde ${applied.date_from}`,
    applied.date_to && `Hasta ${applied.date_to}`,
  ].filter(Boolean).join(' · ')

  return <section className="panel attendance-history" aria-labelledby="attendance-history-title">
    <div className="panel-head attendance-history-header">
      <h2 id="attendance-history-title">{copy.historyRecords}</h2>
      <div className="attendance-history-actions attendance-history-exports">
        <button className="btn outline" disabled={!current || !!current.error || exporting} onClick={() => void download()}>
          <Download size={16}/> {exporting ? 'Exportando…' : 'Exportar CSV'}
        </button>
        <button className="btn outline" disabled={!current || !!current.error || generatingPdf} onClick={() => void generatePdf()}>
          <Download size={16}/> {generatingPdf ? 'Generando PDF…' : 'Exportar PDF'}
        </button>
        <button className="btn outline" disabled={!current || !!current.error || generatingExcel} onClick={() => void generateExcel()}>
          <Download size={16} aria-hidden="true"/> {generatingExcel ? 'Generando Excel…' : 'Exportar Excel'}
        </button>
      </div>
    </div>
    {generatingPdf && <p role="status">Preparando el reporte PDF…</p>}
    {pdf?.filters === applied && pdfLink?.blob === pdf.blob && <div className="attendance-pdf-ready">
      <p role="status">
        <CircleCheck size={20} aria-hidden="true"/>
        <strong>¡Reporte PDF generado correctamente!</strong>
      </p>
      <a className="btn attendance-pdf-download" href={pdfLink.url} download="asistix-asistencia.pdf" target="_blank" rel="noopener noreferrer">
        <Download size={17} aria-hidden="true"/> Abrir o guardar PDF
      </a>
    </div>}
    {pdfError?.filters === applied && <p className="error" role="alert">{pdfError.message}</p>}
    {generatingExcel && <p role="status">Preparando el reporte Excel…</p>}
    {excel?.filters === applied && excelLink?.blob === excel.blob && <div className="attendance-excel-ready">
      <p role="status">
        <CircleCheck size={20} aria-hidden="true"/>
        <strong>¡Reporte Excel generado correctamente!</strong>
      </p>
      <a className="btn attendance-excel-download" href={excelLink.url} download="asistix-asistencia.xlsx" target="_blank" rel="noopener noreferrer">
        <Download size={17} aria-hidden="true"/> Guardar Excel
      </a>
    </div>}
    {excelError?.filters === applied && <p className="error" role="alert">{excelError.message}</p>}
    <form className="attendance-history-filters" aria-label="Filtros del historial" onSubmit={apply}>
      <label>Materia<select value={draft.course_id} onChange={event => setDraft({ ...draft, course_id: event.target.value })}>
        <option value="">Todas las materias</option>
        {courses.map(course => <option key={course.id} value={course.id}>{course.code} · {course.name}</option>)}
      </select></label>
      <label>Fecha inicial<input type="date" value={draft.date_from} onChange={event => setDraft({ ...draft, date_from: event.target.value })}/></label>
      <label>Fecha final<input type="date" value={draft.date_to} onChange={event => setDraft({ ...draft, date_to: event.target.value })}/></label>
      <div className="attendance-history-actions">
        <button className="btn" type="submit">Aplicar filtros</button>
        <button className="btn outline" type="button" onClick={clear}>Limpiar filtros</button>
      </div>
    </form>
    <p className="muted">{appliedSummary ? `Filtros aplicados: ${appliedSummary}` : 'Sin filtros aplicados'} · Fecha de registro en Ecuador continental</p>
    {filterError && <p className="error" role="alert">{filterError}</p>}
    {exportError?.filters === applied && <p className="error" role="alert">{exportError.message}</p>}
    {!current ? <p role="status">Cargando registros…</p> : current.error
      ? <p className="error" role="alert">{current.error}</p>
      : <>
        <p role="status">{current.rows.length} {current.rows.length === 1 ? 'registro encontrado' : 'registros encontrados'}</p>
        {current.rows.length === 0 ? <p className="empty">{appliedSummary ? copy.emptyFilteredHistory : copy.emptyHistory}</p>
          : <>
            <div className="table-wrap attendance-history-table"><table>
              <thead><tr><th scope="col">Estudiante</th><th scope="col">Materia</th><th scope="col">Sesión</th><th scope="col">Fecha y hora de Ecuador continental</th><th scope="col">Estado</th></tr></thead>
              <tbody>{current.rows.map(row => <tr key={row.id}>
                <td>{row.student}</td><td>{row.course}</td><td>#{row.session_id}</td>
                <td><time dateTime={row.registered_at}>{formatReportingInstant(row.registered_at, timeZone)}</time></td>
                <td><span className="badge green">Presente</span></td>
              </tr>)}</tbody>
            </table></div>
            <ul className="attendance-history-cards" role="list" aria-label="Registros de asistencia">
              {current.rows.map(row => <li key={row.id}>
                <dl>
                  <div><dt>Estudiante</dt><dd>{row.student}</dd></div>
                  <div><dt>Materia</dt><dd>{row.course}</dd></div>
                  <div><dt>Sesión</dt><dd>#{row.session_id}</dd></div>
                  <div><dt>Fecha y hora</dt><dd><time dateTime={row.registered_at}>{formatReportingInstant(row.registered_at, timeZone)}</time></dd></div>
                  <div><dt>Estado</dt><dd><span className="badge green">Presente</span></dd></div>
                </dl>
              </li>)}
            </ul>
          </>}
      </>}
  </section>
}
