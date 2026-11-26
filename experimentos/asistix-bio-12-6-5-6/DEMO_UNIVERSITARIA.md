# ASISTIX 12.6.5.6 · Demostración universitaria

La demostración local parte del commit `f75a754a7fc8c769a97ae31878e5a404b8035315`, etiqueta `asistix-prueba-vida-real-validada`. Usa una SQLite nueva, cuentas ficticias y el catálogo sintético. La comparación facial ejecuta el motor aislado con retratos sintéticos. La decisión de prueba de vida se simula y está identificada en la interfaz. La cámara y el micrófono están bloqueados, y la entrada física sigue desactivada.

Abre `http://127.0.0.1:5198/` en dos perfiles del navegador del PC. La API escucha solo en `127.0.0.1:8020`. Usa `docente@asistix.demo` y `estudiante@asistix.demo`, con la clave ficticia de la semilla.

1. Como docente, abre una sesión y activa la verificación. Copia un token desde **Token para demostración sin cámara**.
2. Como estudiante, pega el token, da el consentimiento y registra la plantilla sintética. Valida un token vigente y selecciona **Retrato A** para la cuenta principal. Comprueba una sola asistencia y que otro escaneo bloquee el duplicado.
3. En otra sesión, prueba la cancelación y comprueba que el usuario no tenga una asistencia. El **Retrato B** permite mostrar un rechazo simulado. Usa un QR nuevo para cada intento. Solicita revisión docente si quieres mostrar esa alternativa.
4. Retira el consentimiento. Comprueba que el próximo intento biométrico vuelva a exigir registro. Desactiva la biometría como docente, usa un QR renovado y confirma «Verificación facial no requerida».

La validación física previa en Safari cubrió el rostro del voluntario y una fotografía en pantalla. Sigue pendiente la fotografía impresa. El vídeo pregrabado obtuvo captura insuficiente y queda pendiente una evaluación concluyente de detección de vídeo. Tampoco se estimó la precisión biométrica general. El flujo de canvas y liberación de cámara se conserva del paso anterior. Esta etapa no repite la prueba física.

## Reproducción en Windows

Usa Python con las dependencias del backend instaladas y Node con las dependencias de `frontend`. El laboratorio 12.6.5.3 debe estar en la carpeta hermana `asistix-bio-12-6-5-3`, con el trabajador AppContainer preparado y los retratos sintéticos autorizados del catálogo. No copies la base de la demostración validada.

Desde la raíz del laboratorio 12.6.5.6, prepara una base nueva solamente si aún no existe. Las claves se generan localmente.

```powershell
$lab = (Get-Location).Path
$env:DATABASE_URL = 'sqlite:///' + (($lab + '/backend/asistix-biometria.db').Replace('\','/'))
$env:BIOMETRIC_KEY_FILE = Join-Path $lab 'tools/instance/biometric.key'
$env:DEMO_MODE = 'true'
$env:BIOMETRIC_LAB = 'true'
Set-Location "$lab/backend"
if (!(Test-Path asistix-biometria.db)) {
    python -B -c "import os,pathlib,secrets; d=pathlib.Path('asistix-biometria.db'); d.touch(exist_ok=False); k=pathlib.Path(os.environ['BIOMETRIC_KEY_FILE']); k.parent.mkdir(parents=True,exist_ok=True); k.open('xb').write(secrets.token_bytes(32)); k.with_name('jwt.secret').open('x').write(secrets.token_urlsafe(48))"
    if ($LASTEXITCODE) { throw 'Falló la preparación de la SQLite aislada.' }
    $env:JWT_SECRET = Get-Content -Raw "$lab/tools/instance/jwt.secret"
    python -B -m app.seed
    if ($LASTEXITCODE) { throw 'Falló la semilla.' }
    python -B -m app.biometric_schema
    if ($LASTEXITCODE) { throw 'Falló la migración.' }
    python -B -c "from app.biometric_attendance import initialize_revocations; initialize_revocations()"
    if ($LASTEXITCODE) { throw 'Falló el registro local de revocaciones.' }
}
$env:JWT_SECRET = Get-Content -Raw "$lab/tools/instance/jwt.secret"
python -B -m uvicorn app.university_demo:app --host 127.0.0.1 --port 8020 --no-proxy-headers --no-access-log
```

Desde otra terminal en `frontend`, ejecuta `npm ci`, `npm run build` y luego `npx vite preview --host 127.0.0.1 --port 5198 --strictPort`.
