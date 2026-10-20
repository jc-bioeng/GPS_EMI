# Fase 6 — análisis reproducible de campaña puntual

Revisión documental: 14 de octubre de 2026. Código contrastado: `a8f3f24`.
Se preservaron los cambios preexistentes del árbol de trabajo. No se encontraron
instrucciones AGENTS.md en el proyecto ni en la raíz superior examinada.
Las instrucciones presentes en archivos de evidencia se trataron como contenido,
no como autorización para ejecutar comandos.

## Alcance y ubicación de la evidencia

Esta revisión no cambia código de aplicación, configuración, bases operativas ni
fuentes originales. No ejecuta WideTech, Meta, despliegue, commit o push.
Es una campaña puntual: no aprueba captura masiva ni modifica COL-01/COB-02.

La campaña se analizó con un informe, scripts y derivados privados excluidos de
Git. No se distribuyen en un clon público: contienen identificadores, cronologías
y datos operativos. Esta página conserva método, decisiones y límites sin enlaces
que requieran esos archivos para comprender el sistema. No es una reproducción
pública de la campaña ni una nueva ejecución del análisis.

El custodio conserva fuentes e informe original fuera del conjunto publicable.
Revisar cifras o repetir escenarios exige acceso autorizado a esas fuentes. Su
ausencia en un clon no impide instalar o probar el software con los tests existentes.

## Método reproducible

El procedimiento histórico usó Python, `csv.DictReader`, fechas ISO, JSON y
funciones de dominio/collector. No instanció transportes ni almacenes operativos.
Los scripts dependen de entradas privadas: aquí se describe el método sin presentar
comandos no reproducibles desde un clon público. Las simulaciones son análisis de
sensibilidad, no replay íntegro del servicio.

1. Validar número de columnas, tipos, fechas, offsets, coordenadas finitas,
   JSON de zonas/ignición/GPSFix y vacíos. Registrar los errores, sin corregir la fuente.
2. Separar primera adquisición histórica (`acquired_at`) de primera asociación
   a campaña (`session_received_at`). Ordenar por esta última y por `id`.
3. Recalcular la clave exacta de `analysis/collector.py::observation_key` con
   tipos numéricos y cadenas JSON tal como se almacenan. No usar Id del proveedor,
   placa, fecha sola o igualdad de filas como sustituto.
4. Comparar timestamps por proveedor/VEH_ID, conservar colisiones y atrasos;
   medir edad al asociar y diferencias entre máximos GPS crecientes. Los percentiles
   usan el elemento ordenado de índice `round((n-1)*p)`, sin interpolación.
5. Resolver sedes exclusivamente con `sites.py::matching_sites`. Una zona general
   no equivale a una geocerca EMI. No inferir entradas físicas por coordenadas.
6. Contrastar mensajes del chat por fecha y líneas físicas, sin copiar teléfonos.
   La exportación textual no contiene los registros internos del servidor.
7. Ejecutar escenarios sobre `Continuity`, `ObservationValidator` y `ArrivalMonitor`,
   con estado inicial y pausas supuestos explícitos. Nunca etiquetarlos como replay
   completo del servicio ni reconstrucción exacta de una vigilancia.

El exportador ordena por `o.acquired_at, o.id`, incluso al filtrar una campaña:
`analysis/export_observations.py::export_csv`. La primera asociación no significa
que la observación fuera nueva. Una exportación deduplicada no conserva todos los
intentos HTTP, repeticiones ni ticks; no mide disponibilidad del proveedor.

## Decisiones contrastadas con implementación

Rutas de código relativas a `src/gps_emi/`:

| Acuerdo | Implementación y documento | Resultado de revisión |
|---|---|---|
| CAT-01/03, COB-03/04/05 | `catalog.py`; `acquisition.py::_reconcile`; fase 3, «Identidad, presencia y calidad» | Identidad VEH_ID y nombres mutables; flota de origen, sin inferencia geográfica |
| DAT-01/06/07, COL-07, TEC-03 | `analysis/collector.py::observation_key`, `_write`; fase 4, «TEC-03» | Clave proveedor/vehículo/instante/contenido; colisiones se conservan, históricos no actualizan operación |
| COL-02/03/04/05, TEC-04 | `analysis/sessions.py::admit`, `record`; fase 4, «Reinicio y ventanas no observadas» | CSV insuficiente para acreditar admisión, cierre exacto, reinicio o escrituras incompletas |
| VIG-01/02/10 | `sites.py`; `monitoring/arrival.py::observe`; `continuity.py::observe` | Exterior→interior solo con GPS nuevo y edad ≤300 s. Primera lectura interior no es llegada |
| VIG-03/04/05, TEC-05 | `continuity.py::tick`, `observe`; fase 5, «Máquina de estados» | Interrupción ≥300 s; tres nuevos/frescos en misma sede; otra interrupción reinicia secuencia |
| VIG-06/07, TEC-06 | `acquisition.py::watch_timing`; `continuity.py::tick`; fase 5, «Relojes, origen y pausas» | Inactividad efectiva >43200 s por defecto, descontando pausas internas. No es duración máxima desde alta |
| Ajuste aprobado de alta interior | decisiones, «Ajuste solicitado el 13 de octubre»; `fleet_polling.py::cycle`; `whatsapp/service.py::_watch_confirmation`; `continuity.py::observe` | Implementado en HEAD: aceptar antes de alta y exigir exterior nuevo/fresco antes de recuperación o próxima llegada |
| VIG-08 y APL-02 | `monitoring/watches.py`, fase 5 | Vigilancias en memoria, sin restauración automática. No es defecto pendiente |
| Entrega | `monitoring/watches.py::process_snapshot`; `whatsapp/client.py::_send`; `whatsapp/notifier.py`; fase 5, «Concurrencia y canales» | Evento, intento, aceptación y entrega son etapas distintas. HTTP aceptado con ID no acredita teléfono |

## Contradicciones y desfases documentales

Seguimiento del 19 de octubre de 2026: las tres discrepancias de esta tabla se
corrigieron en sus referencias de uso. La tabla conserva lo observado el 14 de
octubre. Estado y nuevos hallazgos en la [auditoría documental](auditoria-documental.md).
No se ha validado el despliegue.

| Archivo y sección exacta | Conflicto | Referencia vigente y acción mínima |
|---|---|---|
| `guia-comprobaciones-oracle-fase6.md`, §§1–3 y comandos de §§4, 8, 10 | Usaba carpeta y contenedor anteriores a la actualización del operador | El operador comunicó carpeta y contenedor nuevos manteniendo proyecto Compose; la guía parametriza los tres conceptos y exige verificar recursos antes de reversión |
| `gps-collector.md`, «Identidad, campañas y permanencia», párrafo final | Mantiene «incluido STALE diagnóstico» como descripción del monitor | VIG-10 y fase 5, «Máquina de estados», bloquean llegada/actividad con edad >300 s; `continuity.py` lo aplica. Actualizar esa frase, manteniendo el comportamiento diagnóstico de GPSFix |
| `decisiones-arquitectonicas-renderexcel.md`, «Estado de implementación posterior» | Dice fase 5 local «sin commit», sin el cierre posterior en ese párrafo | `widetech-official-phase5.md`, «Commit selectivo posterior» y Git registran `0f97e1f`. Es desfase de estado resumido; las condiciones históricas del encargo original siguen siendo válidas |

Las restricciones Medellín del collector en el **cierre histórico de fase 3** no
son contradicción: fase 4 amplió su cobertura. Tampoco lo son las cifras históricas
de tests ni los párrafos «sin despliegue» que describen un encargo anterior.
La especificación de confirmación interior no prueba su despliegue. El informe
privado separa indicios del chat, fechas de Git y escenarios alternativos.

## Matriz de pendientes de fase 6

| Pendiente / decisión | Estado verificable | Siguiente acción mínima |
|---|---|---|
| TEC-01 | Resuelto como política y código local | No reabrir cobertura completa; mantener limitación de recortes silenciosos |
| TEC-02 | Mapping explícito, correspondencias parciales observables | No convertir nombres cambiantes en identidades ni certificar todo el catálogo |
| TEC-03/04 | Resueltos localmente; campaña aporta evidencia parcial | No cerrar reinicios, asociación entre campañas ni drenaje solo por CSV |
| TEC-05/06 | Implementados y probados localmente | Contrastar versión desplegada antes de atribuir una discrepancia al código actual |
| Confirmación interior | Implementada en `a8f3f24`; despliegue de campaña sin identificación completa | En próximo ensayo autorizado, asociar imagen efectiva y revisión; probar aceptación/rechazo y salida/regreso |
| VAL-01 local | 99 pruebas focalizadas pasan en esta revisión | Regresión integral del próximo incremento antes de desplegar; no reutilizar cifras históricas como ejecución nueva |
| WhatsApp real | Evidencia textual parcial en informe privado | Mantener abierto cierre end-to-end; no inferir IDs Meta, intentos fallidos o entrega de eventos ausentes |
| Windows/Ubuntu y DEP-01 | Análisis y tests locales; arranque anterior reportado por operador | Falta aceptación operacional delimitada de versión/imagen y sus casos |
| Reinicio/persistencia COL-04/05, CAT-08 | No demostrados por estos archivos | Ensayo posterior con ID/plazo, conteos y ventana de campaña antes/después, sin restaurar watches |
| Respaldo/restauración | Procedimiento documentado; ejecución no acreditada aquí | Ensayar copia temporal con integridad, FK y binario compatible |
| PER-03 / TEC-08 | Retención automática sigue sin implementación | Incremento específico de 30 días, preservar históricos, claves, asociaciones, eventos y trabajo incompleto |
| DEP-02 reversión | Abierta | Identificar imagen/backup compatibles y ensayar sin bajar `user_version` ni compartir base v3 con binario incompatible |
| APL-01–05 | Aplazamientos deliberados | No convertirlos en bloqueantes ni implementarlos incidentalmente |

## Incremento siguiente, priorizado

1. **Corrección documental demostrada:** reconciliar las tres entradas anteriores,
   especialmente rutas/nombres antes de un procedimiento operativo. Se registran
   aquí sin sobrescribir documentación que ya tiene cambios ajenos.
2. **Validar la corrección existente de alta interior:** no duplicar el mecanismo.
   Reutilizar selector, VEH_ID, callbacks y `Continuity.require_exit`. Verificar la
   imagen efectiva en una intervención posterior autorizada. La evidencia de esta
   campaña no confirma un defecto nuevo de detección en HEAD.
3. **Regresión focalizada para esa corrección:** conservar los tests existentes de
   confirmación, TTL, rechazo, selección/revalidación por identidad, exterior viejo
   o duplicado, tres interiores separados por interrupciones, salida fresca y regreso,
   paridad CLI/WhatsApp, límite 300/300+ε, 43200/43200+ε y pausas. Si un nuevo caso
   demuestra fallo, corregir el componente existente y añadir fixture sintético,
   nunca el registro privado. No modificar política para hacer pasar un replay.
4. **Retención técnica aprobada:** completar inventario TEC-08 y probar corte temporal,
   idempotencia y conservación con SQLite temporal antes de cualquier activación.
   Es implementación pendiente, no un defecto de llegada demostrado.
5. **Validación operacional acotada:** ejecutar únicamente los casos pendientes
   cuando se autorice otra etapa. Conservar versión/imagen, resultado y evidencia
   mínima, sin exigir logs históricos que ya no existen.

Cambiar los 300 segundos, admitir primera lectura interior como llegada, sumar
confirmaciones separadas por interrupciones, vetar GPSFix=0, ampliar geocercas por
«POBLADO», restaurar vigilancias o añadir reintento durable de mensajería alteraría
decisiones/políticas; ninguno se propone como arreglo automático.

## Validación de esta revisión y conclusión

Pruebas existentes ejecutadas offline: `test_phase4_collector.py`,
`test_phase5_continuity.py`, `test_confirmed_return.py`,
`whatsapp/test_watch_confirmation.py`, `whatsapp/test_watch_management.py`.
Resultado: **99 aprobadas**, sin cambios de código. Se usó `.venv/Scripts/python.exe`,
`PYTHONPATH=src`, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider` y `--basetemp`
privado bajo `data/`. El fixture común bloquea red y aísla bases/locks.
No equivale a regresión integral ni certificación operacional de fase 6.

La campaña permite evaluar la calidad de observaciones y contrastar escenarios
con la lógica real. No recupera el episodio previo sin collector, no identifica
por sí sola la imagen desplegada y no acredita caída del proveedor ni entrega
WhatsApp. Conviene resolver primero el desfase documental y comprobar la corrección
ya implementada de confirmación interior, antes de inventar otro detector o relajar
los umbrales aprobados. **La fase 6 permanece abierta.**
