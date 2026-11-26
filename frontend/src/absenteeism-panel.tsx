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

function RiskBadge({ level }: { level: Risk }) {
  return <span className={`badge risk-${level}`}>{riskLabels[level]}</span>
}

function PeriodCard({ label, period }: { label: string; period: Period }) {
  return <div>
    <strong>{label}</strong>
    <small>{formatReportingDate(period.start)} – {formatReportingDate(period.end)}</small>
    <b>{format(period.rate)}</b>
    {period.expected > 0 && <meter min={0} max={100} value={period.rate ?? 0} aria-label={label}/>}
    <small>{period.present} de {period.expected} asistencias esperadas</small>
  </div>
}

function Ranking({ title, rows }: { title: string; rows: Rank[] }) {
  return <section className="panel">
    <h3>{title}</h3>
    <p>Hasta cinco resultados, ordenados por porcentaje de ausencias.</p>
    {rows.length === 0 ? <p>No hay ausencias en el alcance disponible.</p> :
      <ol className="absence-ranking">{rows.map(row => <li key={row.id}>
        <div><strong>{row.name}</strong><small>{row.absent} de {row.expected} asistencias esperadas</small></div>
        <b>{format(row.rate)}</b>
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
        <p>{alerts.length} alertas activas de riesgo medio o alto</p></div><Bell size={19}/></div>
      {!alerts.length && <p>{rows.some(row => row.level === 'bajo')
        ? 'Sin alertas activas en las matrículas evaluadas.'
        : 'Aún no hay suficientes sesiones para evaluar el riesgo.'}</p>}
      <ul className="absence-alerts">{alerts.map(row => {
        if (row.level !== 'alto' && row.level !== 'medio') return null
        return <li key={row.id}>
          <RiskBadge level={row.level}/>
          <h4>{personal ? row.course : row.student}</h4>
          {!personal && <small>{row.course}</small>}
          <p>{row.absent} ausencias de {row.total} clases · Racha activa de {row.consecutive}</p>
          <p>{row.reasons.join(' · ')}</p>
          <p>{recommendations[role][row.level]}</p>
        </li>
      })}</ul>
    </section>

    <div className="absence-columns">
      {!personal && <Ranking title="Estudiantes con mayor ausentismo" rows={analysis.top_students}/>}
      <Ranking title={personal ? 'Tus materias con más ausencias' : 'Materias con mayor ausentismo'} rows={analysis.top_courses}/>
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
        <p>{format(row.rate)} de asistencia · {row.absent} ausencias de {row.total} clases · Racha activa de {row.consecutive}</p>
        {row.recent.length > 0 && <p>Asistencia reciente, de la más antigua a la más nueva: {row.recent.map(value => value ? 'Presente' : 'Ausente').join(' · ')}</p>}
      </details>)}
    </section>

    <details className="panel absence-rules">
      <summary>Criterios de riesgo</summary>
      <p>El análisis usa reglas estadísticas explicables. Se consideran sesiones válidas finalizadas, desde la fecha y hora de matrícula. Los umbrales se aplican al porcentaje de asistencia acumulado y a la racha activa de ausencias.</p>
      <ul>
        <li>Datos insuficientes: menos de {policy.min_sessions} clases válidas.</li>
        <li>Alto: asistencia inferior al {policy.high_below}% o {policy.high_streak} ausencias consecutivas.</li>
        <li>Medio: asistencia inferior al {policy.medium_below}% o {policy.medium_streak} ausencias consecutivas, una vez descartado el riesgo alto.</li>
        <li>Bajo: asistencia de al menos {policy.medium_below}% y menos de {policy.medium_streak} ausencias consecutivas.</li>
      </ul>
    </details>
  </div>
}
