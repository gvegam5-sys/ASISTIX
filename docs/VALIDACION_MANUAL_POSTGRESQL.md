# Validación manual de ASISTIX con PostgreSQL

Paso 12.8.6. Validación del 26 de noviembre de 2026 en `experimental/postgresql-12.8`, con base `119553f` y datos ficticios en `asistix_lab_pg` (PostgreSQL 17.12).

## Pruebas manuales confirmadas

- Desde el PC, el docente generó el QR de Ingeniería de Software y observó su renovación automática. Desde un iPhone físico con Safari, el estudiante escaneó el código con la cámara, registró su asistencia y recibió el rechazo al escanearlo de nuevo.
- La sesión 33 registró a Isaac Mendoza a las 12:12:46 (hora de Ecuador continental). El historial mostró 21 registros. Al filtrar por materia y fecha aparecieron las sesiones 32 y 33. Safari abrió las vistas previas de CSV, PDF y Excel.
- El estudiante observó 75 % de asistencia y 25 % de ausencias, con gráficas interactivas al tacto. Ingeniería de Software mostró 70 %, riesgo medio y racha activa de cero ausencias. Base de Datos mostró 75 % y riesgo medio. Inteligencia Artificial mostró 100 % y riesgo bajo. Laboratorio de Proyectos mostró datos insuficientes.
- El administrador observó 8 estudiantes, 74,8 % de asistencia, 25,2 % de ausencias, 14 alertas activas y recomendaciones institucionales para casos de riesgo alto.

## Comprobaciones automáticas

- La validación inicial aprobó el acceso y los paneles para los tres roles, apertura y cierre de sesiones, renovación del QR, registro convencional, rechazo de duplicados, filtros, exportaciones, gráficas y ausentismo. Chrome mostró Resumen, Historial y Alertas sin desbordamiento horizontal a 320, 390 y 1440 px. El arranque del backend verificó que su motor y su conexión activa apuntaban a PostgreSQL en `127.0.0.1:5433`.
- La consulta final a PostgreSQL encontró exactamente una asistencia en la sesión 33 (ID 165, estudiante 3), con marca de tiempo 17:12:46,851622 UTC. Existe una sola entrada `attendance:33`, del mismo actor. La sesión cerró a las 12:13:49,712168 (hora de Ecuador continental) y no quedaron sesiones abiertas.
- Las consultas confirmaron los 21 registros del estudiante y las sesiones 32 y 33 para el filtro indicado. Los totales de asistencia coincidieron con el panel, con 21 de 28 para el estudiante y 163 de 218 para el administrador. Se cotejaron los indicadores por materia y las 14 alertas activas. Laboratorio de Proyectos tenía dos sesiones elegibles y conservó la clasificación de datos insuficientes.
- Las comprobaciones específicas de permisos confirmaron el alcance institucional del administrador sobre las cinco materias y el acceso exclusivo de ese rol a usuarios y auditoría. El primer docente vio sus cuatro materias y el segundo solo Redes de Computadoras. Cada docente pudo consultar su lista de asistencia y recibió HTTP 404 al intentar consultar la del otro o filtrar su historial por una materia ajena. El estudiante solo vio su propia asistencia y recibió HTTP 403 al solicitar las listas de asistencia.

## Integridad y apagado

Las huellas SHA-256 de las 16 bases protegidas y del ZIP coincidieron con la auditoría previa. Se cotejaron `master` (`6e5319d`), las 18 etiquetas y las ramas experimentales anteriores. Se detuvieron el frontend HTTPS y el backend del laboratorio. PostgreSQL se detuvo con `pg_ctl stop -m fast` y conservó su directorio de datos. Los puertos 5286, 8186 y 5433 quedaron sin escucha.

El cierre reutilizó los resultados iniciales y de la regresión 12.8.5. Se ejecutaron las consultas y comprobaciones específicas pendientes.
