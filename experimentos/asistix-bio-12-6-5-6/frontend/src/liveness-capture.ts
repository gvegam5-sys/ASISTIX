const FRAME_LIMIT = 60 * 1024
const poll = () => new Promise<void>(resolve => setTimeout(resolve, 40))

export class FrameCaptureError extends Error {}

type FrameMark = { capturedAt: number; fingerprint: string }

function hasPixels(video: HTMLVideoElement) {
  const stream = video.srcObject as MediaStream | null
  return video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0 &&
    stream?.getVideoTracks().some(track => track.readyState === 'live' && track.enabled && !track.muted)
}

function diagnostics(video: HTMLVideoElement) {
  const track = (video.srcObject as MediaStream | null)?.getVideoTracks()[0]
  return `vídeo ${video.videoWidth}×${video.videoHeight}, estado ${video.readyState}, tiempo ${video.currentTime.toFixed(2)} s, pista ${track?.muted ? 'silenciada' : track?.readyState ?? 'ausente'}`
}

export async function waitForVideo(video: HTMLVideoElement, active: () => boolean) {
  const deadline=performance.now()+1500
  while (active() && performance.now()<deadline) {
    if (hasPixels(video)) return
    await poll()
  }
  throw new FrameCaptureError(`La cámara aún no está lista (${diagnostics(video)}). Vuelve a abrirla si el problema continúa.`)
}

export async function captureFrame(video: HTMLVideoElement, active: () => boolean, previous: readonly FrameMark[]) {
  const deadline=performance.now()+1500
  const last=previous.at(-1)
  const canvas=document.createElement('canvas')
  try {
    while (active() && performance.now()<deadline) {
      const capturedAt=performance.now()
      if (!hasPixels(video) || (last && capturedAt-last.capturedAt<240)) {
        await poll()
        continue
      }
      const scale=Math.min(1,640/Math.max(video.videoWidth,video.videoHeight))
      canvas.width=Math.round(video.videoWidth*scale)
      canvas.height=Math.round(video.videoHeight*scale)
      const context=canvas.getContext('2d',{willReadFrequently:true})
      if (!context) throw new Error()
      context.drawImage(video,0,0,canvas.width,canvas.height)
      const pixels=context.getImageData(0,0,canvas.width,canvas.height).data
      const digest=await crypto.subtle.digest('SHA-256',pixels)
      const fingerprint=Array.from(new Uint8Array(digest), value=>value.toString(16).padStart(2,'0')).join('')
      if (previous.some(frame=>frame.fingerprint===fingerprint)) {
        await poll()
        continue
      }
      for (const quality of [0.72,0.64,0.56]) {
        if (!active()) throw new Error()
        const jpeg=await new Promise<Blob | null>(resolve=>{
          const timer=setTimeout(()=>resolve(null),500)
          canvas.toBlob(blob=>{clearTimeout(timer);resolve(blob)},'image/jpeg',quality)
        })
        if (jpeg?.type==='image/jpeg' && jpeg.size>0 && jpeg.size<=FRAME_LIMIT && active()) {
          return {jpeg,capturedAt,fingerprint}
        }
      }
      throw new FrameCaptureError('Safari no pudo preparar un JPEG dentro del límite de tamaño. Vuelve a intentar este paso.')
    }
  } catch (error) {
    if (error instanceof FrameCaptureError) throw error
    throw new FrameCaptureError('No se pudo leer el fotograma de la cámara. Vuelve a intentar este paso.')
  } finally {
    canvas.width=canvas.height=0
  }
  throw new FrameCaptureError(`No se obtuvo un fotograma nuevo (${diagnostics(video)}). Vuelve a intentar este paso.`)
}
