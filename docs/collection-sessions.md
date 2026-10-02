# Sesiones de colección y observabilidad

No implementa clustering ni modifica geocercas, ArrivalMonitor, reglas de llegada,
identidad VEHID o la UX de WhatsApp. El servidor utiliza el collector existente,
ahora condicionado a una sesión persistida. No captura sin sesión activa.

## Uso PowerShell

El servidor debe estar ejecutándose y ambos procesos deben apuntar a la misma DB.
Estos comandos no cargan .env, no autentican GPSpace y no realizan consultas GPS.

```powershell
$env:GPS_EMI_DATA_DB = 'C:\GPS_EMI\data\gps_observations.db'
.\.venv\Scripts\python.exe -m gps_emi.collector start --duration 24h
.\.venv\Scripts\python.exe -m gps_emi.collector status
.\.venv\Scripts\python.exe -m gps_emi.collector stop
.\.venv\Scripts\python.exe -m gps_emi.collector export --session ID_MOSTRADO --output observations-session.csv
```

También admite 30m, 6h, 3d, 7d y segundos (`30s`) para validaciones. No acepta cero,
negativos, fracciones ni unidades desconocidas. Máximo: 3650 días. `--db RUTA`
antes del subcomando sustituye GPS_EMI_DATA_DB. Dos starts concurrentes no crean
dos sesiones: uno informa que ya existe una activa y no cambia su plazo.

Docker en Windows, sin expandir la configuración sensible de Compose:

```powershell
docker compose --env-file NUL exec -T gps-emi python -m gps_emi.collector start --duration 24h
docker compose --env-file NUL exec -T gps-emi python -m gps_emi.collector status
docker compose --env-file NUL exec -T gps-emi python -m gps_emi.collector stop
docker compose --env-file NUL exec -T gps-emi python -m gps_emi.collector export --session ID_MOSTRADO --output /data/observations-session.csv --from 2026-10-02T00:00:00-05:00 --to 2026-10-03T00:00:00-05:00
docker compose --env-file NUL cp gps-emi:/data/observations-session.csv ./observations-session.csv
docker compose --env-file NUL logs -f --tail 100 gps-emi
```

En Linux sustituir `--env-file NUL` por `--env-file /dev/null`. Sin Docker:

```sh
export GPS_EMI_DATA_DB=/ruta/privada/gps_observations.db
.venv/bin/python -m gps_emi.collector start --duration 24h
.venv/bin/python -m gps_emi.collector status
```

El volumen existente `gps-observations:/data` y el bind `127.0.0.1:8000:8000`
permanecen. SQLite no se expone por red. No ejecutar `down -v` si se quieren
conservar datos. Para inspección operacional usar status y export, no volcar
credenciales o bases completas a logs. CSV UTF-8 conserva zonas originales y
normalizadas, tipos JSON y datos crudos; importar como texto en hojas de cálculo.
El destino debe ser nuevo. `--from` inclusivo y `--to` exclusivo filtran acquired_at,
con offset obligatorio. El exportador antiguo sigue funcionando para datos sin sesión.

## Ciclo de vida y reinicio

Start persiste inmediatamente COLLECTING, started_at y planned_end_at en UTC aware.
Los timestamps GPS siguen siendo naive tal como los interpretaba el parser.
Status presenta fechas en America/Bogota e incluye cuenta de observaciones y
VEHID distintos. No se deduce identidad por placa.

El fin es persistente: al reiniciar no se reinicia la duración. Si queda plazo,
el coordinador continúa la captura; si venció durante downtime, el siguiente
chequeo marca COMPLETED con stopped_at igual al planned_end_at original. Stop
marca STOPPED/manual y conserva datos; repetir stop no altera la fecha anterior.
Ninguna terminación de colección detiene servidor, health o watches.

Se descartan lotes pendientes procesados después de stop/vencimiento; se prefiere
no agregar datos a una sesión finalizada. Un snapshot anterior al start o posterior
al fin nunca se atribuye a ella. No se reconstruyen datos perdidos durante downtime.
Watches siguen en memoria y no sobreviven al reinicio, como antes.

Un error terminal de proveedor (incluido SESSION_EXPIRED) bloquea la demanda de
esa sesión en el coordinador del proceso para no reintentar indefinidamente.
La sesión conserva su plazo y aparecerá COLLECTING hasta terminar: ese estado
**no garantiza muestras**. Revisar provider_status. Tras corregir la autenticación
externamente, reiniciar el servicio permite reanudar el plazo restante, o se puede
detener la campaña y crear otra. Los fallos transitorios mantienen el backoff existente.

## Logging y configuración

Todos los entrypoints operacionales reutilizan `gps_emi.observability.configure_logging`:
script `gpspace_loaddatalog.py`, módulo/console script CLI, servidor por módulo,
console script y Docker, y CLI de sesiones. El exportador antiguo mantiene su salida
de conteo sin trazas adicionales. No se instala un handler por importación.

| Variable | Predeterminado | Uso |
|---|---|---|
| GPS_EMI_DATA_DB | data/gps_observations.db | Compose fija /data/gps_observations.db |
| GPS_EMI_COLLECTION_HEARTBEAT_SECONDS | 300 | Cambios siempre se guardan; iguales cada heartbeat |
| LOG_LEVEL | INFO | DEBUG/INFO/WARNING/ERROR; CLI conserva --log-level |
| GPS_EMI_LOG_SUMMARY_SECONDS | 300 | Resumen del servidor; entero positivo, mínimo 1 s |

En servidor y CLI operacional estas variables pueden venir del entorno habitual;
los comandos de sesiones requieren entorno exportado o --db, sin leer .env.
El heartbeat inválido deshabilita el collector y registra aviso; nivel inválido
vuelve a INFO. El resumen usa contadores del proceso, no totales históricos; status
ofrece los totales de la sesión en SQLite. La configuración de logs no imprime
tokens ni headers, no vuelca payloads ni excepciones autenticadas.

Ejemplos ilustrativos, no datos reales:

```text
INFO: service started version=0.1.0 polling_seconds=30 summary_seconds=300
INFO: provider_status=PROVIDER_OK
DEBUG: acquisition completed records=50 vehicles=43 duration_ms=382.0
WARNING: provider_status=NETWORK_ERROR
INFO: provider recovered downtime_seconds=18.0
ERROR: provider_status=SESSION_EXPIRED
INFO: collection started session_id=<id> duration=86400 planned_end_at=<UTC>
INFO: operational_summary uptime_seconds=300 provider_status=PROVIDER_OK acquisitions=10 provider_failures=0 vehicles_last_snapshot=43 active_watches=2 collection_session=COLLECTING observations_written=430 collector_errors=0 dropped_snapshots=0
INFO: collection completed session_id=<id> duration=86400 observations=12540 vehicles=43
```

Los logs reales incluyen timestamp Bogotá y nombre de logger. Cada ciclo va a DEBUG;
INFO muestra cambios de estado, eventos y resúmenes. Watch IDs y VEHID permiten
relacionar creación, transición, llegada y notificación sin registrar propietarios
ni teléfonos. STALE es diagnóstico: no se cambió el criterio de aceptación existente.
Los errores repetidos de estado/escritura SQLite se cuentan, con aviso al cambiar
de estado y mensaje de recuperación. Los logs de órdenes ejecutadas mediante
`docker exec` se ven en esa consola; el servidor también registra el estado observado.

Docker usa stdout con driver json-file rotado: 10 MB por archivo, tres archivos.
Esto limita disco (~30 MB por contenedor), **no garantiza conservar meses de logs**.
Para auditorías largas debe planearse archivado externo, fuera de este incremento.
Recrear el contenedor aplica los cambios del driver.

## Deuda y límites

Sin análisis espacial, auto-login, persistencia de watches ni garantías de entrega
exactamente una vez. SQLite WAL requiere disco local/volumen adecuado, no un filesystem
de red. Exportaciones largas pueden retrasar checkpoint y aumentar WAL. Cola limitada
a 32 snapshots y timeout SQLite de 250 ms: saturación/errores pierden muestras pero
no bloquean notificaciones. El servicio sigue healthy aunque collector falle.
El reloj del host debe estar sincronizado; no se inventa timezone del GPS.
El control verifica SQLite cada segundo; status calcula conteos indexados, cuyo
costo crecerá con la campaña. No hay borrado automático ni recuperación de lotes fallidos.

## Validación del 02/10/2026

Baseline: 665 tests. Resultado final: 705 aprobados, incluidos 40 tests nuevos de
sesiones/observabilidad; advertencia conocida de caché pytest en Windows.
Diff check y Compose config correctos. Lifecycle local sintético validado.

Imagen construida y servidor probado en contenedor aislado, con red externa
deshabilitada, configuración ficticia y volumen nombrado exclusivo de prueba.
Se verificaron health, UID 10001, captura desde una sesión sin watches, heartbeat,
persistencia del ID/plazo/observaciones tras restart, stop manual, exportación CSV,
fin automático sin detener health, vencimiento durante downtime y SIGTERM con
exit code 0. Logs con resúmenes y eventos, sin credenciales ficticias ni errores.
Contenedor y volumen sintéticos eliminados al finalizar. El servicio operacional
y su volumen no se recrearon ni se migraron durante esta prueba; aplicar la nueva
imagen al servicio es un paso de despliegue separado. No se consultó GPSpace/Meta.
