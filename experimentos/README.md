# Laboratorios de reconocimiento facial

`asistix-bio-12-6-5-3` contiene el piloto independiente de verificación 1:1. Consulta su README y el manifiesto de YuNet y SFace. `asistix-bio-12-6-5-4` contiene la integración experimental de asistencia, frontend, gateway TLS, supervisor, adaptador del trabajador y prueba QR.

En la máquina de desarrollo la demo integrada usa frontend en loopback 5190 y API 8016. Inicia una sesión como docente, activa biometría, copia el token QR vigente y pégalo en la cuenta ficticia del estudiante. Tras el consentimiento para la plantilla sintética, la muestra A confirma la asistencia de la cuenta principal y la B permite mostrar el rechazo. El docente puede desactivar la biometría y volver al QR normal. La revisión docente permanece disponible.

Para reconstruir ese laboratorio en otra máquina se necesita preparar los runtimes restringidos de Windows y una SQLite separada con claves nuevas, instalar las dependencias del proyecto y las del motor facial, descargar los modelos oficiales según el manifiesto, y disponer del catálogo sintético autorizado con los SHA-256 definidos en el código. Los scripts de ensayo esperan los runtimes y ese catálogo ya preparados. Adapta a la máquina de destino las rutas locales, la IP, el certificado y los filtros de firewall. El laboratorio requiere preparación adicional respecto a la instalación base de la raíz.

La prueba `asistix-bio-12-6-5-4/scripts/test-verificacion-qr.py` usa una copia SQLite desechable. El arranque de `pilot/run_gateway.py` conserva la captura física desactivada por defecto.
