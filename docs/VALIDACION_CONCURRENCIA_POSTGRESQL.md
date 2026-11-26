# Validación de concurrencia y compatibilidad con PostgreSQL

Paso 12.8.5 sobre `experimental/postgresql-12.8`, base `711328e`, con PostgreSQL 17.12 y Python 3.13.7.

## Reproducción

Desde `backend`, con el entorno Python experimental activo, ejecuta `python -m pytest -q -s tests`. Sin `ASISTIX_TEST_DATABASE_URL`, la suite crea y retira una SQLite temporal. Para PostgreSQL, el administrador del clúster local debe crear una base vacía con nombre `asistix_test_12_8_5_<8 dígitos hexadecimales>` propiedad de `asistix_lab`, habilitar autenticación SCRAM para ese nombre únicamente en `127.0.0.1/32` y configurar `ASISTIX_TEST_DATABASE_URL` en esa terminal con `postgresql+psycopg`. La suite verifica el destino y exige que no haya tablas antes de iniciar. Restablece la regla local y elimina solo la base de prueba al terminar.

Los casos comunes cubren autenticación, permisos y matrículas, QR, sesiones, historial, exportaciones y ausentismo, incluidos UTC y los límites de día en `America/Guayaquil`. Los casos de fila bloqueada y carga se ejecutan únicamente en PostgreSQL. Se usan peticiones ASGI simultáneas y transacciones independientes. Un bloqueo controlado se mantiene hasta observar las solicitudes en espera mediante `pg_stat_activity`.

El ensayo verificó una sola apertura, un solo registro del mismo estudiante, dos registros para estudiantes distintos, un único token por ronda de emisión o renovación, y un resultado coherente al escanear durante un cierre. Se rechazaron los QR vencidos, inválidos o con sesión incorrecta. La prueba de fallo de auditoría provocó deliberadamente una infracción de clave foránea y comprobó que la asistencia se revirtiera junto con la auditoría. Un reintento válido registró ambas.

Las mediciones incluyen la cola del pool y la espera inducida por el bloqueo de prueba. Son observaciones locales de una ejecución con datos ficticios, sin tráfico de red externo ni validación física en Safari. Los clientes se lanzan juntos y el pool limita cuántas transacciones avanzan al mismo tiempo.

## Resultados

| Verificación | Resultado |
|---|---|
| SQLite | 69 pruebas aprobadas. Las 11 específicas de PostgreSQL se omitieron. |
| PostgreSQL | 69 pruebas comunes aprobadas y 11 específicas aprobadas con el arnés definitivo. |
| Frontend | 53 pruebas aprobadas, TypeScript y compilación de producción correctos. |
| Paridad de exportaciones | Coincidieron filas CSV, texto extraído del PDF y valores de celdas Excel para los tres roles sobre una muestra fija. La comparación fue de contenido lógico. |
| Auditoría y duplicados | Los registros de auditoría coincidieron con las asistencias confirmadas. La reversión por fallo de auditoría dejó ambas tablas sin registros nuevos de la sesión. |

La huella común del contenido lógico de los reportes fue `dddae358c2002e1db65514bc8970ca48ba8777552f428664a05652fc010fbbac`.

### Carga controlada en PostgreSQL

| Estudiantes | HTTP 201 | Rechazos | Errores | p50 (ms) | p95 (ms) | Máx. (ms) | Esperas de fila observadas al liberar el bloqueo |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 10 | 0 | 0 | 372,36 | 515,67 | 515,67 | 3 |
| 25 | 25 | 0 | 0 | 583,96 | 717,53 | 780,56 | 3 |
| 50 | 50 | 0 | 0 | 833,76 | 1084,77 | 1095,14 | 3 |

No hubo HTTP 500, esperas agotadas ni interbloqueos en la repetición definitiva. El p95 usa el rango más próximo dentro de cada muestra.

### Incidencias e índices

- En la primera pasada, a partir de 25 estudiantes el observador competía por una conexión del pool mientras el arnés mantenía el bloqueo. Se registró un timeout del observador. En la tanda de 50, esa espera artificial también superó la vigencia del QR y produjo rechazos y errores. Se reservó la conexión de observación antes de lanzar las solicitudes y se repitieron únicamente los 11 casos afectados por el arnés. La lógica de ASISTIX no se modificó.
- `EXPLAIN (ANALYZE, BUFFERS)` de las consultas reales con la semilla de prueba devolvió 157 filas en historial y 192 en ausentismo. Los tiempos de ejecución fueron 0,413 y 0,451 ms. En esa escala se observaron recorridos secuenciales, uniones hash y ordenación. Estos planes no justifican añadir índices. Al probar un volumen representativo conviene medir de nuevo por materia y rango de fechas y observar el tiempo en el pool y en los bloqueos.
- `FOR UPDATE` serializó las operaciones probadas sobre la misma materia o sesión. Se conservan las restricciones únicas de asistencia como garantía de base de datos. Las pruebas no detectaron una carrera de negocio que exigiera una corrección.
- TestClient emitió el aviso conocido de deprecación de Starlette sobre HTTPX. Las bases PostgreSQL desechables se retiraron, se restauró el acceso local original y la huella de datos y secuencias de la base de demostración coincidió antes y después de la regresión.
