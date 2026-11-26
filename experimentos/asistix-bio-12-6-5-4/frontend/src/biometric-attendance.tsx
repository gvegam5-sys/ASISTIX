import { Check, Circle, CircleAlert, LoaderCircle, ScanLine, ShieldCheck, Timer } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ComponentType } from 'react'
import { ApiError, api } from './api'
import './biometric-attendance.css'

type Challenge = { challenge?: string; expires_at?: string; session_id: number; message?: string }
type ScannerProps = { onResult: (text: string) => void; disabled?: boolean }

export function releaseCamera(stream: MediaStream | null) {
  stream?.getTracks().forEach(track => track.stop())
}

export async function openFrontCamera(getMedia: MediaDevices['getUserMedia'], stale: () => boolean) {
  const stream = await getMedia({ video: { facingMode: { ideal: 'user' } }, audio: false })
  if (stale()) {
    releaseCamera(stream)
    return null
  }
  return stream
}

export function BiometricAttendance({ Scanner, refresh, allowCamera = false }: {
  Scanner: ComponentType<ScannerProps>; refresh: () => Promise<void>; allowCamera?: boolean
}) {
  const [enrolled, setEnrolled] = useState<boolean>()
  const [physical, setPhysical] = useState(false)
  const [notice, setNotice] = useState('')
  const [consent, setConsent] = useState(false)
  const [cameraReady, setCameraReady] = useState(false)
  const [confirmRevoke, setConfirmRevoke] = useState(false)
  const [rightsMessage, setRightsMessage] = useState('')
  const [rightsError, setRightsError] = useState(false)
  const [messageTone, setMessageTone] = useState<'success' | 'notice' | 'error'>('notice')
  const locked = useRef(false)
  useEffect(() => {
    let active = true
    api<{ enrolled: boolean; physical_capture?: boolean; notice?: string }>('/biometric/status').then(value => {
      if (active && !locked.current) {
        setEnrolled(value.enrolled)
        setPhysical(window.isSecureContext && value.physical_capture === true)
        setNotice(value.notice || '')
      }
    }).catch(() => { if (active) { setRightsError(true); setRightsMessage('No se pudo consultar el estado del registro.') } })
    return () => { active = false }
  }, [])
  const [screen, setScreen] = useState<'scan' | 'verify' | 'done'>('scan')
  const [input, setInput] = useState('')
  const [challenge, setChallenge] = useState<Challenge>()
  const [fixture, setFixture] = useState('a')
  const [message, setMessage] = useState('')
  const [cameraError, setCameraError] = useState('')
  const [busy, setBusy] = useState(false)
  const [remaining, setRemaining] = useState(0)
  const [transition, setTransition] = useState<number>()
  const [reason, setReason] = useState('technical')
  const camera = useRef<MediaStream | null>(null)
  const video = useRef<HTMLVideoElement>(null)
  const revision = useRef(0)
  const cameraRevision = useRef(0)
  const scanStart = useRef(0)

  function stop() {
    cameraRevision.current += 1
    releaseCamera(camera.current)
    camera.current = null
    setCameraReady(false)
    if (video.current) video.current.srcObject = null
  }

  useEffect(() => () => { revision.current += 1; stop() }, [])
  useEffect(() => {
    const hide = () => { if (document.hidden) stop() }
    document.addEventListener('visibilitychange', hide)
    return () => document.removeEventListener('visibilitychange', hide)
  }, [])
  useEffect(() => {
    if (!challenge?.expires_at) return
    const tick = () => {
      const seconds = Math.max(0, Math.ceil((Date.parse(challenge.expires_at!) - Date.now()) / 1000))
      setRemaining(seconds)
      if (seconds === 0) stop()
    }
    tick()
    const interval = setInterval(tick, 200)
    return () => clearInterval(interval)
  }, [challenge])

  async function scan(value: string) {
    if (locked.current) return
    let qr = value.trim()
    try { qr = new URLSearchParams(new URL(qr).hash.slice(1)).get('qr') || qr } catch { /* direct QR token */ }
    if (!qr) return
    stop()
    const operation = ++revision.current
    scanStart.current = performance.now()
    locked.current = true
    setBusy(true); setMessage(''); setChallenge(undefined); setTransition(undefined)
    try {
      try {
        const result = await api<{ message: string }>('/attendance', 'POST', { token: qr })
        if (operation === revision.current) { setScreen('done'); setMessage(result.message); void refresh() }
        return
      } catch (error) {
        if (!(error instanceof ApiError) || error.code !== 'BIOMETRIC_REQUIRED') throw error
      }
      const response = await api<Challenge>('/biometric/challenges', 'POST', { token: qr })
      if (operation !== revision.current) return
      setChallenge(response); setScreen('verify')
      if (!response.challenge) setMessage(response.message || 'Completa tu registro facial sintético.')
    } catch (error) {
      if (operation === revision.current) { setMessageTone('error'); setMessage((error as Error).message) }
    } finally {
      locked.current = false
      if (operation === revision.current) setBusy(false)
    }
  }

  async function preview() {
    stop()
    const operation = cameraRevision.current
    setCameraError('')
    try {
      const stream = await openFrontCamera(navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices),
        () => operation !== cameraRevision.current || !video.current)
      if (!stream) return
      camera.current = stream
      const element = video.current
      if (element) {
        element.srcObject = stream
        await element.play()
      }
      if (operation === cameraRevision.current) {
        setTransition(Math.round(performance.now() - scanStart.current))
        setCameraReady(true)
      }
    } catch {
      if (operation === cameraRevision.current) {
        stop()
        setCameraError('No pudimos abrir la cámara frontal. Revisa el permiso o cierra las otras aplicaciones que la usan.')
      }
    }
  }

  async function captureJpeg() {
    const element = video.current
    if (!element?.videoWidth || !element.videoHeight || !camera.current) throw new Error('Activa la cámara y espera la vista previa.')
    const scale = Math.min(1, 640 / Math.max(element.videoWidth, element.videoHeight))
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(element.videoWidth * scale)
    canvas.height = Math.round(element.videoHeight * scale)
    const context = canvas.getContext('2d')
    if (!context) throw new Error('No pudimos preparar la captura.')
    context.drawImage(element, 0, 0, canvas.width, canvas.height)
    stop()
    const jpeg = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.86))
    canvas.width = canvas.height = 0
    if (!jpeg) throw new Error('No pudimos preparar la captura.')
    return jpeg
  }

  async function verify() {
    if (!challenge?.challenge || locked.current || !remaining) return
    const operation = revision.current
    locked.current = true
    setBusy(true); setMessage('')
    try {
      const data = physical ? await captureJpeg() : { fixture }
      if (operation !== revision.current) return
      const result = await api<{ code: string; message: string }>(
        `/biometric/${physical ? 'physical/' : ''}challenges/${challenge.challenge}/confirm`, 'POST', data,
      )
      if (operation === revision.current && result.code === 'ATTENDANCE_RECORDED') {
        stop(); setChallenge(undefined); setScreen('done'); setMessage(result.message); void refresh()
      }
    } catch (error) {
      if (operation === revision.current) { setMessageTone('error'); setMessage((error as Error).message) }
    } finally { locked.current = false; if (operation === revision.current) setBusy(false) }
  }

  function reset() {
    revision.current += 1
    if (challenge?.challenge) void api(`/biometric/challenges/${challenge.challenge}`, 'DELETE').catch(() => {})
    stop(); setInput(''); setScreen('scan'); setChallenge(undefined); setMessage(''); setCameraError(''); setConsent(false); setBusy(false)
  }

  async function enroll(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (locked.current) return
    locked.current = true; setBusy(true)
    try {
      if (physical) {
        if (!consent || !notice) return
        const operation = revision.current
        const jpeg = await captureJpeg()
        if (operation !== revision.current) return
        await api('/biometric/physical/enrollment', 'POST', jpeg, { 'X-Explicit-Consent': 'yes', 'X-Consent-Notice': notice })
        if (operation !== revision.current) return
      } else {
        await api('/biometric/enrollment', 'POST', { explicit: true, notice: 'sintetico-12.6.4-v1' })
      }
      setEnrolled(true)
      reset()
      setMessageTone('success')
      setMessage('Registro listo. Escanea un QR vigente.')
    } catch (error) { setMessageTone('error'); setMessage((error as Error).message) } finally { locked.current = false; setBusy(false) }
  }

  async function review() {
    if (!challenge || locked.current) return
    locked.current = true; setBusy(true)
    try {
      await api('/biometric/reviews', 'POST', { session_id: challenge.session_id, reason })
      setMessage('Solicitud pendiente de revisión docente, sin penalización.')
    } catch (error) { setMessageTone('error'); setMessage((error as Error).message) } finally { locked.current = false; setBusy(false) }
  }

  async function revoke() {
    if (locked.current) return
    locked.current = true; setBusy(true); setRightsError(false); setRightsMessage('')
    try {
      const result = await api<{ enrolled: boolean }>('/biometric/enrollment', 'DELETE')
      setEnrolled(result.enrolled)
      setConfirmRevoke(false)
      reset()
      setRightsMessage('Consentimiento retirado y plantilla eliminada. Tus asistencias anteriores se conservan.')
    } catch {
      setRightsError(true)
      setRightsMessage('No se pudo confirmar el retiro. Intenta nuevamente.')
    } finally { locked.current = false; setBusy(false) }
  }

  return <section className="panel bio-flow" aria-label="Registro de asistencia con verificación facial">
    <ol className="bio-steps">
      {([['scan', 'Escanear QR'], ['verify', 'Verificar identidad'], ['done', 'Confirmar asistencia']] as const)
        .map(([key, label], index) => {
          const complete = ['scan', 'verify', 'done'].indexOf(screen) > index || screen === 'done'
          const Icon = complete ? Check : screen === key ? [ScanLine, ShieldCheck, Check][index] : Circle
          return <li key={key} data-complete={complete} aria-current={screen === key ? 'step' : undefined}>
            <Icon aria-hidden="true" size={18}/><span className="sr-only">{complete ? 'Completada: ' : screen === key ? 'Actual: ' : 'Pendiente: '}</span>{label}
          </li>
        })}
    </ol>
    <p>{physical ? 'Escanea el QR de tu docente. Si la sesión requiere verificación, usa tu cámara frontal.' : 'Demostración con datos ficticios. Pega el token del QR y elige un retrato del catálogo sintético.'}</p>
    {screen === 'scan' && <>
      {(physical || allowCamera) && <Scanner onResult={text => void scan(text)} disabled={busy}/>}
      <form onSubmit={event => { event.preventDefault(); void scan(input) }}>
        <label>Token QR de demostración<textarea value={input} required onChange={event => setInput(event.target.value)}/></label>
        <button className="btn" disabled={busy}>Validar QR</button>
      </form>
    </>}
    {screen === 'verify' && challenge?.challenge && <>
      {(physical || allowCamera) && <><div className="bio-frame"><video ref={video} playsInline muted aria-label="Vista previa de la cámara frontal"/></div>
      <p>Centra tu rostro en el óvalo y mantén una iluminación uniforme.</p>
      <button type="button" className="btn outline" disabled={!remaining || busy} onClick={() => void preview()}>Abrir cámara frontal</button></>}
      {cameraError && <p role="alert" className="bio-status error">{cameraError}</p>}
      {transition !== undefined && <p>Del QR a la cámara frontal: {transition} ms.</p>}
      <p className={`bio-count ${remaining <= 5 ? 'urgent' : ''}`}><Timer size={18} aria-hidden="true"/>{remaining} s restantes</p>
      {!physical && <label>Muestra del catálogo sintético
        <select value={fixture} onChange={event => setFixture(event.target.value)}><option value="a">Retrato sintético A</option><option value="b">Retrato sintético B</option></select>
      </label>}
      <button className="btn" disabled={busy || !remaining || (physical && !cameraReady)} onClick={() => void verify()}>{physical ? 'Capturar y verificar' : message && remaining ? 'Reintentar verificación' : 'Verificar muestra'}</button>
      {!remaining && <button className="btn outline" onClick={reset}>Escanear nuevo QR</button>}
    </>}
    {screen === 'verify' && !challenge?.challenge && <form onSubmit={enroll}>
      <p>{physical ? 'El laboratorio voluntario procesa la foto en memoria y conserva una plantilla facial cifrada para tu verificación. Puedes retirar el consentimiento, eliminarla o solicitar revisión docente sin penalización.' : 'El laboratorio genera una plantilla cifrada a partir de un retrato ficticio asignado. Puedes eliminarla o pedir revisión.'}</p>
      <label className="bio-consent"><input type="checkbox" required checked={consent} onChange={event => { setConsent(event.target.checked); if (!event.target.checked) stop() }}/> <span>{physical ? 'Consiento explícitamente el registro facial voluntario.' : 'Acepto explícitamente este registro sintético.'}</span></label>
      {physical && <><div className="bio-frame"><video ref={video} playsInline muted aria-label="Vista previa de la cámara frontal"/></div>
      <button type="button" className="btn outline" disabled={busy || !consent} onClick={() => void preview()}>Abrir cámara frontal</button>
      {cameraError && <p role="alert">{cameraError}</p>}</>}
      <button className="btn" disabled={busy || (physical && (!consent || !cameraReady))}>{physical ? 'Capturar y registrar' : 'Registrar plantilla sintética'}</button>
    </form>}
    {screen === 'verify' && <button className="btn outline" disabled={busy} onClick={reset}>Cancelar</button>}
    {screen === 'done' && <button className="btn outline" onClick={reset}>Escanear otro QR</button>}
    <p role="status" aria-live="polite" className={message || busy ? `bio-status ${busy ? 'notice' : screen === 'done' ? 'success' : messageTone}` : ''}>
      {busy ? <LoaderCircle className="bio-spinner" aria-hidden="true"/> : message && (screen === 'done' || messageTone === 'success' ? <Check aria-hidden="true"/> : <CircleAlert aria-hidden="true"/>)}
      {busy ? 'Procesando solicitud…' : message}
    </p>
    <details><summary>Ayuda y revisión docente</summary>
      <p>La revisión aprobada tiene el mismo efecto académico. Valida primero un QR para identificar la sesión.</p>
      {challenge && <><label>Motivo<select value={reason} onChange={event => setReason(event.target.value)}>
        <option value="technical">Problema técnico</option><option value="accessibility">Accesibilidad</option>
        <option value="no_consent">Sin consentimiento</option><option value="revoked">Consentimiento retirado</option>
        <option value="mismatch">La muestra no coincide</option>
      </select></label><button className="btn outline" disabled={busy} onClick={() => void review()}>Solicitar revisión</button></>}
    </details>
    <details><summary>Gestionar derechos biométricos</summary>
      <p>{enrolled === undefined ? 'Consultando registro…' : enrolled ? 'Registro biométrico vigente.' : 'Sin registro biométrico vigente.'}</p>
      <button className="btn outline" disabled={busy || enrolled !== true} onClick={() => setConfirmRevoke(true)}>Retirar consentimiento y eliminar plantilla</button>
      {confirmRevoke && <div role="group" aria-label="Confirmar retiro" className="bio-status notice">
        <p>Se eliminará tu plantilla y se cancelarán las verificaciones activas. Tu historial se conserva y podrás solicitar revisión docente.</p>
        <button className="btn danger" disabled={busy} onClick={() => void revoke()}>Confirmar eliminación</button>
        <button className="btn outline" disabled={busy} onClick={() => setConfirmRevoke(false)}>Volver</button>
      </div>}
      <p role="status" className={rightsMessage ? `bio-status ${rightsError ? 'error' : 'success'}` : ''}>{rightsMessage && (rightsError ? <CircleAlert aria-hidden="true"/> : <Check aria-hidden="true"/>)}{rightsMessage}</p>
    </details>
  </section>
}

const reasonLabels: Record<string, string> = {
  technical: 'Problema técnico', accessibility: 'Accesibilidad', no_consent: 'Sin consentimiento',
  revoked: 'Consentimiento retirado', mismatch: 'La muestra facial no coincide',
}

export function BiometricTeacher({ sessionId, closed = false }: { sessionId: number; closed?: boolean }) {
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [required, setRequired] = useState<boolean>()
  const [rows, setRows] = useState<{ id: string; student_name: string; reason: string; approved_at: string | null }[]>([])
  useEffect(() => {
    let active = true
    api<{ required: boolean }>(`/sessions/${sessionId}/biometric`).then(value => {
      if (active && !lock.current) setRequired(value.required)
    }).catch(() => { if (active) setMessage('No se pudo consultar el estado de la sesión.') })
    return () => { active = false }
  }, [sessionId])
  async function action(run: () => Promise<void>) {
    if (lock.current) return
    lock.current = true; setBusy(true); setMessage('')
    try { await run() } catch (error) { setMessage((error as Error).message) }
    finally { lock.current = false; setBusy(false) }
  }
  async function load() { setRows(await api<typeof rows>(`/sessions/${sessionId}/biometric/reviews`)) }
  return <details className="bio-review"><summary>Laboratorio biométrico de la sesión</summary>
    <p className={`bio-status ${required ? 'success' : 'notice'}`}>{required === undefined ? 'Consultando estado…' : required ? 'Verificación biométrica activada' : 'Verificación biométrica desactivada'}</p>
    {!closed && required !== true && <button className="btn outline" disabled={busy || required === undefined} onClick={() => void action(async () => {
      await api(`/sessions/${sessionId}/biometric`, 'PUT'); setRequired(true); setMessage('Verificación biométrica requerida en esta sesión.')
    })}>Activar para esta sesión</button>}
    {!closed && required === true && <button className="btn outline" disabled={busy} onClick={() => void action(async () => {
      await api(`/sessions/${sessionId}/biometric`, 'DELETE')
      setRequired(false); setMessage('Verificación facial desactivada. La sesión vuelve al QR normal.')
    })}>Desactivar para esta sesión</button>}
    <button className="btn outline" disabled={busy} onClick={() => void action(load)}>Cargar solicitudes</button>
    {rows.map(row => <article key={row.id} className="bio-request"><strong>{row.student_name}</strong>
      <span>{reasonLabels[row.reason] || 'Revisión solicitada'}</span>
      <span className={`bio-status ${row.approved_at ? 'success' : 'notice'}`}>{row.approved_at ? 'Aprobada' : 'Pendiente'}</span>
      {!row.approved_at && <button className="btn outline" disabled={busy} onClick={() => void action(async () => {
        await api(`/biometric/reviews/${row.id}/approve`, 'POST')
        setRows(current => current.map(item => item.id === row.id ? { ...item, approved_at: new Date().toISOString() } : item))
        setMessage('Asistencia confirmada por revisión docente.')
      })}>Aprobar asistencia</button>}</article>)}
    <p role="status">{busy ? 'Procesando…' : message}</p>
  </details>
}
