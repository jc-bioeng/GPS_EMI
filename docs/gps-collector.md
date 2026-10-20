# Captura GPS nacional mediante campañas

Estado local de fase 4, 9 de octubre de 2026. Diseño y evidencia completos en
[fase 4](widetech-official-phase4.md); autoridad: [decisiones](decisiones-arquitectonicas-renderexcel.md).

AcquisitionRuntime → Coordinator → Snapshot sigue siendo la única adquisición.
FleetPolling distribuye las publicaciones; no es el planificador HTTP. El collector
no consulta WideTech, ni interpreta llegadas. Consultas, vigilancias y campañas
comparten la misma adquisición. Leer caché no entrega otro lote al collector.

## Alcance y datos

En modo oficial, se capturan filas utilizables recibidas en adquisiciones nuevas
cuyo fltName normalizado empieza por Ambulancias, a nivel nacional. Vigilancias
siguen exclusivamente en Medellín; no hay selección manual de flotas (APL-01).
Una fila mala no bloquea las buenas; catalog.absence_eligible no decide captura.
No se usan posiciones retenidas como nuevos reportes. Los reportes válidos fuera
de orden sí se guardan históricamente, sin retroceder el estado operativo.

VEH_ID es identidad. Se conservan las columnas anteriores de Vehicle y se añaden:

| Campo | Significado |
|---|---|
| fleet_name / fleet_raw | Flota normalizada / fltName original del reporte |
| gps_original / server_original | FechaGPS / FechaServidor originales |
| provider_record_id | Id del registro del proveedor, sin garantía de unicidad |
| provenance | Método oficial de procedencia; NULL en legado sin esa información |
| gps_instant | Instante GPS interpretado en UTC, separado del original |
| historical | 1 si el instante es anterior al máximo almacenado del mismo proveedor/VEH_ID |
| timestamp_collision | 1 si otro contenido GPS ya existe para ese instante e identidad |

GPSFix se conserva en gps_fix, y la identidad en vehicle_id. Labels y flota del
catálogo vigente no se aplican a las filas históricas: la proyección del collector
usa los campos del reporte recibido. No se almacena el payload XML ni autenticación.
Metadatos inexistentes en filas antiguas permanecen NULL, sin backfill ficticio.

## Identidad, campañas y permanencia

La clave persistente es SHA-256 del proveedor, VEH_ID, instante GPS y contenido
GPS normalizado: coordenadas, velocidad, ignición, GPSFix, zonas normalizadas y
originales, y ubicación reportada. Nombres, placa, flota, FechaServidor y el Id del
proveedor no generan por sí solos una nueva observación. Una colisión del mismo
instante con otro contenido se conserva; un Id repetido no sustituye VEH_ID.
El hash representa igualdad de campos, no autenticidad del proveedor.

La clave se busca en todo el histórico, no solo en la última fila. El heartbeat
no genera filas GPS idénticas. Los argumentos/variables HEARTBEAT heredados siguen
aceptándose por compatibilidad de configuración, sin alterar la deduplicación.
Una campaña posterior puede asociarse a un reporte conocido mediante
collection_observations, sin duplicarlo ni modificar sus originales. Su received_at
registra la primera recepción en esa campaña; no demuestra presencia continua.

El catálogo y la proyección operacional mantienen su propia semántica temporal;
una fila histórica no reinicia un temporizador de vigilancia. El monitor conserva
la política de fase 5: GPS de más de 300 s no genera llegada ni actividad;
GPSFix=0 sigue siendo diagnóstico. Ver [continuidad](widetech-official-phase5.md).

## Persistencia y límites

SQLite v3, WAL, timeout de bloqueo 250 ms, transacciones IMMEDIATE y una conexión
por operación. La migración de observaciones/campañas es aditiva y transaccional.
La tabla de claves indexa también observaciones legadas que tengan identidad y
fecha, sin cambiar ni borrar duplicados históricos anteriores. Catálogo y eventos
se preservan. Véase el procedimiento de reversión en [fase 4](widetech-official-phase4.md).

GPS_EMI_DATA_DB conserva su valor predeterminado data/gps_observations.db relativo
al cwd; configurar ruta absoluta compartida. Docker conserva /data en volumen
persistente con UID 10001. No se ejecutó Docker ni se migró la base operativa en
este encargo. No usar down -v para una campaña.

La cola tiene 32 lotes. Encolar no inicia una escritura autorizada: el escritor
registra admisión durable frente a la campaña vigente y después escribe el lote.
Una admisión confirmada sobrevive stop/vencimiento y habilita el reintento del
mismo token; la cola no admitida se revalida y puede descartarse tras el cierre.
Hay un reintento local inmediato por lote (dos intentos en total), sin otro HTTP.
Saturación, fallo persistente o cierre forzado pueden perder muestras. Un lote
admitido no escrito queda identificado en collection_batches; no se promete
recuperarlo tras una caída porque su contenido no se persiste en la cola.
Los logs evitan filas y detalles de excepciones; /health sigue siendo liveness.

## Exportación

Se conservan ambos comandos, sin cargar .env:

```powershell
.\.venv\Scripts\python.exe -m gps_emi.analysis.export_observations --output observations.csv
.\.venv\Scripts\python.exe -m gps_emi.collector export --session ID_MOSTRADO --output observations-session.csv
```

Destino nuevo, UTF-8, lectura SQLite mode=ro. Las columnas antiguas conservan su
orden; las nuevas se agregan al final. La exportación por campaña añade
session_received_at y resuelve la tabla de asociación. El reporte conserva su
acquired_at inicial aunque se asocie a otra campaña. --from inclusivo y --to
exclusivo requieren offset: en exportación global filtran acquired_at, y por
campaña filtran su primera recepción (session_received_at). Exportaciones de bases
v1/v2 previas siguen disponibles sin migración; sus columnas originales permanecen.

Direcciones y zonas son texto no confiable: importar CSV como texto, nunca evaluar
fórmulas. SQLite, WAL y CSV contienen datos operativos sensibles; restringir acceso,
no publicarlos ni incorporarlos a Git. No hay cifrado ni purga automática añadidos.

## Crecimiento

Las estimaciones antiguas dependían del heartbeat duplicado y ya no describen
esta política. El tamaño depende de observaciones únicas, asociaciones de campañas,
admisiones y eventos; medir con el piloto. Un GPS idéntico ocupa una sola fila nueva
por identidad de contenido, pero las recepciones de lotes admitidos generan marcas
técnicas. Sin análisis geográfico, clustering ni selección de flotas en esta fase.

## Evidencia histórica anterior a fase 4

Los resultados siguientes corresponden al comportamiento y versión de entonces;
no validan la política nueva ni un despliegue actual.

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
