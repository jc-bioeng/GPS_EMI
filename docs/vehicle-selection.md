# Resolución ambigua con selección explícita

> Edición pública: identificadores sustituidos por ejemplos sintéticos (AMB-9001,
> TEST-PLATE-A y similares). En relatos de validación son seudónimos, no
> transcripciones de registros reales ni nuevas pruebas.

`resolve_vehicle()` devuelve NOT_FOUND, RESOLVED o AMBIGUOUS y conserva todos los
Vehicles coincidentes, en el orden recibido, sin preferir DEMO/no DEMO, fechas,
GPSFix ni posiciones. `find_vehicle()` conserva su contrato fail-safe: lanza
AmbiguousVehicleError; ahora la excepción transporta candidatos estructurados.
La consola mantiene el rechazo seguro. El selector se integra en WhatsApp.

Los datos disponibles son los del modelo real: VEHID, mobile_number, plate,
Location, timestamp GPS, velocidad, ignición, GPSFix y zonas. No existe un tercer
campo de nombre independiente en Vehicle y no se inventó uno. Cada contexto
conserva copias de los candidatos y sus LocationResult con report_age/stale
calculados mediante el mismo evaluador de las consultas. Al mostrar otra página,
la antigüedad se vuelve a calcular sobre el timestamp original, sin consultar GPS.

```text
Coordinator → snapshot en memoria → Vehicle → resolve_vehicle
                       ├─ NOT_FOUND → respuesta segura
                       ├─ RESOLVED  → operación normal
                       └─ AMBIGUOUS → PendingVehicleSelection
                                       │ propietario + operación + candidatos
                                       │ selector WhatsApp
                                       ▼
                               selección consumida atómicamente
                                       │ VEHID exacto
                          ┌────────────┴────────────┐
                     LOCATION                CREATE_WATCH
                  snapshot compartido            siguiente ciclo común
                  find_vehicle_by_id        find_vehicle_by_id
                  resultado exacto          Watch owner+VEHID+target
```

En fase 3, LOCATION conserva el alcance nacional y CREATE_WATCH el alcance
Medellín de su fuente. Se reutiliza el mismo selector. Los informes de candidatos
conservados retienen procedencia, versión y acquired_at; paginar no escribe el
catálogo ni actualiza su adquisición. No se añaden candidatos desde SQLite ni
reglas nuevas por ausencia confirmada. El indicador de dato conservado pertenece
a calidad de ubicación y no incorpora los mensajes de flota aplazados APL-05.

## Contexto y seguridad

`selection.PendingSelections` es independiente de WhatsApp. Guarda un contexto por
owner, con operation (LOCATION/CREATE_WATCH), original_identifier, candidates,
candidate_reports, notification_target y created_at. created_at usa reloj
monotónico para el TTL de **300 segundos**. La expiración se comprueba al acceder
y no se amplía al paginar. El almacenamiento es en memoria y la limpieza es
diferida al acceso o sustitución; no hay recuperación tras reinicio.

La referencia interna tiene la forma `vehicle_select:<selection_id>:<choice_id>`.
Actualmente el usuario responde con un número que MessageService traduce a esa
referencia dentro de la lista vigente; también se aceptan IDs interactivos antiguos.
Ambas referencias son UUID generados para esa oferta; el servidor mantiene la
correspondencia choice_id → VEHID. No se acepta un VEHID arbitrario en su lugar.
El consumo verifica owner, contexto, vigencia y pertenencia del candidato bajo un
RLock. Quita el contexto antes de ejecutar la operación: dos respuestas no pueden
ejecutarlo dos veces, aunque lleven distintos IDs de mensaje del webhook.

MENU/MENÚ/INICIO, CANCELAR sin argumento y una nueva operación invalidan la oferta.
La generación de operación también viaja en las altas pendientes del polling:
una ambigüedad detectada tarde no reinstala un selector de una operación anterior.
Una referencia de contexto vencida o consumida no se puede reutilizar. Un número
escrito responde a la lista vigente: no identifica qué mensaje antiguo miraba
el usuario si ya se presentó una nueva lista.
CANCELAR no cancela las Watches activas; DETENER conserva su función independiente.
Una selección ya consumida compromete la operación; un MENU posterior no cancela
una creación de Watch que ya fue aceptada en la cola.

La continuación refresca por VEHID, incluso si cambian placa/nombre. Si ya no existe
o aparece duplicado técnicamente, se informa que el registro no está disponible de
forma inequívoca. No se busca otro vehículo por el identificador inicial. Un fallo
posterior de adquisición tampoco permite reutilizar el selector: hay que solicitar
la operación otra vez. Las Watches respetan la unicidad owner+VEHID+ACTIVE.

## Presentación

`whatsapp.vehicle_selection` conserva la estructura interna LIST;
`WhatsAppClient.send_vehicle_selection` la presenta como texto numerado, sin
selector nativo. MessageService conserva la correspondencia número/referencia.
El transporte usa `WhatsAppClient._send` y Messenger comprueba la ventana. La firma,
allowlist, Inbox y deduplicación del webhook se mantienen. No se hace HTTP de GPS
en el webhook. El worker procesa ubicación; el polling compartido resuelve altas.

Hay ocho candidatos por página y hasta dos filas de navegación. Se conservan
todos los candidatos entre páginas. Títulos limitados a 24 caracteres,
descripciones a 72, IDs inferiores a 200 y un máximo de diez filas por mensaje.
La navegación valida owner/contexto/TTL y no consume la selección.

Se muestra nombre/móvil, placa, antigüedad y ubicación abreviada. Si dos filas
visibles coinciden, se prueban timestamp, GPSFix, velocidad e ignición existentes.
Solo si siguen siendo indistinguibles se muestra «Registro: <VEHID>». Si aún no
pueden distinguirse dentro de los límites de presentación, se rechaza con un
mensaje seguro. Ninguna variante elige por el usuario.

Si los candidatos no tienen VEHID o comparten uno, se conserva el rechazo seguro:
no se presenta una selección que prometa distinguir identidades indistinguibles.
No se deduplica ni modifica el inventario original.

Ejemplo ilustrativo inspirado en TEST-PLATE-B, sin valores reales de sesión:

```text
⚠️ Encontré varios registros para TEST-PLATE-B.

Selecciona el móvil correcto para continuar.
Página 1 de 1. Válida durante 5 minutos desde la primera lista.

1. TEST-PLATE-B DEMO
TEST-PLATE-B · 🟢 Hace 20 s · Ubicación A

2. TEST-PLATE-B
TEST-PLATE-B · 🟢 Hace 40 s · Ubicación B

3. TEST-PLATE-B-DEMO
TEST-PLATE-B · ⚠️ Hace 8 min · Ubicación C
```

LOCATION: enviar UBICACION TEST-PLATE-B → feedback → lista → responder 2 →
«Consultando el registro seleccionado...» → lectura del snapshot compartido → última posición
reportada del VEHID del segundo. No muestra datos del primero ni del tercero.

CREATE_WATCH: enviar VIGILAR TEST-PLATE-B → feedback → snapshot central → lista →
responder 2 → «Buscando el registro seleccionado...» → siguiente ciclo común
→ confirmación de Watch del segundo. Si ya está activa para ese propietario, se
informa duplicado. No hay un polling por candidato ni consultas adicionales para
construir la lista. Si está reportado dentro, se pide confirmación antes del alta y se exige salida
fresca tras aceptar; ver [confirmación vigente](comandos-whatsapp.md).

## Validación manual pendiente y deuda

Reiniciar una única instancia del servidor con la configuración existente. Desde
un número autorizado, probar UBICACION TEST-PLATE-B y VIGILAR TEST-PLATE-B por separado.
Elegir explícitamente el registro conocido operacionalmente, sin asumir que el que
no dice DEMO sea el correcto. Comprobar identidad, ubicación y lista de vigilancias.
Probar una referencia antigua tras MENU y dejar otra oferta cinco minutos sin elegir:
ambas referencias deben rechazarse. Los números tras MENU corresponden al menú
vigente, no a la lista anterior. Para vigilar el mismo VEHID de nuevo debe aparecer
el aviso de vigilancia activa. No compartir credenciales ni contenidos de sesión.

La suite usa tres vehículos sintéticos de VEHID diferentes con placa TEST-PLATE-B y
selecciona el segundo. Incluye continuidad por VEHID tras cambios, desaparición,
expiración, replay, propietarios, consumo concurrente, oferta tardía, paginación,
firma, allowlist y deduplicación. No se valida Meta/GPSpace real con pytest.

Los contextos siguen en memoria, sin restauración. La autoridad de adquisición
tiene exclusión local CLI/servidor; no coordina otros hosts. Los contextos ya
se aíslan por propietario autorizado; no hay administración persistente de roles.
La entrega del selector depende de Meta y de la ventana de atención. Una lista
puede mostrar datos que cambiaron desde su adquisición; por eso siempre se
resuelve de nuevo el VEHID seleccionado sobre el snapshot compartido. No hay reintentos automáticos de una selección
consumida ni heurísticas para decidir registros indistinguibles.
