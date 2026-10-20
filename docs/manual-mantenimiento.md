# Mantenimiento del código de GPS EMI

Referencia para mantenedores, reconciliada con `a8f3f24` el 19 de octubre de 2026.
Este documento localiza componentes y orienta la verificación de cambios. La
[guía del sistema](guia-del-sistema.md) explica el flujo; [operación](operacion.md)
define configuración y comandos; [SQLite](base-de-datos.md) describe persistencia;
[recuperación](procedimientos-recuperacion.md) contiene los procedimientos ante incidentes.
Los acuerdos pertenecen exclusivamente al [registro aprobado](decisiones-arquitectonicas-renderexcel.md).

## Preparar un cambio

1. Registrar versión y estado Git; conservar cambios ajenos. Relacionar el cambio
   con la decisión aprobada o el límite documentado que corresponda.
2. Localizar componente y pruebas en el mapa inferior. Mantener fixtures sintéticos,
   reloj inyectable y bases temporales; no usar una base operativa como prueba.
3. Comprobar el caso afectado y la regresión apropiada al código modificado. Para
   documentación, revisar enlaces, ejemplos, procedencia y coherencia de estado.
4. Actualizar la referencia dueña de ese contenido y enlazarla desde las demás.
   Registrar ejecución, entorno y límites; no reutilizar cifras históricas como nuevas.

Las opciones y límites de colas se consultan en las especificaciones de
[adquisición](widetech-official-phase2-spec.md), [collector](widetech-official-phase4.md)
y [vigilancias](multiple-watches.md). No añadir reintentos desde consumidores ni
alterar reglas de negocio como parte de una corrección documental.

## Evolución y decisiones implementadas

| Etapa | Resultado y cambio respecto de la anterior | Referencia |
|---|---|---|
| Base I1 | CLI, resolución de vehículo, geocercas y transición exterior→interior; aviso por consola | [README histórico](antecedentes-i1-i4.md) |
| I2 | Continuidad por identidad, validación temporal, reintentos y diagnóstico | [Antecedentes](antecedentes-i1-i4.md) |
| I3 | Menú, ubicación y consulta por sede; EMI como unión de Poblado y Taller | [Antecedentes](antecedentes-i1-i4.md) |
| I4 y ampliaciones, `03ee209` | Webhook WhatsApp, múltiples vigilancias, selección de ambiguos, SQLite, campañas y Docker | [Vigilancias](multiple-watches.md), [campañas](collection-sessions.md) |
| Fase 1, `eda2606` | Adaptador RenderExcel aislado, parser y diagnósticos; inicialmente sin activar consumidores | [Fase 1](widetech-official-phase1.md) |
| Fase 2, `24dae94` | Una autoridad HTTP, un planificador, snapshot compartido y exclusión local; conservación por vehículo | [Fase 2](widetech-official-phase2-spec.md) |
| Fase 3, `a171b37` | Catálogo nacional persistente, consultas nacionales, ausencias confirmadas y reclasificación | [Fase 3](widetech-official-phase3.md) |
| Fase 4, `18d2661` | Collector nacional, deduplicación persistente, asociaciones entre campañas y migración v3 | [Fase 4](widetech-official-phase4.md) |
| Fase 5, `0f97e1f` | Interrupción individual, recuperación por tres GPS frescos, veto a llegadas antiguas y vencimiento con pausas | [Fase 5](widetech-official-phase5.md) |
| Ajuste posterior, `a8f3f24` | Confirmación previa de alta interior, salida fresca obligatoria y alias de comandos | [Comandos](comandos-whatsapp.md) |
| Fase 6, pendiente | Retención técnica y validación gradual; no confundir guía o pruebas reportadas con cierre de fase | [Decisiones](decisiones-arquitectonicas-renderexcel.md) |

El operador reportó arranque oficial en Oracle y consulta WhatsApp funcional con
base nueva. Es evidencia puntual del operador registrada en la guía de Oracle;
no prueba todas las transiciones, recuperación, permisos o límites de WideTech.

## Mapa de código para mantenimiento

Rutas relativas a `src/gps_emi/`:

| Módulo | Responsabilidad / dónde corregir |
|---|---|
| `cli.py`, `whatsapp/server.py` | Composición, argumentos y ciclo de vida |
| `acquisition_runtime.py` | Selección de proveedor, estado y exclusión entre procesos |
| `acquisition.py` | Planificador, snapshots, solicitudes, proyecciones y pausas |
| `providers/widetech_official.py` | HTTP oficial, XML, mapping y errores de filas/lote |
| `providers/widetech.py`, `load_data_log.py` | Transporte y Parameters del legado |
| `catalog.py`, `database.py` | Catálogo, ausencia, transacciones y conexión SQLite |
| `queries.py`, `resolution.py`, `selection.py` | Consultas, identidad y selección pendiente |
| `models.py`, `sites.py`, `formatting.py` | Modelos, nombres de sedes y presentación común |
| `monitoring/observation.py`, `arrival.py` | Validación temporal y transición de geocerca |
| `monitoring/continuity.py` | Interrupción, recuperación y actividad |
| `monitoring/watches.py`, `runner.py`, `fleet_polling.py` | Gestión concurrente, CLI y distribución |
| `analysis/collector.py`, `analysis/sessions.py` | Histórico, deduplicación y campañas |
| `collector.py`, `analysis/export_observations.py` | Administración y CSV |
| `whatsapp/webhook.py`, `worker.py`, `service.py` | Validación de entrada, cola y casos de uso |
| `whatsapp/routing.py`, `menu.py`, `vehicle_selection.py` | Comandos y navegación |
| `whatsapp/client.py`, `delivery.py`, `notifier.py` | Transporte, ventana y notificación |
| `whatsapp/shutdown.py`, `observability.py` | Cierre y resumen de actividad |

Antes de cambiar reglas, localizar su decisión y pruebas en `tests/`. Mantener
reloj inyectable y fixtures sintéticos: no probar con flota o credenciales reales.
Cambios de parser necesitan casos globales y de fila; cambios de snapshot, caché
y entrega única; cambios de catálogo, reinicio y replay; collector, concurrencia
stop/admisión y migración; vigilancias, límites temporales y carreras; WhatsApp,
firma, autorización, selección y ventana. Ejecutar pruebas específicas y regresión
cuando se modifica código. Una edición documental no acredita nueva validación externa.

### Verificación de este consolidado — 12 de octubre de 2026

Se contrastaron las once tablas y sus 77 columnas con una base sintética creada
por SessionStore y CatalogStore: esquema v3, quick_check y claves foráneas correctos.
Se verificaron enlaces locales, cierre de bloques Markdown y `git diff --check`.
Los siete diagramas se revisaron como fuente Mermaid; no se verificó su renderizado
con un motor Mermaid. La revisión de patrones sensibles de los documentos nuevos
y líneas añadidas no produjo alertas; no había detector dedicado en PATH.
No se ejecutó regresión de código por este cambio exclusivamente documental ni
se accedió a la base operativa, al `.env` o a servicios externos.

### Reorganización del 19 de octubre de 2026

El manual previo repetía presentación, arquitectura, reglas y operación. Se conserva
su evolución, mapa de código y evidencia de verificación; el detalle de uso se
consulta en las referencias enlazadas. El estado vigente, las discrepancias y el
alcance de esta revisión figuran en la [auditoría documental](auditoria-documental.md).
