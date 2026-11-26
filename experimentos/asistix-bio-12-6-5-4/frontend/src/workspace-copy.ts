export const workspaceCopy = {
  admin: {
    summaryTitle: 'Resumen institucional',
    summaryDescription: 'Consulta los indicadores de asistencia de todas las materias de la institución.',
    historyTitle: 'Historial institucional',
    historyDescription: 'Consulta y exporta las asistencias registradas en las materias de la institución.',
    historyRecords: 'Registros de la institución',
    emptyHistory: 'Todavía no hay asistencias registradas en la institución.',
    emptyFilteredHistory: 'No hay registros institucionales para los filtros aplicados.',
  },
  teacher: {
    summaryTitle: 'Resumen de mis materias',
    summaryDescription: 'Consulta la asistencia y el seguimiento de tus materias asignadas.',
    historyTitle: 'Historial de mis materias',
    historyDescription: 'Consulta y exporta las asistencias registradas en tus materias asignadas.',
    historyRecords: 'Registros de tus materias',
    emptyHistory: 'Todavía no hay asistencias registradas en tus materias asignadas.',
    emptyFilteredHistory: 'No hay registros de tus materias para los filtros aplicados.',
  },
  student: {
    summaryTitle: 'Mi asistencia',
    summaryDescription: 'Consulta tus indicadores de asistencia en las materias en las que estás matriculado.',
    historyTitle: 'Mi historial de asistencia',
    historyDescription: 'Consulta y exporta tus propias asistencias registradas.',
    historyRecords: 'Mis registros de asistencia',
    emptyHistory: 'Todavía no tienes asistencias registradas.',
    emptyFilteredHistory: 'No tienes registros para los filtros aplicados.',
  },
} as const

export type WorkspaceRole = keyof typeof workspaceCopy
