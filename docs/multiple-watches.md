# Múltiples vigilancias en memoria

Antes: el adaptador WhatsApp reservaba un booleano `active` global y arrancaba un
`WatchRunner` para una ambulancia. Después:

```text
Webhook firmado → Inbox → MessageService → solicitudes de alta
                                      → listar/cancelar por owner_id
                                               │
                       FleetPolling (un hilo compartido)
                                               │
                 WideTechClient.get_vehicles() / LoadDataLog
                        una adquisición por ciclo
                                               │
                           snapshot de flota filtrada
                             │                 │
                      resolver altas       WatchManager
                                               │
                      Watch A       Watch B        Watch C
                      monitor A     monitor B      monitor C
                      validador A   validador B    validador C
                                               │
                          ArrivalEvent + Watch.notification_target
                                               │
                                adaptador WhatsApp → notifier
```

## Entidad e interfaces

`monitoring.watches.Watch` contiene UUID `watch_id`, `owner_id`, `vehicle_id`
(VEHID estable), móvil, placa, `created_at`, `notification_target`, monitor,
validador, última observación/evaluación, evento y resultado de notificación.
Propietario y destino son campos separados. No se modifica Vehicle ni ArrivalEvent.
Las identidades visibles pueden actualizarse sin cambiar el VEHID seguido.

Estados: ACTIVE recibe observaciones; COMPLETED detectó llegada; CANCELLED fue
detenida; FAILED identifica un error terminal de adquisición o un fallo local
inesperado de observación. FAILED es necesario para no presentar un error como
llegada o cancelación del usuario. No hay reactivación automática de terminales.

`WatchManager` ofrece `create_watch`, `get_watch`, `list_watches`,
`get_active_watches`, `cancel_watch`, `process_snapshot` y `close`.
Las consultas/cancelación reciben owner_id. Devuelve copias del estado: modificar
una vista no altera la vigilancia almacenada. Su diccionario privado en memoria
está encapsulado por estas operaciones; no se introduce un repositorio abstracto
sin una segunda implementación. Una futura persistencia puede implementarse aquí
sin cambiar ArrivalMonitor. La creación devuelve `(watch, created)`; el duplicado
ACTIVE por owner+VEHID devuelve la Watch existente y no cambia su destino.

El adaptador `whatsapp.service.WatchManager` mantiene la interfaz de arranque/cierre
del servidor y solo conecta callbacks/presentación con el gestor de dominio.
No construye observaciones ni implementa geocercas. La consola sigue usando el
WatchRunner existente; no participa en el polling compartido del servidor.

## Polling y resiliencia

`FleetPolling` mantiene altas pendientes hasta tener una adquisición exitosa.
Una petición recibida durante HTTP espera el siguiente snapshot. No hay consulta
de preflight ni un runner por Watch: el mismo resultado resuelve todas las altas
del ciclo y se indexa por VEHID para las activas. Sin altas ni Watches activas,
el hilo duerme en una Condition y no consulta GPSpace.

Timeouts/conexión/HTTP recuperables conservan Watches y altas pendientes, con el
backoff exponencial acotado de WatchConfig; recuperación restablece el intervalo.
Un error terminal, incluida sesión expirada, marca las activas FAILED y comunica
el fallo; después de reparar la sesión hay que solicitar las vigilancias otra vez.
No se implementan login, renovación ni bypass de Turnstile.

La ausencia o duplicidad de un VEHID omite solo esa observación y conserva la Watch.
No se interpreta como salida ni se penaliza a otras Watches con backoff por vehículo.
El validador existente rechaza timestamps duplicados, fuera de orden, ausentes o
incompatibles en zona horaria de forma independiente. STALE y GPSFix=0 siguen
siendo diagnósticos y no descartan observaciones nuevas. Zones y ArrivalMonitor
mantienen sus reglas exactas: primera lectura dentro no es llegada, y pasar de
sede a sede sin observar exterior tampoco lo es.

Las consultas puntuales de ubicación/inventario conservan su adquisición propia.
La garantía de un snapshot por ciclo corresponde al conjunto de vigilancias.

## Concurrencia y notificación

El gestor usa RLock para creación, unicidad, cancelación y observaciones. El poller
usa una Condition para solicitudes/cierre y un lock de ciclo para evitar ciclos
superpuestos. HTTP de adquisición y notificaciones se ejecutan fuera del lock
del gestor. No se depende del GIL ni se usa asyncio.

La llegada cambia a COMPLETED y reserva `notification_status=attempting` bajo lock
antes de liberar el evento al adaptador. Solo se intenta una vez, al destino de
esa Watch. Después queda `accepted` o `failed`; el evento permanece en memoria.
Un fallo/timeout no reinicia el monitor ni reenvía automáticamente. `accepted`
solo significa aceptación del envío, no entrega confirmada por WhatsApp.

Si la cancelación gana el lock antes de detectar llegada, no habrá evento.
Si la llegada ya fue reservada, cancelar devuelve que ya no está activa y no
interrumpe el intento de envío. Listar/cancelar otras Watches no espera ese HTTP.
Un fallo de envío no evita que se intente notificar las otras llegadas del snapshot.
Las notificaciones son secuenciales: un envío lento puede retrasar otros envíos
y el siguiente ciclo, sin bloquear el webhook.

El modo template conserva la plantilla aprobada y su esquema de parámetros;
este incremento no cambia su texto en Meta. El modo text añade «La vigilancia
ha finalizado» y conserva «última posición reportada». No se envía un segundo
texto libre fuera de la ventana de atención para complementar una plantilla.

SIGTERM y Ctrl+C cierran admisión, descartan altas pendientes y cancelan las activas.
Inbox y polling reciben parada antes de esperar los hilos, con seis segundos
compartidos de presupuesto. Las
esperas son interrumpibles. Una petición HTTP en curso puede superar la espera
acotada de cierre; al regresar su snapshot se descarta. Un envío ya reservado
puede terminar después de solicitar cierre. No hay recuperación tras reinicio.

## WhatsApp y prueba manual

El ID antiguo «Vigilar llegada», la opción 1 y VIGILAR conservan el prompt de alta.
MENU añade «Gestionar vigilancias»; VIGILANCIAS abre esa misma sección con:
Nueva vigilancia / Mis vigilancias / Detener vigilancia / Menú.
MISVIGILANCIAS lista solo las activas del propietario, sin IDs técnicos.
DETENER ofrece una lista nativa hasta diez Watches; con más, una lista numerada
completa. El índice se liga a watch_id al mostrar la lista, nunca al orden de
una lista recalculada al cancelar. Una selección vieja no puede cancelar otra Watch.
Los títulos nativos se ajustan a los límites de Meta; el listado textual mantiene
el móvil/placa completos. Las respuestas interactivas usan IDs y pasan por la misma
firma, allowlist, deduplicación, ventana de atención y Conversation.

Ejemplo de alta:

```text
Usuario: VIGILAR AMB-20
Bot: 🔎 Buscando AMB-20...

Bot: 👀 Vigilancia iniciada

AMB-20 · PJU886

Te avisaré cuando llegue a una sede EMI.
Escribe VIGILANCIAS para gestionar tus vigilancias.
```

Prueba con la configuración real existente, sin compartir secretos:

1. Reiniciar una única instancia con
   `.\.venv\Scripts\python.exe -m gps_emi.whatsapp.server` desde C:\GPS_EMI.
   Mantener el túnel y webhook ya configurados.
2. Desde el número autorizado enviar VIGILAR AMB-20, VIGILAR AMB-18 y un tercer
   identificador real confirmado. Esperar cada confirmación; si llegan durante
   polling/backoff, el feedback precede a una resolución diferida al próximo ciclo.
3. Enviar MISVIGILANCIAS: deben aparecer las dos o tres. Solicitar de nuevo la
   primera por su placa: debe indicar duplicado, sin crear otra Watch.
4. Abrir VIGILANCIAS → Detener vigilancia y seleccionar solo una. Volver a listar:
   las demás siguen activas. Crear otra Watch del vehículo cancelado es válido.
5. Observar movimientos operativos reales sin provocarlos para la prueba. Una
   transición reportada exterior → sede completa solo esa Watch y notifica una vez.
   Si inicia dentro, debe observar salida antes de una llegada. No simular posiciones
   ni cambiar geocercas para forzar el resultado en producción.
6. Probar MENU, UBICACION amb20 y SEDE TALLER mientras siguen vigilancias activas.
7. Cerrar con Ctrl+C. Al reiniciar, MISVIGILANCIAS debe indicar que no hay activas.

El test de integración usa tres vehículos y cuatro snapshots: cero llegadas,
llegada de A, llegada de B/salida de C, llegada de C. Verifica cuatro adquisiciones
totales, no doce. Otras pruebas cubren concurrencia con barreras/eventos, aislación
por propietario, resiliencia, cierre y fallos de entrega. Todas son offline.

## Deuda explícita

**Las vigilancias activas se pierden al reiniciar el proceso.**
Almacenamiento e historial in-memory, sin límite/retención persistente; un solo
proceso; multiusuario real todavía no implementado; persistencia futura pendiente.
No hay coordinación con otra instancia o con una vigilancia de consola aparte.
La cola de altas pendientes y el historial consumen memoria durante la sesión.
Quedan pendientes reintentos durables, seguimiento de entrega y recuperación de
eventos tras una caída. No hay validación real de este incremento hasta ejecutar
la prueba manual del usuario; pytest no sustituye esa aceptación.
