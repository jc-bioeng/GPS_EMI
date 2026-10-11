# Fase 5 — continuidad, recuperación y vencimiento de vigilancias

Implementación local del 11 de octubre de 2026 sobre fase 4, commit verificado
`18d2661`. Se leyeron las decisiones del árbol de trabajo, incluidas las revisiones
posteriores de VIG-07/TEC-06, que se conservan. No hay llamadas a WideTech/Meta,
arranque WhatsApp, cambio de .env, base operativa, despliegue, commit ni push.
Las bases de pruebas son temporales. El futuro arranque con base nueva aprobado
por el usuario no se ejecuta aquí.

## Componentes y responsabilidad compartida

| Componente | Evolución |
|---|---|
| Coordinator | Misma autoridad HTTP/backoff/snapshot. Registra intervalos monotónicos de pausa y expone su intersección con el origen de cada vigilancia. |
| SnapshotSource.wait | Su espera existente admite un callback temporal local; cancelar/terminar libera el future pendiente. No adquiere por otra ruta. |
| WatchManager / WatchRunner | Reutilizan monitores, validadores, identidad y canales. Ambos delegan decisiones temporales y recuperación a Continuity. |
| Nuevo monitoring/continuity.py | Estado individual de actividad, interrupción, secuencia y vencimiento. No tiene transporte, hilos, persistencia ni notificaciones. Extrae la decisión antes duplicada de aceptar y observar GPS. |
| ArrivalMonitor / ObservationValidator | Conservan transición normal, sedes exactas, identidad adaptada por VEH_ID y validación temporal existente. |
| FleetPolling | Distribuye las mismas publicaciones y avanza temporizadores locales cada 0,2 s mientras hay vigilancias. Invalida activas ante fallo terminal antes de drenar publicaciones antiguas. |
| ArrivalEvent / PresenceEvent | Evento de llegada compatible y especialización explícita PRESENCE_CONFIRMED. Canales comparten el evento, no la política de recuperación. |
| Collector, campañas, catálogo | Sin una segunda implementación ni cambios de reglas. Pausas de vigilancia no prolongan campañas. Errores siguen reiniciando ausencias provisionales TEC-01. |

La proyección continúa siendo `purpose=watch`, limitada a Medellín y excluyendo
filas retenidas. Releer caché no entrega nuevamente al collector ni avanza GPS.
Se mantienen resolución, selección, aislamiento por propietario y exclusión local
CLI/servidor. No hay IPC, métodos auxiliares ni diagnóstico remoto de WideTech.

## Máquina de estados

El ciclo de vida conserva ACTIVE, COMPLETED, CANCELLED y FAILED; añade EXPIRED
con causa interna `inactivity`. COMPLETED comprende llegada o presencia confirmada,
distinguibles por event_type. Una vigilancia terminal no vuelve a ACTIVE.

Dentro de ACTIVE, Continuity distingue seguimiento normal, interrupción individual
y recuperación con contador de sede. El estado geométrico lo conserva ArrivalMonitor.

1. Seguimiento normal: primera lectura dentro solo establece pertenencia.
   OUTSIDE → INSIDE con GPS nuevo y fresco produce ARRIVAL_DETECTED.
2. A los **300 segundos** sin GPS nuevo y fresco aceptado se entra en interrupción.
   La pausa de adquisición no suspende este detector individual.
3. Recuperación: tres GPS nuevos y frescos consecutivos en la **misma sede única**
   producen PRESENCE_CONFIRMED y COMPLETED. No se afirma hora exacta de llegada.
4. Exterior fresco devuelve al seguimiento normal desde exterior. Cambio de sede
   comienza una nueva secuencia de uno. Ambas sedes simultáneas reinician el contador
   sin escoger una. Otra interrupción de 300 s descarta la secuencia provisional.
5. Duplicados, atrasados, timestamps ausentes/incompatibles, registros retenidos,
   filas ambiguas y ausencias no aportan actividad ni confirmaciones. Los ignorados
   no simulan un exterior; la interrupción temporal puede reiniciar la secuencia.
6. Edad GPS **>300 s** impide avanzar monitor, actividad y recuperación; exactamente
   300 s todavía es fresco. `--stale-warning-seconds` solo ajusta diagnóstico.
   GPSFix=0 y GPS futuro mantienen sus advertencias anteriores, sin veto nuevo.

Las reglas materiales de TEC-05 fueron aprobadas expresamente por el usuario
durante este encargo: misma sede, reinicios, exterior y terminación tras confirmar.
La no selección arbitraria cuando se reportan ambas sedes es un detalle técnico
coherente con la regla de sede única y el dominio existente.

## Relojes, origen y pausas

`--watch-inactivity-seconds` existe en CLI y servidor; predeterminado **43200**,
positivo y finito. WatchConfig.inactivity_seconds ofrece la misma configuración
para composición. No se cambia .env ni la configuración de adquisición.

El origen inicial es el alta local de la vigilancia, medido con reloj monotónico.
Cada GPS nuevo y fresco aceptado establece un nuevo origen local. No se retrotrae
el alta a un timestamp antiguo del proveedor: un dato inicial antiguo o ausente
no provoca vencimiento inmediato ni prueba actividad nueva. La espera previa a
resolver el alta conserva su TTL anterior de 120 s; todavía no es vigilancia activa.

Para origen O e instante monotónico N:

`inactividad efectiva = N - O - suma(intersección([O,N], cada pausa))`

EXPIRED ocurre al **superar** el plazo configurado. La igualdad conserva ACTIVE.
El reloj civil evalúa edad GPS; no mide las doce horas. Saltos del reloj civil no
alargan/acortan esa duración. El adaptador oficial conserva su conversión explícita
de instante a Bogotá para los consumidores naive; no se mezclan zonas implícitamente.

Coordinator usa su clasificación recuperable existente: primer intento fallido
abre una pausa en el inicio monotónico del intento, nunca en el último GPS.
Fallos consecutivos mantienen el mismo intervalo. La siguiente publicación válida,
después de persistir catálogo, lo cierra. Una nueva interrupción abre otro intervalo.
Se descuenta solo la porción posterior al alta/última actividad, sin duplicación.
Una publicación válida con toda la flota repitiendo GPS cierra la pausa pero no
reinicia ninguna actividad individual. HTTP exitoso sin publicación no la cierra.

**Aprobación expresa adicional:** un fallo local de persistencia que impide publicar
también pausa. Mantiene categoría `persistence`, sin afirmar fallo del proveedor.
Errores terminales de autenticación, autorización, configuración y funcionales
mantienen su tratamiento y prevalecen. No se necesita confirmación manual, otra
consulta HTTP ni un vencimiento alternativo para interrupciones prolongadas.

Mientras un intento está pendiente se difiere la decisión de vencer hasta conocer
su resultado: solo entonces se sabe si debe descontarse desde su inicio. Si tiene
éxito y el plazo ya se superó, una nueva observación no rescata una vigilancia vencida.
El diferimiento no reinicia actividad. Los timeouts del transporte siguen siendo
los existentes; no se añade un temporizador HTTP paralelo ni se presume cancelación
instantánea de una petición en curso.

Los intervalos y vigilancias viven en memoria. Reiniciar no restaura ninguno;
las campañas sí mantienen su vencimiento original y su persistencia anterior.

## Concurrencia y canales

WatchManager serializa observación, tick, cancelación, reclasificación y reserva
de evento bajo su RLock. WatchRunner usa la misma exclusión para decisión temporal,
publicaciones de flota y reserva de su único evento. Otro VEH_ID no se sustituye
por etiquetas. Renombrar conserva continuidad; otra flota confirmada termina
internamente aun durante recuperación; flota desconocida no lo confirma.

La operación que fija primero el estado terminal bajo el lock gana. Una reserva
de COMPLETED anterior a cancelación/fallo permite terminar su único intento de envío;
una terminación anterior impide que una publicación atrasada emita un evento.
HTTP de notificación ocurre fuera del lock. Un envío lento puede retrasar el ciclo
de distribución; al retomarlo se evalúa el tiempo transcurrido real, no el número
de ciclos. No se promete precisión de despertador ni entrega exactamente una vez.

Consola y WhatsApp distinguen «presencia confirmada tras interrupción» de llegada.
Indican hora del **reporte GPS** y que no se conoce la hora de llegada. Una confirmación
completa la vigilancia incluso si falla el envío: no hay reintento automático/durable.

La plantilla de llegada existente no se utiliza para recuperación. PresenceEvent
se envía por Messenger.reply con su texto específico, también cuando arrival_mode
es template; aplica la ventana de atención existente. Fuera de ventana queda fallo
`service_window_closed`, sin envío alternativo. No se creó una plantilla Meta.
Aceptación del envío no prueba recepción. Vencimiento/reclasificación no añaden
avisos proactivos APL-04/05; el aviso terminal de adquisición previo se conserva.

## Decisiones y evidencia

ARQ-01/02/03: única autoridad y snapshots. VIG-01–11: sedes/transiciones, antigüedad,
interrupción/recuperación, vencimiento/pausa, identidad, reclasificación y no restauración.
TEC-05 queda concretado por aprobación expresa; TEC-06 aplica VIG-07 revisado e
incluye persistencia local por aprobación adicional. COB-03 sigue Medellín.
COL-04 y TEC-01 conservan sus contratos; APL-01–05 y PER-03/fase 6 no se adelantan.

`tests/test_phase5_continuity.py` utiliza relojes inyectados, datos sintéticos,
SQLite temporal y eventos/barreras de sincronización; sin sleeps de minutos/horas.
Cubre límites exactos, datos inválidos/repetidos/retenidos, secuencias, múltiples
pausas y altas durante pausa, fallo SQLite, publicación tras persistencia lenta,
vencimiento sin publicación, carreras y reserva única, prioridad terminal, campañas,
paridad CLI/adaptador WhatsApp, configuración y contenido de los avisos.

Las pruebas anteriores que permitían llegada con GPS antiguo se actualizan a
VIG-10. Las pruebas de transición que usaban datos viejos incidentalmente reciben
un reloj fresco explícito; conservan sus comprobaciones de identidad, canales y
adquisiciones. ScriptedSnapshots falla de forma acotada ante guion agotado, evitando
confundir un fixture incompleto con una interrupción recuperable interminable.

Resultados reales del cierre local:

- **143 pruebas específicas aprobadas en 2,67 s**, incluidas 45 nuevas de fase 5.
- **Regresión completa: 1022 aprobadas, 0 fallidas, en 27,98 s**; incluye CLI,
  WhatsApp, catálogo, campañas/collector y exclusión entre procesos.
- `git diff --check` limpio; enlaces locales y codificación UTF-8 sin alertas.
- Revisión del diff y archivos nuevos; búsqueda local de patrones de claves/tokens
  y credenciales en URL sin alertas. Gitleaks, detect-secrets y trufflehog no están
  instalados; esta revisión no es una certificación absoluta de ausencia de secretos.
- HEAD permanece `18d2661`; índice vacío. No se hizo commit ni push.

La primera regresión expuso expectativas históricas de STALE y un fixture que
agotaba su guion; se corrigieron antes del resultado final. La ejecución final
terminó normalmente; las cifras anteriores intermedias no se presentan como cierre.
No quedan decisiones materiales necesarias pendientes para esta implementación;
las aprobaciones de TEC-05 y persistencia local están registradas expresamente.

El comando usa
Python 3.12 del runtime local, `.venv/Lib/site-packages` y `src` en PYTHONPATH:
`python -m pytest -q -p no:cacheprovider --tb=short --basetemp=<nuevo bajo build>`.
El fixture común prohíbe red y time.sleep. No se reutilizan cifras de fases previas.

## Límites y archivos

No hay validación real de WideTech/Meta, prueba de entrega WhatsApp, Docker/Ubuntu,
despliegue ni ensayo sobre base operativa. El piloto posterior debe comprobar esos
puntos de forma acotada, con una sola autoridad e intervalo aprobado de 30 s,
sin volcar credenciales, flota completa ni datos operativos. No se fuerza movimiento
de vehículos reales para provocar eventos. Cobertura desconocida y límites de
TEC-01 permanecen; una prueba sintética no certifica disponibilidad del proveedor.

Se conservan cierres históricos de fases 2–4. Se actualizan registro de decisiones,
índice, guía, operación y múltiples vigilancias. Código: acquisition, config, CLI,
modelos, monitoring (continuity nuevo, runner, watches, fleet_polling), consola,
WhatsApp (server, notifier, formatting). Pruebas: phase5_continuity nuevo,
snapshot_fakes, CLI/config, runner y multiple_watches.

Se preservan `.codemapignore`, `docs/auditoria-api-oficial.md` y
`docs/prompt-integracion-api-oficial.md` como cambios ajenos; el índice no se prepara.


### Inventario exacto de archivos del encargo

Rutas relativas a `C:/GPS_EMI` (24 archivos; los tres ajenos citados arriba se excluyen):

- `docs/README.md`
- `docs/decisiones-arquitectonicas-renderexcel.md` (conserva la revisión previa aprobada)
- `docs/guia-del-sistema.md`
- `docs/multiple-watches.md`
- `docs/operacion.md`
- `docs/widetech-official-phase5.md` (nuevo)
- `src/gps_emi/acquisition.py`
- `src/gps_emi/cli.py`
- `src/gps_emi/config.py`
- `src/gps_emi/models.py`
- `src/gps_emi/monitoring/continuity.py` (nuevo)
- `src/gps_emi/monitoring/fleet_polling.py`
- `src/gps_emi/monitoring/runner.py`
- `src/gps_emi/monitoring/watches.py`
- `src/gps_emi/notifications/console.py`
- `src/gps_emi/whatsapp/formatting.py`
- `src/gps_emi/whatsapp/notifier.py`
- `src/gps_emi/whatsapp/server.py`
- `tests/snapshot_fakes.py`
- `tests/test_cli.py`
- `tests/test_config.py`
- `tests/test_multiple_watches.py`
- `tests/test_runner.py`
- `tests/test_phase5_continuity.py` (nuevo)


## Commit selectivo posterior — 11 de octubre de 2026

Por autorización posterior del usuario se prepara el commit local de fase 5.
Los apartados anteriores conservan las condiciones del encargo de implementación.
Incluye exclusivamente los 24 archivos del inventario, con las decisiones aprobadas
VIG-07/TEC-05/TEC-06; se preservan fuera del índice los tres archivos ajenos citados.

Nueva ejecución para este cierre: **1022 pruebas aprobadas en 33,11 s**, con Python
3.12, dependencias locales y basetemp `build/phase5-commit-20261011`. Sin red ni
bases operativas. Se revisan íntegramente el diff staged y los archivos nuevos,
las rutas seleccionadas y patrones de contraseñas/tokens/cookies/claves/cadenas
de conexión, sin imprimir valores sensibles. No hay detector especializado
instalado (gitleaks, detect-secrets y trufflehog). Se exige `git diff --cached --check`
y verificación del contenido final del índice antes del commit. El hash se informa
en la entrega. No se publica ni se hace push.
