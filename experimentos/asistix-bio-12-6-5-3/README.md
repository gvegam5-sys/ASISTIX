# Laboratorio de registro facial real

Copia de revisión del paso 12.6.5.2. Véase [la validación](../../docs/VALIDACION_REGISTRO_FACIAL_REAL.md). Este árbol contiene código y pruebas. Las dependencias instaladas, los ejecutables Windows, los modelos y retratos de prueba, las ACL locales, las claves, las SQLite y la configuración de ejecución se mantienen en el laboratorio aislado existente.

Para reproducir en Windows, provisionar por separado Python 3.13.7 con ONNX Runtime 1.24.4, OpenCV headless 4.13.0.92, NumPy 2.4.4, cryptography 46.0.7 y las dependencias web locales de ASISTIX. Verificar los modelos y las muestras con las huellas fijadas en el código. Se necesita el runtime Windows dedicado de supervisor, gateway, relé y motor, con sus perfiles y las ACL limitadas al directorio de cada componente. El código presupone una ubicación local a dos niveles de la raíz del proyecto para encontrar la CA y las herramientas cuando el operador autoriza habilitar el piloto. La copia de respaldo no constituye un despliegue.

Ejecutar desde el laboratorio provisionado, con la captura real cerrada:

- `python -B -s -m unittest -q test_registro`
- `node test_ui.mjs`
- `python -B -s -m test_supervisor_piloto`

La última prueba requiere Windows con AppContainer, el runtime aislado y las muestras sintéticas verificadas. Solo inicia un listener efímero en loopback y usa SQLite y certificados temporales. La apertura del sustrato Wi-Fi del piloto es una operación independiente que requiere autorización.

## Dependencias y reconstrucci?n del entorno

Versiones y licencias verificadas en el entorno ejecutado. La comprobaci?n de dependencias con `pip check` fue satisfactoria.

| Dependencia | Versi?n | Licencia declarada |
| --- | --- | --- |
| FastAPI | 0.161.1 | MIT |
| Starlette | 1.9.0 | BSD-3-Clause |
| AnyIO | 4.15.1 | MIT |
| Pydantic y pydantic-core | 2.14.1 y 2.50.1 | MIT |
| h11 | 0.16.0 | MIT |
| Uvicorn, httpx y websockets | 0.54.0, 0.28.1 y 17.3 | BSD-3-Clause |
| ONNX Runtime CPU | 1.24.4 | MIT |
| OpenCV headless | 4.13.0.92 | Apache-2.0 |
| NumPy | 2.4.4 | BSD-3-Clause y licencias de componentes incluidas |
| cryptography | 46.0.7 | Apache-2.0 o BSD-3-Clause |
| YuNet 2023mar | 2023mar | MIT |
| SFace 2021dec | 2021dec | Apache-2.0 |

En el directorio local del laboratorio, usar Python **3.13.7 x64** y los paquetes de las versiones indicadas desde el repositorio de paquetes aprobado. Crear un entorno exclusivo y verificar sus dependencias:

```powershell
py -3.13 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install fastapi==0.161.1 starlette==1.9.0 anyio==4.15.1 pydantic==2.14.1 pydantic-core==2.50.1 h11==0.16.0 uvicorn==0.54.0 httpx==0.28.1 websockets==17.3 onnxruntime==1.24.4 opencv-python-headless==4.13.0.92 numpy==2.4.4 cryptography==46.0.7
& .\.venv\Scripts\python.exe -m pip check
```

1. Conservar los avisos de dependencias instaladas. Obtener los modelos desde la revisi?n oficial indicada en `engine/models/manifest.json` y comprobar sus SHA-256. Para reproducir la suite completa se necesitan los dos retratos sint?ticos ya verificados del laboratorio local y Node.js y Chrome para sus ensayos de interfaz. Los retratos y los modelos no van en Git.
2. Preparar los cuatro ejecutables nativos dedicados, copias locales del runtime Python compatible, y sus archivos `python313._pth` apuntando a sus dependencias locales. Las ubicaciones esperadas son `runtime/pilot-supervisor/asistix-supervisor.exe`, `runtime/pilot-relay/asistix-relay.exe`, `runtime/pilot-gateway/asistix-gateway.exe` y `runtime/pilot-python/asistix-face.exe`. El c?digo y dependencias de cada sandbox se copian a su subdirectorio propio, sin incluir bases ni claves. El lanzador `appcontainer_piloto.py` concede acceso acotado al SID de cada AppContainer. Las ACL y el firewall deben verificarse en la instalaci?n de destino.
3. Ejecutar primero las pruebas sint?ticas de loopback indicadas arriba. La reproducci?n desde un clon limpio requiere provisionar el runtime y los recursos externos al repositorio. El entorno local ya provisionado fue el que se valid?. Esta lista fija dependencias principales, pero no sustituye un archivo de bloqueo con huellas para todas las transitivas.

## Inventario del respaldo propuesto

- docs/VALIDACION_REGISTRO_FACIAL_REAL.md
- laboratorios/registro-facial-real/README.md
- `laboratorios/registro-facial-real/appcontainer_piloto.py`
- `laboratorios/registro-facial-real/comprobar_aislamiento.py`
- `laboratorios/registro-facial-real/ejecutar_registro_voluntario.py`
- `laboratorios/registro-facial-real/engine/benchmark.py`
- `laboratorios/registro-facial-real/engine/models/face_detection_yunet-LICENSE.txt`
- `laboratorios/registro-facial-real/engine/models/face_recognition_sface-LICENSE.txt`
- `laboratorios/registro-facial-real/engine/models/manifest.json`
- `laboratorios/registro-facial-real/errores_captura.py`
- `laboratorios/registro-facial-real/firewall-piloto.ps1`
- `laboratorios/registro-facial-real/firewall-wifi-piloto.ps1`
- `laboratorios/registro-facial-real/gateway_persistente.py`
- `laboratorios/registro-facial-real/gateway_tls_piloto.py`
- `laboratorios/registro-facial-real/motor.py`
- `laboratorios/registro-facial-real/preparar.py`
- `laboratorios/registro-facial-real/preparar_registro.py`
- `laboratorios/registro-facial-real/probar_gateway.py`
- `laboratorios/registro-facial-real/probar_gateway_restringido.py`
- `laboratorios/registro-facial-real/probar_intermediarios.py`
- `laboratorios/registro-facial-real/registro.py`
- `laboratorios/registro-facial-real/rele_identidad.py`
- `laboratorios/registro-facial-real/rele_tls.py`
- `laboratorios/registro-facial-real/supervisor_piloto.py`
- `laboratorios/registro-facial-real/test-firewall-piloto.ps1`
- `laboratorios/registro-facial-real/test_browser_appcontainer.py`
- `laboratorios/registro-facial-real/test_https_appcontainer.py`
- `laboratorios/registro-facial-real/test_identidad_rele.py`
- `laboratorios/registro-facial-real/test_registro.py`
- `laboratorios/registro-facial-real/test_rele_concurrente.py`
- `laboratorios/registro-facial-real/test_rele_tls_piloto.py`
- `laboratorios/registro-facial-real/test_supervisor_piloto.py`
- `laboratorios/registro-facial-real/test_ui.mjs`
- `laboratorios/registro-facial-real/token_restringido.py`
- `laboratorios/registro-facial-real/verificar_voluntario.py`
- `laboratorios/registro-facial-real/web/index.html`
- `laboratorios/registro-facial-real/web/ui.css`
- `laboratorios/registro-facial-real/web/ui.js`
- `laboratorios/registro-facial-real/worker_sintetico_ipc.py`
