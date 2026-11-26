'use strict'
const find = selector => document.querySelector(selector)
const login = find('#login')
const panel = find('#enrollment')
const consent = find('#consent')
const open = find('#open')
const take = find('#capture')
const verifyOpen = find('#verify-open')
const remove = find('#remove')
const cancel = find('#cancel')
const preview = find('#preview')
const video = find('video')
const feedback = find('#feedback')
let current
let busy = false
let stream
let generation = 0
let mode = 'enrollment'
let cameraPending = false
let verificationRequest
let cancelled = false
function message(text, tone='info') {
  feedback.textContent = text
  feedback.dataset.tone = tone
}
async function request(path, options) {
  const response = await fetch(path, {...options, credentials:'same-origin', cache:'no-store'})
  const payload = await response.json()
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'No pudimos completar la solicitud.')
  return payload
}
function controls() {
  open.disabled = busy || !current?.enabled || current?.enrolled || !consent.checked || !!stream
  consent.disabled = busy || !current?.enabled || current?.enrolled
  verifyOpen.disabled = busy || !current?.verification_enabled || !current?.enrolled || !!stream
  take.disabled = busy || !stream || !(mode === 'verification' ? current?.enrolled : consent.checked) || !video.videoWidth
  remove.disabled = busy || !current?.enrolled
  cancel.hidden = !stream && !cameraPending && !verificationRequest
  cancel.disabled = busy && !cameraPending && !verificationRequest
}
function apply(state) {
  current = state
  login.hidden = true
  panel.hidden = false
  find('#policy').textContent = state.enabled ? '' : 'La captura está desactivada mientras se completa la revisión de seguridad.'
  find('#verification-panel').hidden = !state.verification_enabled
  find('#verification-state').textContent = state.enrolled ? 'Tienes un registro facial vigente.' : 'No tienes un registro facial vigente.'
  find('#registration').textContent = state.enrolled ? 'Tienes un registro facial vigente.' : 'Aún no tienes un registro facial.'
  controls()
}
function release() {
  generation += 1
  stream?.getTracks().forEach(track => track.stop())
  stream = null
  video.srcObject = null
  preview.hidden = true
  controls()
}
login.addEventListener('submit', async event => {
  event.preventDefault()
  if (busy) return
  busy = true
  try {
    await request('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(login)))})
    login.reset()
    await refresh()
    message('')
  } catch (error) { login.reset(); message(error.message,'error') }
  finally {busy = false; controls()}
})
async function refresh() {
  apply(await request('/enrollment'))
}
consent.addEventListener('change', () => {
  if (!consent.checked) release()
  controls()
})
open.addEventListener('click', () => {
  if (!open.disabled && consent.checked && current?.enabled) return startCamera('enrollment')
})
verifyOpen.addEventListener('click', () => {
  if (!verifyOpen.disabled && current?.verification_enabled && current.enrolled) return startCamera('verification')
})
async function startCamera(selection) {
  mode = selection
  cancelled = false
  take.textContent = selection === 'verification' ? 'Capturar y verificar' : 'Capturar y registrar'
  if (!navigator.mediaDevices?.getUserMedia) return message('Cámara no disponible. Comprueba que estás usando HTTPS.', 'error')
  cameraPending = true
  const attempt = ++generation
  busy = true
  controls()
  try {
    const acquired = await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'user'},width:{ideal:960},height:{ideal:720}},audio:false})
    if (attempt !== generation || document.hidden) {
      acquired.getTracks().forEach(track => track.stop())
      return
    }
    stream = acquired
    stream.getVideoTracks().forEach(track => track.addEventListener('ended', () => {
      release()
      message('La cámara se desconectó. Actívala otra vez.', 'error')
    }, {once:true}))
    video.srcObject = stream
    preview.hidden = false
    await video.play()
    if (attempt === generation) message('Posiciona tu rostro dentro del óvalo.')
  } catch (error) {
    if (attempt !== generation) return
    release()
    const explanation = error.name === 'NotAllowedError' ? 'Permiso denegado. Habilita la cámara para este sitio.' : 'Cámara no disponible. Comprueba que esté conectada y libre.'
    message(explanation,'error')
  } finally {cameraPending = false; busy = false; controls()}
}
take.addEventListener('click', async () => {
  if (take.disabled) return
  const verifying = mode === 'verification'
  busy = true
  controls()
  const attempt = generation
  const frame = document.createElement('canvas')
  try {
    const scale = Math.min(1,960/Math.max(video.videoWidth,video.videoHeight))
    frame.width = Math.round(video.videoWidth*scale)
    frame.height = Math.round(video.videoHeight*scale)
    frame.getContext('2d').drawImage(video,0,0,frame.width,frame.height)
    const data = await new Promise(resolve => frame.toBlob(resolve,'image/jpeg',.82))
    if (!data || data.size > 384*1024) throw new Error('No se pudo preparar la captura. Inténtalo nuevamente.')
    if (attempt !== generation || document.hidden) return
    release()
    message(verifying ? 'Verificando identidad…' : 'Procesando captura…')
    const headers = verifying
      ? {'Content-Type':'image/jpeg','X-Face-Verification':'confirm'}
      : {'Content-Type':'image/jpeg','X-Explicit-Consent':'yes','X-Consent-Notice':current.notice}
    if (verifying) verificationRequest = new AbortController()
    controls()
    const timeout = setTimeout(() => verificationRequest?.abort(),17000)
    let result
    try {
      result = await request(verifying ? '/verification' : '/enrollment',{
        method:'POST',headers,body:data,signal:verificationRequest?.signal || AbortSignal.timeout(17000),
      })
    } finally { clearTimeout(timeout) }
    if (cancelled) return
    if (!verifying) {
      consent.checked = false
      apply({...current,enrolled:result.enrolled})
    }
    if (verifying) verifyOpen.textContent = 'Reintentar verificación facial'
    message(result.message, verifying && !result.matched ? 'error' : 'success')
  } catch(error) {
    release()
    if (cancelled) return
    if (verifying) {
      await refresh().catch(()=>{})
      verifyOpen.textContent = 'Reintentar verificación facial'
    }
    message(['TimeoutError','AbortError'].includes(error.name) ? 'El tiempo de espera se agotó. Consulta el estado antes de reintentar.' : error.message,'error')
  } finally {frame.width=0;frame.height=0;verificationRequest=undefined;busy=false;controls()}
})
cancel.addEventListener('click', () => {
  cancelled = true
  verificationRequest?.abort()
  release()
  message('Captura cancelada.')
  const trigger = mode === 'verification' ? verifyOpen : open
  trigger.focus()
})
remove.addEventListener('click', async () => {
  if (busy || !current?.enrolled || !confirm('Se eliminará tu plantilla facial. ¿Deseas continuar?')) return
  release()
  busy = true
  controls()
  try {
    const result = await request('/enrollment',{method:'DELETE'})
    consent.checked = false
    apply({...current,enrolled:result.enrolled})
    message('Consentimiento retirado y plantilla eliminada.','success')
  } catch(error) {message(error.message,'error')}
  finally {busy=false;controls()}
})
video.addEventListener('loadedmetadata',controls)
function leave() {
  cancelled = true
  verificationRequest?.abort()
  release()
}
window.addEventListener('pagehide',leave)
document.addEventListener('visibilitychange',()=>{if(document.hidden) leave()})
refresh().catch(()=>{})
