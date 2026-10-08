# Fase 2 — especificación de integración, sin implementación

Referencia vigente: encargo de cierre del usuario del 8 de octubre de 2026.
Prevalece sobre propuestas anteriores. [Contrato y cierre de fase 1](widetech-official-phase1.md).
Este documento no activa proveedores, modifica bases ni autoriza despliegue.

Aclaración posterior del usuario: salvo la envoltura funcional real de RenderExcel,
los temas de límites, mapping, zona horaria e integración ya se discutieron y
decidieron para incrementos posteriores. Los detalles marcados aquí como propuestas
son un diseño de referencia, no nuevas decisiones exigidas ni bloqueos: al ejecutar
cada incremento prevalecen los acuerdos del usuario, que se consolidarán por escrito
sin reabrirlos. No se inventan valores de acuerdos que no están transcritos aquí.

## Objetivo y decisiones aprobadas

Un único coordinador adquiere RenderExcel para todos los consumidores, sin
solapamientos. Intervalo inicial **30 segundos configurable**, backoff progresivo,
recuperación gradual y respeto de Retry-After. Los 30 segundos son configuración
aprobada, no un límite certificado por WideTech; la descripción del 109 no los
reemplaza por 20. El adaptador mantiene una petición por acquire y cero reintentos.

Consultas y campañas: ambulancias nacionales por prefijo fltName `Ambulancias`,
con la normalización de fase 1. Vigilancias: exclusivamente Medellín. Un cambio
confirmado a otra flota termina la vigilancia; no hay restauración automática.
La implementación de catálogo, campañas y continuidad/reclasificación de
vigilancias corresponde a sus fases respectivas. No se infiere clasificación
por ubicación, etiqueta o VEH_DESC. No se utiliza GetMobileList como dependencia
ni como health check: el 108 observado allí no determina acceso a RenderExcel.

## Inventario comprobado en el código actual

| Camino | Punto actual | Cambio previsto |
|---|---|---|
| Vigilancias y demanda del collector | `src/gps_emi/monitoring/fleet_polling.py`, `FleetPolling.cycle`: `source_factory().get_vehicles()`; su propio hilo espera y hace backoff | Consumir versiones publicadas; retirar su autoridad HTTP y su temporizador de adquisición |
| Consulta por etiqueta | `src/gps_emi/queries.py`, `get_vehicle_location`: `client.get_vehicles()` | Resolver sobre un snapshot explícito, sin HTTP |
| Consulta por VEH_ID | Mismo archivo, `get_vehicle_location_by_id` | Validar la identidad seleccionada en el snapshot, sin fallback por etiqueta |
| Inventario por sede | Mismo archivo, `list_vehicles_at_site` | Filtrar el snapshot; conservar nombres exactos de geocercas |
| WhatsApp ubicación y sede | `src/gps_emi/whatsapp/service.py`, `MessageService.handle`, acciones `location` y `site` | Solicitudes pendientes asíncronas al coordinador |
| Selección de vehículo | `MessageService.handle`, `vehicle_select`: consulta por ID; `WatchManager.start_selected` encola alta en FleetPolling | Mantener owner, generación, TTL y consumo único; revalidar por ID al completar |
| Contextos de selección | `src/gps_emi/selection.py`, `PendingSelections` | Ya almacena candidatos en memoria; no convertir paginación en HTTP |
| CLI consultas | `src/gps_emi/cli.py`, `_execute` crea `WideTechClient` y llama queries | Cliente del coordinador; puede esperar con timeout en consola |
| CLI vigilancia | `src/gps_emi/monitoring/runner.py`, `WatchRunner._run` llama `get_vehicles()` y espera con su backoff | Suscripción al coordinador; retirar autoridad de consulta del runner |
| Arranque WhatsApp | `src/gps_emi/whatsapp/server.py`, `source_factory` devuelve nuevas instancias WideTechClient | Inyectar cliente único del coordinador, sin crear adaptadores por mensaje |
| Entradas de compatibilidad | `gpspace_loaddatalog.py` delega a CLI; `providers/widetech.py::load_data_log` instancia cliente | No permitir un camino operacional que evada el coordinador al activar el nuevo modo |

El collector actual es pasivo: FleetPolling llama `collector.submit(vehicles,
acquired_at)` tras adquirir; su sesión activa mantiene demanda de polling.
`src/gps_emi/analysis/collector.py` y las sesiones existentes no son un segundo
proveedor HTTP. Conservar esa separación en la integración posterior.

## Autoridad única, procesos y concurrencia

Diseño propuesto: servicio propietario del coordinador, con clientes locales
para WhatsApp, CLI y consumidores. Solo el propietario posee el adaptador y
credenciales. IPC/API interna autenticada y no expuesta públicamente; su elección
concreta seguirá los acuerdos del incremento correspondiente. Una exclusión de proceso a nivel del
host y dominio de cuenta/método impide iniciar un segundo propietario. Los clientes
no tienen fallback HTTP cuando el propietario está ausente: informan indisponibilidad.

Un mutex de Python o una instancia por worker no resuelve competencia entre
procesos. Todos los entrypoints deben pasar por el mismo servicio. Si se despliega
en varios hosts, bloquear esa topología hasta disponer de liderazgo con fencing
y un límite compartido; no confiar en locks locales ni en «una réplica» declarada.
Otras herramientas externas que usen la misma cuenta quedan fuera del control
del proceso y deben identificarse antes de activar.

El propietario mantiene una sola adquisición en vuelo y agrupa solicitudes
concurrentes (single flight). Cien solicitudes no generan cien consultas. Leer
la caché, abrir otra CLI, crear otra vigilancia o cambiar de worker no reinicia
el plazo. El lock se mantiene durante el intento y la publicación atómica;
callbacks y envíos no deben ejecutarse bajo ese lock ni sobre el hilo HTTP.

## Relojes, intervalos y política propuesta

Separar reloj monotónico para plazos y reloj aware UTC para auditoría. Intervalo
base B=30 s configurable y validado. Medir entre inicios de intentos; nunca iniciar
otro mientras siga uno en vuelo. Propuesta precisa para probar:

`next_start >= max(last_start + B, finished_at_monotonic + failure_delay, retry_after_deadline)`.

En éxito estable, failure_delay=0. Ante fallos recuperables, primer delay B,
duplicar sucesivamente hasta un máximo configurable (300 s es solo una propuesta
de referencia, subordinada a lo ya acordado); nunca acortar un Retry-After por ese máximo. No reutilizar
sin cambios WatchConfig.initial_backoff=5/max_backoff=30: hoy pertenecen a otro
loop y podrían acelerar indebidamente las peticiones.

Recuperación propuesta: después de cada adquisición válida dividir el delay
vigente por dos hasta B; tras llegar a B, pasar a estable y delay=0. Un nuevo
fallo vuelve a aumentarlo. No recuperar todo el tráfico después de un único éxito.
No hay ráfagas para recuperar ciclos perdidos. Sin demanda activa se puede
suspender el loop, pero el siguiente solicitante conserva todos los plazos.

Retry-After segundos se ancla al momento de recepción; fecha absoluta se compara
con UTC al recibirla y se convierte a deadline monotónico. Fechas pasadas no
eliminan el intervalo base. Cambios del reloj del sistema no anticipan un plazo
ya establecido. Un Retry-After en una adquisición exitosa también se respeta.

Reinicio: preservar de forma separada de las bases operativas el próximo permiso
de consulta/Retry-After y la propiedad de la autoridad; no persistir secretos.
Si no hay estado temporal fiable, iniciar con espera conservadora y estado no
listo, sin asumir permiso inmediato. El mecanismo durable y el tratamiento de
relojes tras reinicio seguirán las decisiones del incremento correspondiente. En ningún
caso abrir otro proceso elude una restricción aún vigente.

## Snapshot compartido y arranque

Contrato propuesto e inmutable: `epoch`, `version`, `source`, `request_started_at`,
`acquired_at` real al terminar recepción, `published_at`, `records`, `diagnostics`,
`duplicate_ids`, `incomplete_rows`, `coverage=unknown`, `quality`, `timezone_name`.
Versiones monotónicas dentro del epoch; una lectura cacheada conserva versión y
acquired_at. Publicar después de parsing y validación, nunca al iniciar la llamada.
Las fechas GPS/servidor siguen separadas; ninguna se sustituye por acquired_at.

Estado separado del snapshot: `INITIALIZING`, `READY`, `DEGRADED`, `UNAVAILABLE`,
`BLOCKED_METHOD`, `STOPPING`, `STOPPED`; último intento/éxito, error seguro y próximo
plazo. UNAVAILABLE describe adquisición de esta integración; no afirma caída
general de WideTech. La última información válida sigue disponible con antigüedad
y error actual explícitos, sin cambiar acquired_at ni emitir observaciones nuevas.

Arranque requiere el primer snapshot válido de este proceso/epoch; hasta entonces
responder inicialización o pendiente. Un catálogo o ubicación persistidos son
históricos, no evidencia actual. Un DataTable válido vacío puede ser una adquisición
estructural válida con cobertura desconocida, nunca prueba de desaparición global.
Un status 0/100 sin DataTable y un estado sin datos no cumplen el requisito.

Propuesta de calidad: guardar por separado el último lote recibido y la última
vista aceptada; lotes con duplicados/incompletos se publican como degradados con
evidencia íntegra, sin sustituir automáticamente la vista operativa válida. Nunca
mezclar filas antiguas y nuevas bajo una única fecha actual. La política exacta
de aceptación parcial seguirá lo acordado para conectar consumidores; no inferir
un umbral de cobertura por el número observado de vehículos.

## Espera asíncrona y separación de eventos

`request_snapshot(min_version, max_age, deadline, request_context)` devuelve una
vista disponible o ticket pendiente; no ejecuta HTTP en el llamador. Valores de
max_age y deadline deben ser configurables y definidos en las pruebas de integración.
El coordinador entrega completados mediante una cola acotada. No hacer
`future.result`, sleeps ni espera del intervalo dentro de `Inbox._process`:
`whatsapp/worker.py::Inbox` tiene un único consumidor.

MessageService registra intención y vuelve al worker; finalización reentra por
eventos serializados para no mutar sus contextos desde el hilo HTTP. Comprobar
owner, generación, TTL y cancelación antes de contestar o crear una vigilancia;
un comando nuevo invalida una respuesta tardía. Saturación/timeouts finalizan el
ticket explícitamente; no bloquean menús, cancelaciones ni el webhook. El envío
a Meta no gobierna la frecuencia GPS. CLI sí puede esperar fuera del worker,
con cancelación y plazo acotados, usando la misma autoridad.

Tres conceptos distintos:

1. Adquisición nueva: intento validado y nueva versión, aunque GPS no haya cambiado.
2. Presencia en catálogo: VEH_ID y flota recibidos; incluir también no ambulancias
   y desconocidos para futura reclasificación. Ausencia no equivale a desaparición.
3. Observación GPS nueva: decisión por vehículo sobre Id/FechaGPS y orden temporal;
   leer caché o repetir registro no genera otra transición de llegada.

`ObservationValidator` actual evalúa orden/antigüedad de Vehicle naive; una futura
conversión explícita debe evitar comparar fechas naive y aware. No activar el
adaptador hasta validar etiquetas/fechas y la compatibilidad de consumidores.

## Errores y alcance de sus efectos

| Evidencia | Política propuesta |
|---|---|
| Red, timeout, HTTP 500/otros 5xx | Indisponibilidad de adquisición; backoff y conservación del último válido; no inferir causa funcional del texto |
| HTTP 429 / funcional 109 | Restricción; mismo planificador y Retry-After, sin deducir 20 s de descripción |
| Funcional 108 | Método denegado; detener reintentos automáticos de ese método hasta intervención/configuración; no declarar credenciales globalmente inválidas |
| Autenticación estructurada / HTTP 401 o 403 | Suspender intentos de esta integración y pedir revisión; conservar distinción entre HTTP y código funcional, sin probar otros métodos |
| Servicio suspendido, otros códigos funcionales o desconocidos | Retener categoría/código; política explícita por clase, por defecto bloqueo de adquisición pendiente de revisión, sin retry agresivo |
| Sin datos, éxito sin DataTable, XML inválido | No publicar snapshot vacío; conservar último válido, diagnosticar y usar backoff acotado para errores de payload; escalamiento tras repetición configurable |

Errores nunca causan desaparición, reclasificación ni llegada. El futuro contrato
de vigilancia procesa cambio de flota solo cuando esté confirmado por catálogo;
un fltName ausente no confirma otra flota. La fase 2 no implementa esa política
ni restaura vigilancias automáticamente. No copiar el `fail_active` actual de
FleetPolling como respuesta genérica a todo fallo del nuevo adaptador.

## Interfaces para fases posteriores

Proponer `on_acquisition(snapshot)` al catálogo (todas las filas y calidad),
`on_snapshot(snapshot)` a consumidores y `on_acquisition_state(state)` a salud.
Interfaces tipadas y colas acotadas con deduplicación por epoch/version; no crear
catálogo persistente ni migraciones ahora. El collector futuro recibe una sola
notificación por adquisición aceptada con acquired_at real; relecturas de caché
no disparan submit. Su escritura sigue fuera del hilo de adquisición. Fallos de
collector no originan otra petición GPS. Contrapresión y descartes deben ser
explícitos; retención y campañas se especifican en sus fases.

## Pruebas y secuencia de integración futura

Reloj monotónico/UTC, transporte, scheduler y notificaciones falsos; sin sleeps
ni red reales. Cubrir 100 solicitudes simultáneas, HTTP lento, exclusión entre
procesos, pérdida de propietario, IPC ausente sin fallback, lectura cacheada sin
petición, versiones y timestamps estables, primer snapshot, histórico persistido,
lote vacío válido frente a fallo/sin datos, calidad parcial y duplicados.
Verificar intervalos entre inicios, backoff creciente, recuperación escalonada,
Retry-After fecha/segundos/pasado/en éxito, reinicio sin reset de restricciones,
sin demanda y reanudación sin ráfagas. Un fallo conserva datos y no llama catálogo
con vacío. 108 de GetMobileList no cambia disponibilidad de RenderExcel.

Probar Inbox responsivo durante GPS pendiente, cancelación/TTL/owner/generación,
saturación y una sola respuesta final; igualdad de observación GPS tras distintas
adquisiciones y ausencia de transiciones desde caché. Cierre: dejar de admitir,
cancelar tickets, impedir nuevas llamadas, esperar intento en vuelo con plazo,
descartar publicación tardía, drenar consumidores según plazo y liberar propiedad
sin permitir solapamiento con otro proceso. El timeout de lectura actual no es
un deadline global: resolver cancelación/limite total antes del relevo del propietario.

Secuencia propuesta (cada paso requiere un encargo posterior):

1. Trasladar los acuerdos existentes al incremento; implementar núcleo de scheduling y
   snapshots con fuentes falsas, manteniendo proveedor oficial inactivo.
2. Implementar propietario/IPC y exclusión real entre procesos, pruebas de fallo
   y arranque; habilitar clientes sin acceso directo al proveedor.
3. Convertir queries en operaciones sobre snapshots y MessageService en consumidor
   asíncrono; conectar selección, CLI y FleetPolling al mismo coordinador.
4. Probar puente de modelo y consumidores actuales; retirar todos los timers de
   adquisición redundantes y verificar regresiones WhatsApp/CLI/vigilancias/collector.
5. En fases respectivas, completar catálogo, campañas y política Medellín antes
   de exponer la operación nacional. Nunca ampliar vigilancias por usar una fuente nacional.
6. Activar únicamente con autorización posterior, pruebas completas, mapping y
   zona aceptados, política de calidad resuelta, autoridad única demostrada,
   configuración de 30 s/backoff revisada y plan de reversión controlado. No hacer
   doble polling para comparar proveedores; tampoco fallback automático operacional.

## Envoltura pendiente y acuerdos de incrementos posteriores

Permanece sin confirmar si RenderExcel emite la envoltura funcional observada
en GetMobileList. Esto no bloquea el desarrollo con fakes ni autoriza afirmar
que se haya observado allí el código 109.

Acuerdos a trasladar a sus incrementos, no decisiones a reabrir: mecanismo IPC y exclusión/reinicio, persistencia
mínima del permiso temporal fuera de bases operativas, aceptación de calidad parcial,
max_age/plazo y capacidad de tickets, tope de backoff y parámetros de recuperación,
cancelación de transporte al relevar autoridad, límites y conversión temporal/etiquetas.
Su consolidación documental debe reflejar lo ya decidido por el usuario, sin
convertir las propuestas técnicas de este documento en requisitos adicionales.
Mantener aprobados 30 s iniciales, alcance nacional de consultas/campañas,
vigilancias Medellín, terminación por cambio confirmado y no restauración automática.
