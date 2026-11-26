import { useId } from 'react'
import { BookOpen, ChevronDown } from 'lucide-react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatReportingDate } from './reporting-time'
import './attendance-charts.css'

export type WeeklyAttendance = { date: string; present: number; expected: number }
export type CourseAttendance = { name: string; present: number; expected: number; rate: number | null }

const percentFormat = new Intl.NumberFormat('es-EC', {
  minimumFractionDigits: 1, maximumFractionDigits: 1,
})
const countFormat = new Intl.NumberFormat('es-EC')
const registeredLabel = 'Asistencias registradas'
const expectedLabel = 'Asistencias esperadas'

export function formatAttendancePercent(rate: number | null) {
  return rate === null ? 'Sin datos' : `${percentFormat.format(rate)}\u00a0%`
}

function AttendanceCounts({ present, expected }: Pick<WeeklyAttendance, 'present' | 'expected'>) {
  return <dl className="attendance-counts">
    <div><dt>{registeredLabel}</dt><dd>{countFormat.format(present)}</dd></div>
    <div><dt>{expectedLabel}</dt><dd>{countFormat.format(expected)}</dd></div>
  </dl>
}

export function WeeklyAttendanceTooltip({ point }: { point?: WeeklyAttendance }) {
  if (!point) return null
  const rate = point.expected > 0 ? 100 * point.present / point.expected : null
  return <div className="attendance-chart-tooltip">
    <strong>{formatReportingDate(point.date)}</strong>
    <AttendanceCounts present={point.present} expected={point.expected}/>
    <p>Asistencia · <strong>{formatAttendancePercent(rate)}</strong></p>
  </div>
}

function WeeklyChart({ week }: { week: WeeklyAttendance[] }) {
  const fillId = `attendance-fill-${useId().replace(/[^\w-]/g, '')}`
  return <section className="panel attendance-chart-panel">
    <div className="panel-head">
      <div><h3>El pulso de tus clases</h3><p>Asistencias en sesiones cerradas · Últimos 7 días · hora de Ecuador continental</p></div>
      <span className="badge">Semanal</span>
    </div>
    <ul className="attendance-chart-legend" aria-label="Leyenda de asistencia semanal">
      <li><span className="attendance-chart-line" aria-hidden="true"/>{registeredLabel}</li>
      <li><span className="attendance-chart-line attendance-chart-line-expected" aria-hidden="true"/>{expectedLabel}</li>
    </ul>
    <ResponsiveContainer width="100%" height={245} minWidth={0}>
      <AreaChart data={week} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} accessibilityLayer>
        <defs>
          <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2870ef" stopOpacity={.25}/>
            <stop offset="100%" stopColor="#2870ef" stopOpacity={0}/>
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="4 5" vertical={false} stroke="#edf0f5"/>
        <XAxis dataKey="date" tickFormatter={(day: string) => `${day.slice(8)}/${day.slice(5, 7)}`}
          axisLine={false} tickLine={false} fontSize={11} minTickGap={8}/>
        <YAxis allowDecimals={false} axisLine={false} tickLine={false} width={34} fontSize={11}/>
        <Tooltip isAnimationActive={false} wrapperStyle={{ pointerEvents: 'none' }}
          content={({ active, label }) => <WeeklyAttendanceTooltip point={active ? week.find(day => day.date === label) : undefined}/>}/>
        <Area name={registeredLabel} type="monotone" dataKey="present" stroke="#2870ef" strokeWidth={3}
          fill={`url(#${fillId})`} isAnimationActive={false}/>
        <Area name={expectedLabel} dataKey="expected" stroke="#869ab5" strokeWidth={2} strokeDasharray="5 4"
          fill="none" isAnimationActive={false}/>
      </AreaChart>
    </ResponsiveContainer>
  </section>
}

export function AttendanceByCourse({ courses }: { courses: CourseAttendance[] }) {
  return <section className="panel attendance-chart-panel">
    <div className="panel-head"><div><h3>Asistencia por materia</h3><p>Porcentaje acumulado</p></div><BookOpen size={19}/></div>
    {courses.length === 0 ? <p className="empty">No hay materias para mostrar.</p>
      : <ul className="attendance-course-bars">
        {courses.map((course, index) => <li key={index}>
          <details className="attendance-course-details">
            <summary>
              <span className="attendance-course-name">{course.name}</span>
              <strong className="attendance-course-rate">{formatAttendancePercent(course.rate)}<ChevronDown size={12} aria-hidden="true"/></strong>
              <span className={`attendance-course-track${course.rate === null ? ' attendance-course-track-empty' : ''}`} aria-hidden="true">
                {course.rate !== null && <span className="attendance-course-fill" style={{ width: `${course.rate}%` }}/>}
              </span>
            </summary>
            <div className="attendance-course-counts">
              <AttendanceCounts present={course.present} expected={course.expected}/>
            </div>
          </details>
        </li>)}
      </ul>}
  </section>
}

export function AttendanceCharts({ week, courses }: { week: WeeklyAttendance[]; courses: CourseAttendance[] }) {
  return <div className="charts-grid attendance-charts">
    <WeeklyChart week={week}/>
    <AttendanceByCourse courses={courses}/>
  </div>
}
