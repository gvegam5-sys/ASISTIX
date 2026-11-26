# Validación del análisis inteligente de ausentismo

El paso 12.7.3 fue validado manualmente en Safari de un iPhone físico con los tres roles y en computadora con el rol administrador. El paso 12.7.4 reúne las correcciones finales de presentación sobre `consolidacion-12.7.2`, con base en `0646919`.

## Correcciones

- Riesgo alto en rojo, medio en ámbar, bajo en verde y datos insuficientes en gris. Las etiquetas textuales se conservan en el resumen, las alertas y el seguimiento.
- Los recuentos respetan el singular y el plural. El detalle puede mostrar «1 ausencia de 1 clase» y «1 ausencia consecutiva».
- El ranking distingue el número de ausencias y su porcentaje. Marca «Datos insuficientes» cuando el total de asistencias esperadas de la fila queda por debajo del mínimo configurado. Mantiene los datos y el orden recibidos del servidor.
- Las barras de tendencia usan pista y relleno CSS de ASISTIX, con semántica accesible de medidor. Los periodos sin datos conservan su estado textual.

## Resultados del paso 12.7.4

| Comprobación | Resultado |
|---|---|
| Vitest focalizado | 2 pruebas aprobadas. Cubren etiquetas, concordancia, ranking y barras accesibles. |
| TypeScript y compilación Vite | Aprobados. |
| Chrome en la instancia HTTPS | Aprobado a 1440 px con administrador y a 390 y 320 px con estudiante. Se verificaron colores calculados, barras CSS, filtros, concordancia y ausencia de desbordamiento horizontal. |
| Contraste de etiquetas | Alto 7,35:1, medio 7,09:1, bajo 7,05:1 y datos insuficientes 7,58:1. |
| Protecciones | Coinciden los SHA-256 de las 16 bases protegidas y del ZIP de la exposición. Se verificaron las referencias de `master`, las ramas experimentales y las 17 etiquetas. |

Los cálculos, permisos, umbrales y recomendaciones del paso 12.7.2 conservan su implementación. La validación física en Safari de estas correcciones visuales queda pendiente de confirmación.

## Comprobación manual

Abre [ASISTIX en la red Wi-Fi local](https://192.168.100.16:5272/) y recarga la página. Usa una cuenta ficticia `admin@asistix.demo`, `docente@asistix.demo` o `estudiante@asistix.demo`. La contraseña común es `Asistix2026!`. Safari debe confiar en la CA local.

1. Abre **Alertas** y revisa la barra azul de cada periodo con datos.
2. Comprueba los colores del seguimiento y compara las alertas alta y media.
3. Como estudiante, busca **Laboratorio de Proyectos** en el ranking. Comprueba «1 ausencia de 1 asistencia esperada», «de ausencias» y «Datos insuficientes». Despliega su detalle para verificar «1 ausencia de 1 clase».
