import { useState } from 'react'
import { Activity, Bell } from 'lucide-react'
import { formatAttendancePercent } from './attendance-charts'
import { formatReportingDate } from './reporting-time'
import './absenteeism-panel.css'

type Risk = 'alto' | 'medio' | 'bajo' | 'sin_datos'
export type RiskRow = {
  id: number; student: string; course: string; total: number; absent: number
  rate: number | null; consecutive: number; level: Risk; reasons: string[]; recent: number[]
}
type Period = { start: string; end: string; present: number; expected: number; rate: number | null }
type Rank = { id: number; name: string; absent: number; expected: number; rate: number }
type Role = 'admin' | 'teacher' | 'student'
export type Absenteeism = {
  policy: { min_sessions: number; high_below: number; medium_below: number; high_streak: number; medium_streak: number }
  trend: { previous: Period; current: Period; change: number | null }
  top_students: Rank[]
  top_courses: Rank[]
}

const riskLabels: Record<Risk, string> = {
  alto: 'Riesgo alto', medio: 'Riesgo medio', bajo: 'Riesgo bajo', sin_datos: 'Datos insuficientes',
}
const recommendations = {
  admin: {
    alto: 'Coordina con el docente y tutoría un plan de seguimiento y recuperación.',
    medio: 'Solicita al docente un seguimiento preventivo en las próximas clases.',
  },
  teacher: {
    alto: 'Contacta al estudiante, acuerda un plan de recuperación y programa un seguimiento.',
    medio: 'Conversa con el estudiante y revisa su asistencia en las próximas clases.',
  },
  student: {
    alto: 'Escribe a tu docente o tutoría para acordar cómo recuperar las actividades pendientes.',
    medio: 'Revisa tus próximas clases y avisa a tu docente si necesitas apoyo para asistir.',
  },
}
const formatChange = new Intl.NumberFormat('es-EC', { signDisplay: 'exceptZero', maximumFractionDigits: 1 })
const format = formatAttendancePercent

function countNoun(count: number, singular: string, plural: string) {
  return `${count} ${count === 1 ? singular : plural}`
}

const absenceCount = (count: number) => countNoun(count, 'ausencia', 'ausencias')
const classCount = (count: number) => countNoun(count, 'clase', 'clases')
const consecutiveCount = (count: number) => countNoun(count, 'ausencia consecutiva', 'ausencias consecutivas')
const expectedCount = (count: number) => countNoun(count, 'asistencia esperada', 'asistencias esperadas')

export function RiskBadge({ level }: { level: Risk }) {
  return <span className={`badge risk-badge risk-${level}`}>{riskLabels[level]}</span>
}

function PeriodCard({ label, period }: { label: string; period: Period }) {
  return <div>
    <strong>{label}</strong>
    <small>{formatReportingDate(period.start)} – {formatReportingDate(period.end)}</small>
    <b>{format(period.rate)}</b>
    {period.rate !== null && <div className="absence-trend-track" role="meter"
      aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={period.rate}>
      <span style={{ width: `${period.rate}%` }}/>
    </div>}
    <small>{period.present} de {expectedCount(period.expected)}</small>
  </div>
}

function Ranking({ title, rows, minSessions }: { title: string; rows: Rank[]; minSessions: number }) {
  return <section className="panel">
    <h3>{title}</h3>
    <p>Hasta cinco resultados, por porcentaje de ausencias. Se señalan los resultados con menos de {expectedCount(minSessions)}.</p>
    {rows.length === 0 ? <p>No hay ausencias en el alcance disponible.</p> :
      <ol className="absence-ranking">{rows.map(row => <li key={row.id}>
        <div>
          <strong>{row.name}</strong>
          <small>{absenceCount(row.absent)} de {expectedCount(row.expected)}</small>
          {row.expected < minSessions && <RiskBadge level="sin_datos"/>}
        </div>
        <div className="absence-ranking-rate"><b>{format(row.rate)}</b><small>de ausencias</small></div>
      </li>)}</ol>}
  </section>
}

export function AbsenteeismPanel({ analysis, alerts, rows, role }: {
  analysis: Absenteeism; alerts: RiskRow[]; rows: RiskRow[]; role: Role
}) {
  const [filter, setFilter] = useState('all')
  const personal = role === 'student'
  const { policy, trend } = analysis
  const filtered = rows.filter(row => filter === 'all' || row.level === filter)
  return <div className="absence-panel">
    <section className="panel">
      <div className="panel-head"><div><h3>Tendencia de asistencia</h3>
        <p>{personal ? 'Tu asistencia' : role === 'teacher' ? 'Tus materias a cargo' : 'Todas las materias'} · Ecuador continental</p>
      </div><Activity size={19}/></div>
      <div className="absence-periods">
        <PeriodCard label="Periodo anterior" period={trend.previous}/>
        <PeriodCard label="Últimos 7 días" period={trend.current}/>
      </div>
      <p className="absence-change">{trend.change === null
        ? 'Se necesitan sesiones válidas en ambos periodos para calcular la variación.'
        : `Variación de asistencia: ${formatChange.format(trend.change)} puntos porcentuales.`}</p>
    </section>

    <section className="panel">
      <div className="panel-head"><div><h3>Alertas preventivas</h3>
        <p>{countNoun(alerts.length, 'alerta activa', 'alertas activas')} de riesgo medio o alto</p></div><Bell size={19}/></div>
      {!alerts.length && <p>{rows.some(row => row.level === 'bajo')
        ? 'Sin alertas activas en las matrículas evaluadas.'
        : 'Aún no hay suficientes sesiones para evaluar el riesgo.'}</p>}
      <ul className="absence-alerts">{alerts.map(row => {
        if (row.level !== 'alto' && row.level !== 'medio') return null
        return <li className={`risk-${row.level}`} key={row.id}>
          <RiskBadge level={row.level}/>
          <h4>{personal ? row.course : row.student}</h4>
          {!personal && <small>{row.course}</small>}
          <p>{absenceCount(row.absent)} de {classCount(row.total)} · Racha activa de {consecutiveCount(row.consecutive)}</p>
          <p>{row.reasons.join(' · ')}</p>
          <p>{recommendations[role][row.level]}</p>
        </li>
      })}</ul>
    </section>

    <div className="absence-columns">
      {!personal && <Ranking title="Estudiantes con mayor ausentismo" rows={analysis.top_students} minSessions={policy.min_sessions}/>}
      <Ranking title={personal ? 'Tus materias con más ausencias' : 'Materias con mayor ausentismo'} rows={analysis.top_courses} minSessions={policy.min_sessions}/>
    </div>

    <section className="panel">
      <div className="absence-followup">
        <h3>{personal ? 'Mi seguimiento por materia' : 'Seguimiento por estudiante y materia'}</h3>
        <label>Nivel de riesgo
          <select value={filter} onChange={event => setFilter(event.target.value)}>
            <option value="all">Todos</option>
            {Object.entries(riskLabels).map(([level, label]) => <option key={level} value={level}>{label}</option>)}
          </select>
        </label>
      </div>
      {!filtered.length && <p>No hay matrículas para esta selección.</p>}
      {filtered.map(row => <details className="absence-row" key={row.id}>
        <summary>
          <span><strong>{personal ? row.course : row.student}</strong>{!personal && <small>{row.course}</small>}</span>
          <RiskBadge level={row.level}/>
        </summary>
        <p>{row.rate === null ? 'Sin datos de asistencia' : `${format(row.rate)} de asistencia`} · {absenceCount(row.absent)} de {classCount(row.total)} · Racha activa de {consecutiveCount(row.consecutive)}</p>
        {row.recent.length > 0 && <p>Asistencia reciente, de la más antigua a la más nueva: {row.recent.map(value => value ? 'Presente' : 'Ausente').join(' · ')}</p>}
      </details>)}
    </section>

    <details className="panel absence-rules">
      <summary>Criterios de riesgo</summary>
      <p>El análisis usa reglas estadísticas explicables. Se consideran sesiones válidas finalizadas, desde la fecha y hora de matrícula. Los umbrales se aplican al porcentaje de asistencia acumulado y a la racha activa de ausencias.</p>
      <ul>
        <li>Datos insuficientes: menos de {countNoun(policy.min_sessions, 'clase válida', 'clases válidas')}.</li>
        <li>Alto: asistencia inferior al {policy.high_below}% o {consecutiveCount(policy.high_streak)}.</li>
        <li>Medio: asistencia inferior al {policy.medium_below}% o {consecutiveCount(policy.medium_streak)}, una vez descartado el riesgo alto.</li>
        <li>Bajo: asistencia de al menos {policy.medium_below}% y menos de {consecutiveCount(policy.medium_streak)}.</li>
      </ul>
    </details>
  </div>
}
