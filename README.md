# ASISTIX

ASISTIX gestiona la asistencia universitaria mediante códigos QR dinámicos, paneles por rol y reportes exportables.

**Universidad Estatal de Milagro (UNEMI)**

Ingeniería en Software · Construcción de Software

Docente · Jonathan Eduardo Merino Gavilanes

**Integrantes**

- Carlos Simisterra
- Gastón Vega
- Jesus Constante

## Funcionalidades

- Autenticación y paneles de administrador, docente y estudiante.
- Sesiones de clase y QR dinámico con caducidad, control de matrícula y una asistencia por estudiante y sesión.
- Indicadores de asistencia, gráficas por materia y por semana, historial responsivo y filtros por materia y fechas.
- Exportación CSV, PDF y Excel con el alcance y los filtros aplicados al historial.
- Zona institucional `America/Guayaquil` y persistencia temporal en UTC.
- Laboratorio separado de verificación facial 1:1 vinculada al QR, con consentimiento, revocación, activación por sesión y revisión docente.

## Tecnologías y requisitos

Python 3.13, FastAPI, SQLAlchemy y SQLite para la demostración. React, TypeScript, Vite, Tailwind CSS y Recharts para la interfaz. ReportLab y XlsxWriter para los reportes. Se recomienda Node.js 22 LTS y npm. El laboratorio biométrico usa YuNet, SFace, ONNX Runtime CPU y AppContainer de Windows.

## Instalación y ejecución local

En PowerShell, desde la raíz del repositorio, inicia el backend en una terminal. La semilla crea una base **ficticia** local y un archivo de configuración ignorado por Git.

```powershell
Set-Location backend
py -3.13 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
Copy-Item .env.example .env
$jwt = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
(Get-Content .env) -replace '^JWT_SECRET=.*$', "JWT_SECRET=$jwt" | Set-Content .env
& .\.venv\Scripts\python.exe -m app.seed
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

En otra terminal, desde la raíz del repositorio:

```powershell
Set-Location frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Abre [ASISTIX local](http://localhost:5173) e ingresa con `admin@asistix.demo`, `docente@asistix.demo` o `estudiante@asistix.demo`. La semilla muestra la contraseña ficticia de demostración. Usa una sesión de navegador independiente para el docente y el estudiante. El docente abre una sesión y muestra el QR, y el estudiante registra su asistencia. Revisa luego el historial y las exportaciones. Para usar la cámara desde otro dispositivo es necesario configurar HTTPS local y confiar en el certificado del laboratorio.

Ejecuta `python -m pytest` desde el backend con el entorno virtual configurado. Desde el frontend, usa `npm test` y `npm run build`.

## Laboratorio biométrico

El código experimental está en [12.6.5.4](experimentos/asistix-bio-12-6-5-4) y reutiliza el [piloto 12.6.5.3](experimentos/asistix-bio-12-6-5-3). El flujo separa el transporte TLS del procesamiento facial, compara con la plantilla cifrada de la cuenta autenticada y vuelve a comprobar el desafío QR antes de registrar una sola asistencia.

La verificación 1:1 y su integración con QR se validaron físicamente en Safari de iPhone con un participante adulto voluntario. Se comprobó el consentimiento, la asistencia única, el bloqueo de duplicados, la verificación nueva en sesiones consecutivas, la cancelación, la revocación y el QR convencional. Las pruebas automatizadas con JPEG sintéticos cubren también la no coincidencia y la concurrencia. En el QR convencional se muestra «Verificación facial no requerida».

El piloto físico está cerrado y la captura real permanece desactivada por defecto. Una nueva prueba requiere autorización, un entorno Windows aislado, HTTPS y firewall propios del laboratorio y cuentas voluntarias temporales. La validación con un participante no permite estimar la precisión biométrica general. La prueba de vida y la validación con PostgreSQL siguen pendientes.

El repositorio contiene el código, los manifiestos y las licencias. Los modelos se obtienen de las URLs oficiales del manifiesto verificando SHA-256. Los retratos sintéticos, binarios instalados, claves, certificados y bases de datos se preparan fuera de Git. Consulta las [instrucciones del laboratorio](experimentos/README.md).
