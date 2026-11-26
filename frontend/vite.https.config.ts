import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createPrivateKey, X509Certificate } from 'node:crypto'
import { isIP } from 'node:net'
import { defineConfig, loadEnv, mergeConfig } from 'vite'
import baseConfig from './vite.config'

// Configuración optativa: no cambia ni reinicia el servidor HTTP existente.
export default defineConfig((configEnv) => {
  const env = loadEnv(configEnv.mode, process.cwd(), '')
  const cert = readFileSync(resolve(process.cwd(), env.HTTPS_CERT_FILE || '../.certs/asistix.pem'))
  const key = readFileSync(resolve(process.cwd(), env.HTTPS_KEY_FILE || '../.certs/asistix-key.pem'))
  const host = env.HTTPS_HOST || '127.0.0.1'
  const certificate = new X509Certificate(cert)
  const validHost = isIP(host) ? certificate.checkIP(host) : certificate.checkHost(host)
  if (!validHost || Date.parse(certificate.validTo) <= Date.now() || Date.parse(certificate.validFrom) > Date.now()) {
    throw new Error('Certificado no vigente o no válido para HTTPS_HOST. Ejecuta scripts/setup-https.ps1 con la IPv4 Wi-Fi actual.')
  }
  if (!certificate.checkPrivateKey(createPrivateKey(key))) {
    throw new Error('La clave HTTPS no corresponde al certificado.')
  }
  const https = { cert, key, minVersion: 'TLSv1.2' as const }
  return mergeConfig(baseConfig(configEnv), {
    server: {
      host, port: 5174, strictPort: true, https,
      headers: { 'Permissions-Policy': 'camera=(self), microphone=()' },
      fs: { deny: ['.env', '.env.*', '**/.git/**', '**/.certs/**', '**/*.{pem,key,crt,p12,pfx}'] },
    },
    preview: { host, port: 4174, strictPort: true, https },
  })
})
