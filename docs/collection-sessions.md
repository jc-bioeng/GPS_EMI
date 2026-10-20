# Campañas de colección y observabilidad

Referencia del subsistema de campañas implementado en fase 4 y vigente en `a8f3f24`.
Las validaciones al final son históricas; no identifican el despliegue actual. Se reutilizan SessionStore, SessionCollector y el
coordinador central; no existe cliente HTTP ni planificador GPS adicional.
Captura oficial nacional por prefijo Ambulancias; las vigilancias siguen Medellín.

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
El destino debe ser nuevo. `--from` inclusivo y `--to` exclusivo filtran la primera
recepción por campaña (global: acquired_at), con offset obligatorio. El exportador antiguo sigue funcionando para datos sin sesión.

## Ciclo de vida y fronteras (TEC-04)

Start persiste COLLECTING con started_at y planned_end_at UTC. No cambia una campaña
activa ni extiende su duración. Solo una COLLECTING por base. La demanda se observa
aproximadamente cada segundo en SQLite, sin HTTP propio. El servidor debe tener la
misma base y única autoridad de adquisición; el CLI de campañas solo administra DB.

El snapshot incluye started_at (inicio de HTTP) y acquired_at (fin). La ventana es
[started_at de campaña, planned_end_at): deben caber el inicio y fin de adquisición.
Una petición ya en vuelo al comenzar la campaña no se incorpora aunque termine
después. Las marcas iguales al inicio son admitidas; se requiere reloj sincronizado.
No hay entrega de caché previa ni de posiciones retenidas al iniciar campañas.

La cola no confiere autorización de escritura. Al consumirla, el escritor abre
BEGIN IMMEDIATE y verifica campaña vigente, ventana y reloj actual. Registra un
collection_batches/token durable: ese es el inicio de escritura autorizado.
Stop y admisión se serializan con SQLite. Stop anterior gana; admisión anterior
permite completar el lote después de stop o vencimiento. La transacción de datos
confirma observaciones, claves, asociaciones y estado written conjuntamente.
Si falla, queda admitted y el mismo token puede reintentarse sin duplicar datos.
No se extiende planned_end_at para drenar. Los lotes en cola sin admisión se
rechazan al consumirlos después del cierre; no se confunden con escrituras iniciadas.

El worker intenta hasta dos veces cada lote, sin repetir adquisición. El cierre
acotado intenta drenar la cola; una terminación forzada puede perder contenido no
confirmado. No hay replay durable de payloads. Las marcas admitted sin written
permiten reconocer trabajo incompleto, no inventar muestras recuperadas.

## Reinicio e interrupciones (COL-04/05)

Al reiniciar, el lector de estado recupera la campaña vigente con su mismo fin.
Si ya venció, pasa a COMPLETED con stopped_at=planned_end_at original. Stop manual
queda STOPPED/manual e idempotente. Nada de esto restaura vigilancias ni detiene
health/servidor al finalizar campaña.

collection_runtime registra el último contacto local con el estado por campaña.
Un nuevo proceso registra en collection_interruptions una ventana entre ese
contacto y el nuevo, acotada al fin de campaña; no afirma que todo ese intervalo
fuera downtime ni conoce el instante exacto de caída. Primera conexión tardía usa
started_at como límite de una ventana no observada, diferenciada por reason.
Un status del CLI no se presenta como heartbeat del collector. No se inventan GPS
para esos periodos. Tras un error terminal del proveedor se conserva el plazo;
COLLECTING no acredita respuestas ni muestras. Reparar autenticación es externo.

## Deduplicación y exportación

Observaciones GPS únicas entre campañas y reinicios. Cambiar solo nombre/flota/Id
no crea otro GPS. Otra campaña recibe una asociación a la observación existente;
status cuenta asociaciones y VEH_ID distintos de esa campaña. No se duplican filas
por heartbeat. Reportes nuevos fuera de orden se conservan como historical; una
colisión de timestamp con contenido diferente se conserva y marca explícitamente.

Ambos exportadores mantienen columnas originales, añadiendo metadatos al final.
En exportación por campaña collection_session_id identifica la campaña solicitada,
y session_received_at su primera recepción; acquired_at conserva la adquisición
original del reporte. Los filtros temporales por campaña usan esa recepción, y
los globales acquired_at. Las bases previas se exportan sin migración. Detalles en
[collector](gps-collector.md) y [fase 4](widetech-official-phase4.md).

## Configuración, privacidad y límites

GPS_EMI_DATA_DB debe coincidir entre servidor y CLI; preferir ruta absoluta.
Las variables GPS_EMI_COLLECTION_HEARTBEAT_SECONDS y GPS_EMI_DATA_HEARTBEAT_SECONDS
son compatibilidad heredada (positivas), no autorizan duplicar GPS. Se mantienen
LOG_LEVEL y GPS_EMI_LOG_SUMMARY_SECONDS para logs y resúmenes. Ningún log imprime
credenciales, filas o payloads. El resumen es del proceso; status consulta SQLite.

WAL requiere almacenamiento local adecuado; exportaciones largas pueden aumentar
WAL. Cola de 32 lotes, bloqueo SQLite acotado y reintentos limitados no garantizan
captura sin pérdidas. No hay retención automática, selección de flotas, geografía,
notificaciones proactivas nuevas. La continuidad de vigilancias de fase 5 está
implementada en su propio subsistema; no cambia el plazo de campaña. Para revertir una migración, consultar
el procedimiento de backup y compatibilidad de [fase 4](widetech-official-phase4.md).

## Evidencia histórica anterior a fase 4

Las pruebas siguientes acreditaron el incremento previo y su política de entonces.
No deben interpretarse como validación de la nueva deduplicación/admisión.

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
