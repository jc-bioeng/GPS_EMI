# Captura GPS pasiva

El collector observa snapshots ya adquiridos por `FleetPolling` (el coordinador
real del repositorio). No tiene cliente GPS, no consulta por su cuenta y no decide
llegadas. WatchManager procesa primero el snapshot; después se entrega una copia
de los vehículos a una cola limitada de 32 snapshots. Un thread independiente
escribe SQLite. No se modifican ArrivalMonitor, geocercas ni la UX.

## Alcance y campos

La captura abarca la flota que ya devuelve el cliente: exclusivamente
`Ambulancias Medellin;44986;0`. Incluye todos los vehículos de cada snapshot,
con/sin zona, detenidos/en movimiento, ignición encendida/apagada, GPSFix cero,
reportes antiguos, duplicados y campos ausentes. No guarda el payload completo.

El parser ya extraía Latitude y Longitude; ahora Vehicle las conserva, junto
con los identificadores originales y Zones original. No se agregan campos
inventados. Correspondencia **observada en EMI/GPSpace**, no garantía universal:

| SQLite | Origen / significado |
|---|---|
| id | Clave local autoincremental de observación |
| acquired_at | Fin de adquisición por GPS_EMI; ISO 8601 UTC con offset |
| vehicle_id | VEHID, identidad técnica principal |
| mobile_number | VEH_LCNS con strip, número de móvil |
| plate | VEH_NAM normalizado, placa |
| vehicle_name_raw | VEH_NAM antes de normalizar |
| vehicle_license_raw | VEH_LCNS antes de normalizar |
| gps_reported_at | Fecha, interpretación actual del parser sin timezone añadido |
| latitude / longitude | Latitude / Longitude que ya extrae el parser |
| speed | Velocidad que ya normaliza Vehicle |
| ignition / gps_fix | StateIgnition / GPSFix, escalares JSON para preservar tipo |
| zones | Lista normalizada, JSON; lista vacía si no hay zonas |
| zones_raw | Zones antes de eliminar markup o extraer nombres |
| reported_location | Location, conservada sin limpiar markup |
| fingerprint | SHA-256 de los campos anteriores salvo id/acquired_at |

Valores opcionales ausentes se guardan como SQL NULL, salvo ignition/gps_fix,
que usan JSON `null`, y zones, que usa JSON `[]`. Coordenadas sin afinidad SQLite
preservan incluso un valor textual que el parser no pudiera convertir. El esquema
es versión 1 (`PRAGMA user_version`), con índices por VEHID/id y acquired_at.
Una versión desconocida se rechaza sin reescribirla.

"Crudo" significa campos disponibles después del parser actual: no es una copia
byte a byte de LoadDataLog. Se conserva markup de Zones y Location; las fechas
y coordenadas mantienen las conversiones previas. No se inventa zona horaria
para Fecha; no puede afirmarse una diferencia temporal absoluta con acquired_at
sin resolver esa limitación del proveedor. acquired_at usa el reloj centralizado,
es aware y se serializa en UTC independientemente del timezone del host.

## Frecuencia y permanencia

El polling predeterminado es 30 segundos y **solo funciona mientras existen
vigilancias o solicitudes pendientes**. Un servidor encendido 24/7 no garantiza
un dataset continuo: no se inicia polling para recolectar. Las consultas puntuales
de ubicación/sede tampoco alimentan este collector. No hay adquisición adicional.

Se compara con la última observación almacenada del mismo VEHID. Cualquier cambio
en un campo conservado produce otra fila (incluye timestamp, posición, ignición,
velocidad sin umbral, GPSFix, nombres, Zones original/normalizada y dirección).
Una observación idéntica produce una fila cada 300 segundos de adquisición por
defecto. `GPS_EMI_DATA_HEARTBEAT_SECONDS` permite ajustar ese intervalo positivo.
Sin VEHID no se deduplica ni se inventa identidad por placa. Una vuelta atrás
del reloj de adquisición se conserva, no se descarta.

La deduplicación sobrevive reinicios porque lee la última fila de SQLite, no una
caché de proceso. Los heartbeats prueban que se volvió a recibir ese reporte;
**no prueban presencia física continua**. Datos obsoletos, interrupciones y pérdidas
de captura deben considerarse al estudiar permanencia.

## Persistencia, concurrencia y fallos

`GPS_EMI_DATA_DB` predetermina `data/gps_observations.db` relativo al directorio
de trabajo. El arranque crea carpeta/base/esquema en el escritor. La configuración
se obtiene del entorno después de la carga de configuración habitual del servidor.
No se carga .env en el módulo collector ni en la utilidad de exportación.

Cada lote abre conexión, usa una transacción atómica y cierra la conexión en su
propio thread; no se comparten conexiones SQLite. Timeout de bloqueo: 250 ms.
SQLite utiliza su journal transaccional habitual. No se modifica `/health`:
sigue siendo liveness `{"status":"ok"}` sin consultar SQLite.

Errores de inicialización/escritura se registran sin filas, excepciones internas,
credenciales ni rutas; se reintenta con el siguiente snapshot. Un lote fallido se
pierde; no hay reintentos que bloqueen las vigilancias. Si la cola se llena, se
descarta el nuevo snapshot y se registra el aviso. No existe borrado automático.
El cierre detiene primero el polling y después permite hasta dos segundos para
drenar la cola; un cierre forzado puede perder lo pendiente en memoria, mientras
las transacciones ya confirmadas permanecen. No existe garantía de captura sin
pérdidas ni de latencia cero de la copia en memoria.

Docker monta el volumen nombrado `gps-observations` en `/data` (Compose añade el
prefijo del proyecto) y fija `GPS_EMI_DATA_DB=/data/gps_observations.db`.
El directorio pertenece al UID/GID 10001, modo 0700; el proceso sigue sin root.
La base sobrevive restart, down y up. **`docker compose down -v` elimina el
volumen**. No usar esa opción para una campaña. El build excluye los datos.

## Exportar

PowerShell, sin cargar .env:

```powershell
.\.venv\Scripts\python.exe -m gps_emi.analysis.export_observations --output observations.csv
.\.venv\Scripts\python.exe -m gps_emi.analysis.export_observations --db data/gps_observations.db --output observations-period.csv --from 2026-09-24T00:00:00-05:00 --to 2026-09-25T00:00:00-05:00
```

En Docker:

```powershell
docker compose --env-file NUL exec -T gps-emi python -m gps_emi.analysis.export_observations --output /data/observations.csv
docker compose --env-file NUL cp gps-emi:/data/observations.csv ./observations.csv
```

CSV UTF-8 con encabezados, campos JSON preservados y sin fingerprint interno.
La conexión es `mode=ro`; no crea una base inexistente ni modifica registros.
El archivo destino debe ser nuevo. `--from` inclusivo y `--to` exclusivo filtran
**acquired_at**, requieren offset/Z y se convierten a UTC. No filtran por fecha
GPS ni criterios analíticos. Un export largo puede bloquear brevemente al escritor
con el journal actual; sus lotes fallidos se notifican y descartan.

Tratar direcciones y nombres como texto no confiable: el CSV conserva valores
originales, incluidos posibles prefijos de fórmulas. Importar las columnas como
texto en hojas de cálculo, no evaluar contenido como fórmulas.

## Privacidad

Solo se serializa la lista explícita de campos técnicos de Vehicle, nunca Watches,
owner_id, notification_target, teléfonos WhatsApp, conversaciones, nombres de
usuarios, cookies, tokens, App Secret o payloads de autenticación. DB, journals,
carpeta data y exportaciones observations*.csv están ignorados por Git. Mantener
otros nombres de exportación fuera del repositorio y revisar antes de publicar.
Estos datos de ambulancias siguen siendo operativos sensibles: restringir acceso
al volumen y exportaciones; SQLite no cifra ni implementa control de acceso propio.

## Crecimiento estimado (no medición de flota real)

No se consultó GPSpace: no conocemos el número real de móviles ni el ritmo de
cambio. Suponiendo **100 vehículos**, 24 horas de snapshots activos al día,
heartbeat 300 s y **1–2 KB por fila incluyendo índices**:

| Campaña | Reportes idénticos, 288 filas/vehículo/día | Cambio cada 30 s, 2880 filas/vehículo/día |
|---|---|---|
| 7 días | 202–403 MB | 2,02–4,03 GB |
| 14 días | 403–806 MB | 4,03–8,06 GB |
| 30 días | 864–1728 MB | 8,64–17,28 GB |

Unidades decimales; multiplicar por N/100 para otra flota y por la fracción de
tiempo de polling efectivo. Direcciones/markup extensos, duplicados sin VEHID,
journals y exportaciones pueden elevar el tamaño. Medir después de una campaña
piloto; no se establece retención automática ni se presenta esta estimación como
límite garantizado.

## Análisis posterior

El dataset permitirá estudiar ignition OFF, velocidad cero, GPSFix, permanencia,
distancias a sedes, discrepancias con Zones, múltiples VEHID por región, drift,
episodios estacionarios, clustering espacial, distribución de error y percentiles
de distancia. No se implementa análisis espacial, mapas, geocercas alternativas ni
se afirma que DBSCAN deba ser el algoritmo final. Nada de esto participa hoy en
las decisiones operativas.

## Validación local del 24/09/2026

27 pruebas específicas y 665 pruebas totales aprobadas (una advertencia conocida
de caché pytest en Windows); `git diff --check` sin errores. Se probaron esquema,
campos opcionales, tipos/zonas, cambios/heartbeat, reapertura, bloqueo SQLite,
rollback, cola saturada, escritor bloqueado, aislamiento operativo y exportación.
Todo con datos sintéticos y bases temporales, sin llamadas GPSpace/Meta.

Docker build/up correctos; health 200 y estado healthy. Base operacional creada
por el arranque en el volumen `gps_emi_gps-observations`; escritura comprobada
como UID/GID 10001. Una base sintética separada dentro del mismo volumen conservó
su fila tras `docker compose restart`, y se exportó correctamente con rango
temporal. Sus archivos se eliminaron después de comprobarla. No se insertaron
filas sintéticas en la base operacional. Logs revisados sin errores del collector.
No se ejecutó down/up como prueba adicional; la persistencia entre recreaciones
se apoya en el volumen nombrado, que no debe eliminarse con `down -v`.
