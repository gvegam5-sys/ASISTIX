import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { strict as assert } from 'node:assert'
import { runInNewContext } from 'node:vm'

const source = readFileSync(new URL('./web/ui.js', import.meta.url), 'utf-8')
const tick = () => new Promise(resolve => setImmediate(resolve))

async function view(enabled, camera, state={}, fetchOverride=null) {
  const elements = new Map()
  const listeners = {}
  const document = {
    hidden: false,
    createElement() { return {getContext:()=>({drawImage(){}}),toBlob:resolve=>resolve({size:8})} },
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector,{
        checked:false, dataset:{}, videoWidth:640, videoHeight:480,
        play:async()=>{}, focus(){}, addEventListener(name, cb){ this[name]=cb },
      })
      return elements.get(selector)
    },
    addEventListener(name, cb) { listeners[name]=cb },
  }
  let requests = 0
  const getUserMedia = async options => { requests++; return camera(options) }
  runInNewContext(source,{
    document, navigator:{mediaDevices:{getUserMedia}},
    window:{addEventListener(name,cb){listeners[name]=cb}},
    fetch:fetchOverride || (async()=>({ok:true,json:async()=>({enabled,enrolled:false,notice:'test',...state})})),
    AbortController,AbortSignal,setTimeout,clearTimeout,
  })
  await tick()
  return {get:sel=>elements.get(sel), requests:()=>requests, listeners}
}

test('camera must remain off without explicit consent or server permission',async()=>{
  const disabled = await view(false,()=>{})
  disabled.get('#consent').checked=true
  disabled.get('#consent').change()
  await disabled.get('#open').click()
  assert.equal(disabled.requests(),0)
  const enabled = await view(true,()=>{})
  await enabled.get('#open').click()
  assert.equal(enabled.requests(),0)
})

test('stops every track on cancellation and releases late permission after hide',async()=>{
  let stopped=0
  const media={getTracks:()=>[{stop:()=>stopped++}],getVideoTracks:()=>[]}
  let releasePermission
  const {get,listeners}=await view(true,()=>new Promise(resolve=>{releasePermission=resolve}))
  get('#consent').checked=true
  get('#consent').change()
  const first=get('#open').click()
  releasePermission(media)
  await first
  get('#cancel').click()
  assert.equal(stopped,1)
  const second=get('#open').click()
  listeners.pagehide()
  releasePermission(media)
  await second
  assert.equal(stopped,2)
})

test('guides the user when the camera permission is denied',async()=>{
  const {get}=await view(true,()=>{throw Object.assign(new Error(),{name:'NotAllowedError'})})
  get('#consent').checked=true
  get('#consent').change()
  await get('#open').click()
  assert.match(get('#feedback').textContent,/Permiso denegado/)
})

test('verification requires its own start action and releases the camera after a match', async()=>{
  let stopped=0
  const requests=[]
  const media={getTracks:()=>[{stop:()=>stopped++}],getVideoTracks:()=>[]}
  const {get,requests:cameraCalls}=await view(true,()=>media,{},async (path,options)=>{
    requests.push([path,options])
    return {ok:true,json:async()=>path==='/enrollment'
      ? {enabled:true,enrolled:true,verification_enabled:true}
      : {matched:true,message:'Verificación facial completada correctamente.'}}
  })
  assert.equal(cameraCalls(),0)
  await get('#verify-open').click()
  assert.equal(cameraCalls(),1)
  await get('#capture').click()
  assert.equal(stopped,1)
  assert.equal(requests.at(-1)[0],'/verification')
  assert.equal(requests.at(-1)[1].headers['X-Face-Verification'],'confirm')
  assert.equal(get('#feedback').dataset.tone,'success')
})

test('verification remains disabled with no current template and cancels late permission', async()=>{
  const empty=await view(true,()=>{}, {verification_enabled:true})
  await empty.get('#verify-open').click()
  assert.equal(empty.requests(),0)
  let stop=0
  let permission
  const v=await view(true,()=>new Promise(resolve=>{permission=resolve}),{verification_enabled:true,enrolled:true})
  const pending=v.get('#verify-open').click()
  v.get('#cancel').click()
  permission({getTracks:()=>[{stop:()=>stop++}],getVideoTracks:()=>[]})
  await pending
  assert.equal(stop,1)
  assert.equal(v.get('#preview').hidden,true)
  assert.match(v.get('#feedback').textContent,/cancelada/)
})
