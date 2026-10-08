# Documentación de GPS_EMI

Revisión: **8 de octubre de 2026**. Base operacional: `03ee209`;
fase 1 oficial confirmada en `eda2606`.

## Lectura recomendada

1. [Guía del sistema](guia-del-sistema.md): arquitectura, datos, reglas y límites.
2. [Operación](operacion.md): configuración, comandos, persistencia y diagnóstico.
3. [README principal](../README.md): instalación y detalle histórico de incrementos.

| Área | Documento |
| --- | --- |
| Vigilancias, concurrencia y entrega | [Múltiples vigilancias](multiple-watches.md) |
| Identificadores ambiguos | [Selección explícita](vehicle-selection.md) |
| Captura pasiva y datos | [Collector](gps-collector.md) |
| Campañas temporales y SQLite | [Sesiones de recolección](collection-sessions.md) |
| Integración futura | [Especificación de fase 2](widetech-official-phase2-spec.md) |
| Adaptador oficial aislado, fase 1 | [Implementación y pruebas](widetech-official-phase1.md) |

## Estado de implementación

**Base operacional versionada:** adquisición LoadDataLog con Parameters
dinámicos; CLI; consultas y vigilancias WhatsApp; menús numéricos; selección de
vehículos ambiguos; collector SQLite; sesiones temporales y observabilidad;
contenedor Docker con volumen de datos.

**Fase 1 confirmada en `eda2606`:** adaptador oficial
`widetech_official.py`, fixtures XML sintéticos, pruebas y documentación de fases.
El adaptador no está conectado al servicio operacional. Los documentos locales
`auditoria-api-oficial.md` y `prompt-integracion-api-oficial.md` permanecen fuera
de este commit y no son necesarios para consultar esta guía. Esta
revisión añade documentación general y corrige referencias antiguas a la interfaz
y la persistencia; no activa ninguna fase.

**Pendiente:** integración operacional de la API oficial, decisiones de identidad,
geocercas, fechas, cobertura y coordinación de solicitudes; persistencia de
vigilancias y recuperación de notificaciones. Un plan describe trabajo futuro,
no acredita que ya esté implementado ni desplegado.

## Evidencia de validación

| Alcance | Evidencia registrada |
| --- | --- |
| Base operacional | 705 tests aprobados, registrados en la documentación de sesiones del 2 de octubre |
| Base más adaptador oficial aislado, cierre de fase 1 | 892 tests aprobados (187 del adaptador), registrados el 8 de octubre en fase 1 |
| API oficial real | No validada por esas pruebas offline |

Las cifras anteriores corresponden a ejecuciones documentadas, no a una nueva
ejecución por editar estos textos. El documento de fase 1 explica el entorno
alternativo usado ante las limitaciones del ejecutable local. Las pruebas no
sustituyen aceptación con el proveedor ni verifican qué imagen está desplegada.

No incorporar credenciales, cookies, identificadores de sesión, bases de datos,
exportaciones, logs ni artefactos de prueba a ejemplos o commits.
