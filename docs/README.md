# Documentación de GPS EMI

Revisión documental: **20 de octubre de 2026**, código local `a8f3f24`.
Este índice es la referencia del estado general; los documentos de fases conservan
el alcance y las pruebas de su fecha. Ninguno identifica por sí solo el despliegue.

## Elegir por necesidad

| Necesidad del lector | Referencia y función |
|---|---|
| Conocer problema, capacidades e instalación | [README principal](../README.md): presentación del sistema desplegable |
| Saber qué está acordado o aplazado | [Decisiones arquitectónicas](decisiones-arquitectonicas-renderexcel.md): única autoridad documental de acuerdos |
| Entender componentes, flujo y responsabilidades | [Guía del sistema](guia-del-sistema.md) |
| Configurar y ejecutar | [Operación](operacion.md): variables, CLI, Docker y campañas |
| Usar WhatsApp | [Comandos](comandos-whatsapp.md): alias, confirmación y gestión |
| Mantener el código | [Mantenimiento](manual-mantenimiento.md): mapa de módulos, evolución y verificación de cambios |
| Comprender tablas y compatibilidad | [SQLite](base-de-datos.md): diccionario, transacciones y esquema |
| Resolver incidentes y recuperar datos | [Recuperación](procedimientos-recuperacion.md): diagnóstico, backup, restauración y reversión |
| Profundizar en subsistemas | [Vigilancias](multiple-watches.md), [selección](vehicle-selection.md), [collector](gps-collector.md), [campañas](collection-sessions.md) |
| Preparar aceptación en la instalación reportada | [Guía Oracle](guia-comprobaciones-oracle-fase6.md): procedimiento interno, ejecución pendiente por caso |
| Evaluar evidencia y preparar portafolio | [Auditoría documental](auditoria-documental.md): inventario, sensibilidad, historial y desajustes |
| Gestionar pendientes por commit y responsable | [Plan y asignaciones por rol](auditoria-documental.md#plan-de-commits-y-asignación-por-rol): dependencias, cierre y revisión obligatoria de secretos |

## Estado general y evidencia

| Nivel | Estado / referencia |
|---|---|
| Acuerdos | ARQ/CAT/COB/DAT/VIG/COL/PER/DEP y APL en el registro aprobado; el ajuste de alta interior del 13 de octubre sigue vigente |
| Implementación local | Fases 1–5 versionadas; confirmación previa y alias en `a8f3f24`. Oficial explícito, consultas/collector nacionales y vigilancias Medellín |
| Pruebas offline históricas | Base: 705; fase 1: 892; fase 2: 933; fase 3: 960; fase 4: 977; fase 5: 1.022; ajuste posterior: 1.105. Cada cierre identifica su ejecución; no son cifras acumulables |
| Análisis puntual | [Campaña de fase 6](widetech-official-phase6-campaign-analysis.md): método, límites y 99 pruebas focalizadas históricas; evidencia privada fuera del conjunto publicable |
| Validación operativa reportada | CLI el 9 de octubre; arranque oficial y consulta WhatsApp en Oracle; campaña y conversación posteriores con evidencia parcial. No prueban todos los escenarios ni la imagen actual |
| Pendiente | Retención técnica PER-03/TEC-08 y aceptación completa de fase 6, incluyendo versión efectiva, respaldo/restauración y reversión |
| Aplazado | Selección de flotas, restauración de vigilancias y mensajes proactivos especificados en APL-01–05; no incorporarlos incidentalmente |

Verificación realizada para este incremento: [auditoría](auditoria-documental.md).
Un acuerdo no equivale a código; un test offline no acredita proveedor real;
un reporte del operador no identifica una imagen si no se registra esa evidencia.

## Evolución histórica

| Documento | Etapa y relación |
|---|---|
| [Antecedentes I1–I4](antecedentes-i1-i4.md) | README anterior con reglas sustituidas; ejemplos saneados, original privado conservado |
| [Fase 1](widetech-official-phase1.md) | Adaptador aislado; `eda2606` |
| [Fase 2](widetech-official-phase2-spec.md) | Adquisición central; `24dae94` |
| [Fase 3](widetech-official-phase3.md) | Catálogo y consultas nacionales; `a171b37` |
| [Fase 4](widetech-official-phase4.md) | Collector nacional y campañas; `18d2661` |
| [Fase 5](widetech-official-phase5.md) | Continuidad y recuperación; `0f97e1f` |
| [Análisis de fase 6](widetech-official-phase6-campaign-analysis.md) | Evidencia parcial; no cierre ni despliegue certificado |
| [Auditoría API inicial](auditoria-api-oficial.md) | Propuestas superadas por las decisiones aprobadas |
| [Prompt de integración](prompt-integracion-api-oficial.md) | Antecedente sustituido; no ejecutar como encargo vigente |

## Referencia portátil y evidencia privada

La [referencia PDF](../output/pdf/GPS_EMI-referencia-comandos.pdf) se genera desde
[comandos WhatsApp](comandos-whatsapp.md) y [operación](operacion.md) mediante
`generar-referencia-comandos.py`. No se edita el PDF a mano ni se mantiene otro
catálogo de comandos. La auditoría registra fuentes y verificación visual.

Originales, renders anteriores e informe empírico de campaña permanecen en rutas
ignoradas. No se enlazan datos privados como requisito de lectura. El inventario
y los límites están en la [auditoría documental](auditoria-documental.md).
