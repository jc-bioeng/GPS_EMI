# Documentación de GPS_EMI

Revisión: **9 de octubre de 2026**. Base histórica: `03ee209`;
fase 1 versionada en `eda2606`, fase 2 en `24dae94`, fase 3 en `a171b37`.
Fase 4 implementada localmente, sin commit ni despliegue en este encargo.

## Lectura recomendada

Para RenderExcel, leer primero las [decisiones arquitectónicas aprobadas](decisiones-arquitectonicas-renderexcel.md). Separan acuerdos, funcionalidades aplazadas y detalles técnicos; prevalecen sobre propuestas históricas discrepantes.

1. [Guía del sistema](guia-del-sistema.md): arquitectura, datos, reglas y límites.
2. [Operación](operacion.md): configuración, comandos, persistencia y diagnóstico.
3. [README principal](../README.md): instalación y detalle histórico de incrementos.

| Área | Documento |
| --- | --- |
| Decisiones vigentes y fases | [Registro aprobado](decisiones-arquitectonicas-renderexcel.md) |
| Vigilancias, concurrencia y entrega | [Múltiples vigilancias](multiple-watches.md) |
| Identificadores ambiguos | [Selección explícita](vehicle-selection.md) |
| Captura pasiva y datos | [Collector](gps-collector.md) |
| Campañas temporales y SQLite | [Sesiones de recolección](collection-sessions.md) |
| Adquisición central implementada, fase 2 | [Especificación de fase 2](widetech-official-phase2-spec.md) |
| Collector nacional y campañas, fase 4 | [Diseño y pruebas](widetech-official-phase4.md) |
| Catálogo y consultas nacionales, fase 3 | [Implementación y pruebas](widetech-official-phase3.md) |
| Adaptador oficial aislado, fase 1 | [Implementación y pruebas](widetech-official-phase1.md) |

## Estado de implementación

**Base operacional versionada:** adquisición LoadDataLog con Parameters
dinámicos; CLI; consultas y vigilancias WhatsApp; menús numéricos; selección de
vehículos ambiguos; collector SQLite; sesiones temporales y observabilidad;
contenedor Docker con volumen de datos.

**Fase 1 confirmada en `eda2606`:** adaptador oficial
`widetech_official.py`, fixtures XML sintéticos, pruebas y documentación de fases.
**Fase 2 implementada:** AcquisitionRuntime compone una autoridad, Coordinator
planifica y SnapshotSource comparte datos con CLI, WhatsApp, vigilancias y collector.
`--official` activa RenderExcel explícitamente; sin esa opción se mantiene el
legado, sin fallback entre proveedores. En el cierre de fase 2, el alcance
operacional estaba limitado a Medellín. CLI y servidor son excluyentes usando el mismo directorio de estado.
La especificación detalla conservación por vehículo, calidad y limitaciones.
La auditoría y el prompt históricos quedan fuera del commit; no son dependencias.

**Fase 3 versionada:** catálogo persistente nacional, consultas nacionales y
reclasificación confirmada de vigilancias. TEC-01 quedó aprobado como criterio
operacional de tres adquisiciones aptas consecutivas; no certifica cobertura.
En su cierre, collector y admisión de vigilancias conservaban Medellín. Véase su especificación
para consistencia SQLite y evidencia offline.

**Fase 4 local:** collector nacional, deduplicación GPS persistente, asociaciones
entre campañas, históricos fuera de orden, admisión durable y registro de ventanas
de interrupción. Vigilancias siguen en Medellín. SQLite v3 y CSV aditivos.

**Pendiente de implementación por fases:** continuidad de vigilancias (fase 5)
y validación/despliegue gradual (fase 6).
Identidad, geocercas, zona inicial, cobertura y coordinación ya tienen decisiones
aprobadas en el registro de referencia. La restauración de vigilancias está
aplazada; los detalles técnicos restantes no reabren esos acuerdos. Un plan no
acredita que el comportamiento ya esté implementado ni desplegado.

## Evidencia de validación

| Alcance | Evidencia registrada |
| --- | --- |
| Base operacional | 705 tests aprobados, registrados en la documentación de sesiones del 2 de octubre |
| Base más adaptador oficial aislado, cierre de fase 1 | 892 tests aprobados (187 del adaptador), registrados el 8 de octubre en fase 1 |
| Fase 2, ejecuciones anteriores registradas | 919 tests; después del cierre de hallazgos, 41 específicos y 933 de regresión |
| Cierre documental y commit de fase 2 | Véase el apartado de reconciliación del documento de fase 2 para la ejecución de este encargo |
| Fase 4 local | Véase evidencia específica y regresión en fase 4; sin validación externa |
| Fase 3, ejecución local previa | Véase la evidencia de fase 3; bases temporales, sin validar WideTech |
| Pruebas manuales de fase 2 reportadas por el usuario, 9 de octubre | CLI por móvil/placa, por sede y arranque de vigilancia con STALE; no acreditan llegada, WhatsApp, cobertura nacional ni Docker/Ubuntu |

Las cifras anteriores corresponden a ejecuciones documentadas, no a una nueva
ejecución por editar estos textos. El documento de fase 1 explica el entorno
alternativo usado ante las limitaciones del ejecutable local. Las pruebas no
sustituyen aceptación con el proveedor ni verifican qué imagen está desplegada.

No incorporar credenciales, cookies, identificadores de sesión, bases de datos,
exportaciones, logs ni artefactos de prueba a ejemplos o commits.
