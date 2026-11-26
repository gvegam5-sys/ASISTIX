# Migraciones de esquema de ASISTIX

La revisión `0001_initial` crea el esquema académico en PostgreSQL 17.12 y SQLite. Alembic obtiene los modelos de `backend/app/models.py` sin iniciar FastAPI ni leer la clave de sesión. El archivo de configuración lee `DATABASE_URL` del proceso. El repositorio no contiene la URL con credenciales.

## Preparación

Desde la raíz de la copia de trabajo experimental en Windows, usa Python 3.13 x64. Si el entorno todavía no existe, créalo e instala el conjunto fijado de dependencias de migración.

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r backend\requirements-migrations.lock.txt
```

Con el clúster independiente activo, carga la conexión local con el script del paso 12.8.2. El script lee la credencial DPAPI del laboratorio y configura el entorno de esta terminal. El destino de 12.8.3 es exclusivamente `asistix_lab_pg` en `127.0.0.1:5433`.

```powershell
& .\tools\pg-lab-env.ps1
$py = '.\.venv\Scripts\python.exe'
& $py -m alembic -c backend\alembic.ini upgrade head
& $py -m alembic -c backend\alembic.ini current
& $py -m alembic -c backend\alembic.ini check
```

Para revisar el DDL de la actualización sin aplicarlo, usa `upgrade head --sql`. La revisión inicial se generó con `revision --autogenerate` sobre un esquema vacío y se revisó antes de ejecutarla. Revisa siempre las revisiones generadas antes de aplicarlas.

## Reversión y SQLite desechable

`downgrade base` elimina las tablas que crea la revisión inicial, junto con sus datos si los hubiera. Para el ensayo de 12.8.3, se comprobó que las tablas estuvieran vacías antes de revertir.

```powershell
& $py -m alembic -c backend\alembic.ini downgrade base
& $py -m alembic -c backend\alembic.ini current
& $py -m alembic -c backend\alembic.ini upgrade head
& $py -m alembic -c backend\alembic.ini check
Remove-Item Env:DATABASE_URL
```

Para reproducir el ensayo SQLite, usa una terminal separada y un archivo temporal nuevo.

```powershell
$sqlite = New-TemporaryFile
try {
    $env:DATABASE_URL = "sqlite:///$($sqlite.FullName.Replace('\','/'))"
    $py = '.\.venv\Scripts\python.exe'
    & $py -m alembic -c backend\alembic.ini upgrade head
    & $py -m alembic -c backend\alembic.ini downgrade base
    & $py -m alembic -c backend\alembic.ini upgrade head
    & $py -m alembic -c backend\alembic.ini check
} finally {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $sqlite.FullName
}
```

## Esquema y arranque

Las 11 tablas son `roles`, `users`, `students`, `teachers`, `courses`, `enrollments`, `class_sessions`, `qr_tokens`, `attendance`, `alerts` y `audit_log`. La tabla `alembic_version` registra la revisión. Después de revertir a `base`, puede quedar vacía.

Se conservan los tipos, la nulabilidad, las claves primarias y foráneas, las restricciones únicas de asistencia por estudiante y sesión o token, y el límite de niveles de alerta a `medio` y `alto`. Las fechas mantienen la convención UTC sin zona. Los valores predeterminados de los modelos se aplican en Python, con generación de IDs enteros mediante secuencias de PostgreSQL o mediante SQLite. Se conservan los índices implícitos de las restricciones.

En PostgreSQL, ejecuta Alembic antes de iniciar la API o crear una semilla. El arranque y la semilla mantienen `create_all()` únicamente para la ruta SQLite heredada. Para ensayar Alembic en SQLite, usa un archivo vacío y evita arrancar la API o la semilla antes de la revisión inicial. El ensayo de este paso no arrancó la aplicación ni ejecutó la semilla.

## Resultado de 12.8.3

El ciclo `upgrade head → downgrade base → upgrade head` pasó en PostgreSQL 17.12 y en una SQLite desechable, con Alembic 1.20.1, SQLAlchemy 2.0.55 y Psycopg 3.3.6. Se contrastó el esquema reflejado con los modelos en ambos motores. `alembic check` no detectó operaciones pendientes. PostgreSQL quedó en `0001_initial` con las 11 tablas de aplicación vacías. El archivo SQLite de prueba se retiró al finalizar.
