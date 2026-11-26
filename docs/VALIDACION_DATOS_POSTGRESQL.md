# Validación inicial de datos en PostgreSQL

El paso 12.8.4 usó PostgreSQL 17.12 en `127.0.0.1:5433`, la base independiente `asistix_lab_pg` y la revisión Alembic `0001_initial`. Antes de cargar se comprobó que las 11 tablas académicas estaban vacías. Las pruebas de API usaron FastAPI TestClient dentro del proceso.

## Preparar y generar

Utiliza el entorno Python del laboratorio y las dependencias fijadas del repositorio. Si faltan las dependencias mínimas del backend, instala únicamente en ese entorno.

```powershell
$py = (Resolve-Path .venv/Scripts/python.exe).Path
& $py -m pip install -c backend/requirements.lock.txt fastapi pydantic-settings email-validator 'pwdlib[argon2]' PyJWT httpx
& ./tools/pg-lab-env.ps1
$env:DEMO_MODE = 'true'
$env:JWT_SECRET = & $py -c "import secrets; print(secrets.token_urlsafe(48))"
$reference = [DateTimeOffset]::UtcNow.ToString('o')
Push-Location backend
try {
    & $py -m alembic current
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo verificar la revisión' }
    & $py -m app.seed --extended --reference-utc $reference
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo cargar la semilla' }
    & $py -m app.seed --extended --reference-utc $reference
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo verificar la segunda ejecución' }
} finally {
    Pop-Location
    Remove-Item Env:DATABASE_URL,Env:DEMO_MODE,Env:JWT_SECRET -ErrorAction SilentlyContinue
}
```

Antes de cargar, confirma `0001_initial (head)`. Para repetir la comparación, usa una SQLite temporal nueva en otra terminal, configura su `DATABASE_URL` explícitamente, aplica `alembic upgrade head` y reutiliza el mismo valor de `--reference-utc`. Retira el archivo temporal al terminar. El modo ampliado requiere el destino explícito y un esquema migrado. Conserva el mecanismo de hash Argon2id de ASISTIX.

## Resultados

| Tabla | PostgreSQL | SQLite |
|---|---:|---:|
| roles | 3 | 3 |
| users | 11 | 11 |
| teachers | 2 | 2 |
| students | 8 | 8 |
| courses | 5 | 5 |
| enrollments | 27 | 27 |
| class_sessions | 30 | 30 |
| qr_tokens | 0 | 0 |
| attendance | 161 | 161 |
| alerts | 9 | 9 |
| audit_log | 4 | 4 |

Hay 29 sesiones finalizadas y una abierta. Las cuatro entradas de auditoría corresponden a los accesos de prueba, dos docentes, un administrador y un estudiante. La semilla no genera tokens QR.

- Una segunda ejecución no modificó ninguna fila de la primera carga en ninguno de los motores. La comparación entre motores igualó las filas académicas y los datos devueltos por la API. Se excluyeron los hashes de contraseña por sus sales aleatorias y la marca técnica de creación de alertas.
- Se comprobaron todas las relaciones y restricciones únicas del esquema y las fechas UTC. SQLite no informó infracciones de claves foráneas. PostgreSQL rechazó un intento de asistencia duplicada con el código `23505`. Las siete secuencias generaron valores superiores al mayor ID de su tabla, lo que consumió números de secuencia sin añadir filas académicas.
- La autenticación, el alcance de materias, el historial y los resultados de ausentismo coincidieron. El administrador vio cinco materias, los docentes vieron cuatro y una, y el estudiante vio cuatro propias con los cuatro niveles de riesgo. El acceso a gestión de usuarios quedó reservado al administrador.
- La SQLite temporal se retiró. TestClient emitió el aviso conocido de deprecación de Starlette sobre HTTPX. La validación física y las pruebas de concurrencia quedan fuera de este paso.
