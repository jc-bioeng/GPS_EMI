# Guía de comprobaciones de GPS_EMI en Oracle — fase 6

> Edición pública: identificadores sustituidos por ejemplos sintéticos (AMB-9001,
> TEST-PLATE-A y similares). En relatos de validación son seudónimos, no
> transcripciones de registros reales ni nuevas pruebas.

Preparada el 11 de octubre; reconciliada el 19 de octubre de 2026 con los datos
posteriores del operador conservados en el análisis de campaña y la fuente del PDF.
Referencia interna de instalación: no verificada por SSH en esta revisión.
Crear este documento no ejecuta pruebas ni cierra fase 6.

## 1. Punto de partida y resultados conocidos

Los valores de la instalación comunicada se conservan en el original privado.
Los parámetros siguientes son variables de shell del operador, no nuevas variables
de configuración de la aplicación.

| Parámetro / concepto | Significado |
|---|---|
| `APP_DIR` | Ruta absoluta del checkout instalado |
| `COMPOSE_PROJECT` | Proyecto Compose existente; no se deduce de la carpeta |
| `CONTAINER_NAME` | Contenedor efectivo; puede fijarse con `compose.name.yaml` |
| Servicio `gps-emi` | Clave real de servicio de `compose.yaml`, independiente de los nombres anteriores |
| Archivos Compose | Base versionada y overrides locales `compose.official.yaml`, `compose.name.yaml`, si existen en esa instalación |
| Volumen de datos | Nombre efectivo a comprobar mediante montajes |
| SQLite y estado | `/data/gps_observations.db` y `/data/state`, rutas internas del despliegue |
| Código local de referencia | `a8f3f24`; imagen efectiva pendiente de identificar |
| `OLD_CONTAINER` | Contenedor anterior verificado, solo para reversión cuando exista |

El operador ya reportó construcción correcta, creación del volumen nuevo,
contenedor healthy y funcionamiento de la consulta por WhatsApp. Registrar esos
resultados como evidencia del operador, no como ejecución automática de esta guía.
No se trasladan datos del piloto anterior.

La retención técnica de 30 días todavía requiere implementación y pruebas de
fase 6. La rotación Docker por tamaño no equivale a esa retención.

## 2. Preparación de la sesión SSH

Ejecutar los comandos siguientes en Oracle, no en Git Bash de Windows:

```bash
read -r -p 'Ruta absoluta del checkout: ' APP_DIR
read -r -p 'Proyecto Compose existente: ' COMPOSE_PROJECT
read -r -p 'Contenedor efectivo: ' CONTAINER_NAME
cd -- "$APP_DIR"
dc() { docker compose -p "$COMPOSE_PROJECT" -f compose.yaml -f compose.official.yaml -f compose.name.yaml "$@"; }
```

Los dos overrides son configuración privada de Oracle y no están en este checkout.
Comprobar que existen y que el proyecto es el de la instalación antes de usar
el atajo: cambiar carpeta o contenedor no cambia el proyecto Compose.

`dc` es un atajo temporal para esta terminal. Repetir su definición al reconectar.
No ejecutar una CLI de adquisición GPS en Windows mientras el servidor esté activo.
Los comandos `gps_emi.collector` de esta guía administran SQLite y no crean otra
autoridad HTTP; se pueden ejecutar mientras el servidor funciona.

Realizar primero las comprobaciones sin interrupción. Reservar el reinicio para
un momento en el que se puedan perder las vigilancias activas de prueba. No usar
`down -v`, no borrar el lock y no compartir `.env`, dumps de configuración o bases.

## 3. Identificar la versión y el arranque efectivo

```bash
git log -1 --oneline
git status --short
dc config --quiet
dc ps
docker inspect "$CONTAINER_NAME" --format '{{json .Config.Cmd}}'
docker inspect "$CONTAINER_NAME" --format '{{.Image}}'
docker inspect "$CONTAINER_NAME" --format '{{range .Mounts}}{{println .Name .Destination}}{{end}}'
```

Esperado:

- Registrar commit del directorio e imagen efectiva por separado; contrastar sus
  interfaces con `a8f3f24`, sin asumir que coinciden.
- `compose.official.yaml` puede aparecer sin seguimiento: es configuración local
  preparada en Oracle. No añadir `.env` a Git para limpiar el estado.
- El comando efectivo incluye `--official`, intervalo 30 y puerto 8000.
- El montaje `/data` corresponde al volumen persistente identificado en la instalación.
- Solo la autoridad elegida está activa. Si el contenedor anterior no existe,
  registrar ese hecho; no recrearlo a partir de este documento.

Guardar el ID de imagen junto con el commit: el commit del directorio por sí solo
no prueba qué imagen está ejecutándose. No reconstruir durante esta comprobación.

Si el modo es legado, el volumen es el anterior o ambos contenedores están
adquiriendo, detener la validación y corregir la configuración antes de continuar.

## 4. Salud local, permisos, reloj y recursos

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health
dc exec -T gps-emi id
dc exec -T gps-emi python -c "import os; from pathlib import Path; paths=[Path('/data'),Path('/data/state')]; print([(str(p),p.is_dir(),os.access(p,os.W_OK)) for p in paths]); print('SQLite presente:',Path('/data/gps_observations.db').is_file())"
timedatectl status
df -h / /var/lib/docker
docker stats --no-stream "$CONTAINER_NAME"
dc logs --since 10m --tail 100 gps-emi
```

Esperado: health `{"status":"ok"}`, UID/GID 10001, directorios accesibles para
escritura, base presente después del arranque oficial y reloj sincronizado.
Si `/var/lib/docker` no es el almacenamiento real, consultar `docker info --format
'{{.DockerRootDir}}'` y comprobar espacio en esa ruta.

Registrar uso de disco y memoria como línea base; no hay un umbral de consumo
aprobado que deba inventarse. Revisar ausencia de reinicios continuos, errores de
permisos y fallos SQLite repetidos. Health prueba vida del proceso, no entrega
WhatsApp, frescura GPS ni disponibilidad del proveedor.

## 5. Consultas reales por WhatsApp

Enviar desde el teléfono autorizado; anotar hora y resultado sin copiar datos
operativos a Git:

| Prueba | Acción | Resultado esperado |
|---|---|---|
| Ayuda | Enviar `MENU` | Menú existente, sin cambios de navegación |
| Móvil | `UBICACION AMB-9001`, o un móvil vigente conocido | Móvil, placa y última ubicación; aviso inicial posible mientras se obtiene snapshot |
| Placa | `UBICACION TEST-PLATE-A`, solo si sigue correspondiendo al móvil usado | Misma identidad y reporte, salvo una actualización entre consultas |
| Nacional | Consultar una ambulancia conocida de otra flota | Ubicación disponible si pertenece a una flota cuyo nombre empieza por Ambulancias |
| Sede | `SEDE POBLADO` y `SEDE TALLER` | Inventario o ausencia de resultados; advertencias de antigüedad correspondientes |
| No encontrado | Consultar un identificador ficticio | Mensaje controlado, sin resolver otra identidad arbitrariamente |
| Ambigüedad | Usar una etiqueta duplicada solo si existe naturalmente | Selector existente; elegir una opción no crea otra adquisición independiente |

No forzar en el proveedor etiquetas duplicadas o reclasificaciones para probar.
Si un caso no existe en la flota disponible, marcarlo como no observado y mantener
su evidencia offline. Una ubicación antigua con advertencia es un resultado
válido; no es prueba de que el vehículo esté físicamente allí.

Durante una campaña activa, revisar los resúmenes de logs (intervalo predeterminado
300 s) para comprobar adquisiciones y errores. Varias consultas pueden compartir
caché; no esperar una llamada HTTP por mensaje ni bajar el intervalo para probar.
Los contadores agregados por sí solos no certifican cada separación exacta entre
intentos: esa propiedad también se prueba con relojes controlados offline.

## 6. Gestión y eventos de vigilancia

Usar una ambulancia de Medellín y un destinatario de prueba:

1. Enviar `VIGILAR <MOVIL>` y comprobar resolución y alta.
2. Enviar `VIGILANCIAS` y comprobar que aparece la vigilancia propia.
3. Enviar `DETENER` y seguir el selector para cancelar esa vigilancia.
4. Verificar que la cancelada deja de estar activa.
5. Intentar vigilar una ambulancia de otra flota conocida: no debe admitirse.

Casos de observación natural, sin ordenar movimientos de ambulancias:

| Caso | Esperado |
|---|---|
| Alta reportada dentro (imagen con ajuste `a8f3f24`) | Confirmación antes de alta; aceptar exige exterior fresco antes de llegada o presencia interior |
| GPS nuevo y fresco: exterior → interior | Un evento de llegada y un intento de notificación |
| GPS de más de 300 s | No genera llegada ni renueva actividad |
| Interrupción de 300 s seguida de tres GPS nuevos y frescos en la misma sede | Una presencia confirmada, distinta de llegada, y vigilancia completada |
| Exterior fresco durante recuperación | Seguimiento normal desde exterior |
| Cambio confirmado de flota | Finalización interna, sin aviso proactivo de causa |

La recepción en el teléfono es la evidencia de entrega; la aceptación de Meta no
basta. Registrar por separado evento detectado, intento de envío y recepción.
La recuperación usa texto dentro de la ventana de atención; fuera de ella falla
sin usar la plantilla de llegada ni reintentar automáticamente. No considerar esa
limitación documentada una prueba de entrega exitosa.

El plazo de doce horas se prueba determinísticamente offline. No reducirlo en el
servicio compartido ni esperar doce horas solo para repetir esa prueba.

## 7. Campaña corta, captura y exportación

Comprobar primero que no hay una campaña ajena activa:

```bash
dc exec -T gps-emi python -m gps_emi.collector status
```

Si aparece COLLECTING de otra campaña, no detenerla ni reemplazarla. Esperar o
usar sus comprobaciones de lectura con el operador responsable.

Si no hay campaña activa, iniciar una prueba de 15 minutos:

```bash
dc exec -T gps-emi python -m gps_emi.collector start --duration 15m
```

Anotar `Session`, `Started` y `Ends`. Tras uno o varios ciclos, consultar:

```bash
dc exec -T gps-emi python -m gps_emi.collector status
```

Esperado: COLLECTING y asociaciones/vehículos cuando se reciben filas utilizables.
Un GPS repetido no debe crear nuevas filas solo por pasar 30 o 300 segundos.
Los conteos pueden crecer por GPS nuevos; no se exige que permanezcan fijos.
COLLECTING sin muestras no acredita captura: revisar proveedor, permisos y logs.

Para esta terminal, copiar el ID de la campaña de prueba:

```bash
read -r -p 'ID de la campaña de prueba: ' SESSION_ID
```

Continuar con respaldo y reinicio antes de que venza si se quiere comprobar
reanudación activa. Después, para comprobar stop manual de esta campaña:

```bash
dc exec -T gps-emi python -m gps_emi.collector status
dc exec -T gps-emi python -m gps_emi.collector stop
dc exec -T gps-emi python -m gps_emi.collector status
```

Verificar el ID antes de stop, porque el comando detiene la campaña activa, no
recibe ID. Esperado: STOPPED; escrituras ya admitidas pueden terminar después.
Alternativamente dejar vencer: COMPLETED y fin original. Para verificar ambas
formas, realizar otra campaña corta después de terminar la primera.

Exportar a un nombre nuevo, sin imprimir las posiciones en consola:

```bash
EXPORT_PATH="/data/validation-$(date -u +%Y%m%dT%H%M%SZ).csv"
dc exec -T gps-emi python -m gps_emi.collector export --session "$SESSION_ID" --output "$EXPORT_PATH"
```

Esperado: contador exportado, columnas originales primero, metadatos nuevos al
final y `session_received_at`. No sobrescribir exportaciones existentes. Si se
necesita revisar el CSV, descargarlo a un lugar privado fuera del repositorio e
importar sus campos como texto, sin evaluar fórmulas.

## 8. Respaldo consistente y ensayo de restauración aislado

Esta comprobación crea un respaldo nuevo; no reemplaza la base activa. Usa la API
backup de SQLite para incluir una vista consistente aunque WAL esté activo.

```bash
BACKUP_PATH="/data/backup-validation-$(date -u +%Y%m%dT%H%M%SZ).db"
dc exec -T gps-emi python - "$BACKUP_PATH" <<'PY'
import os, sqlite3, sys
from pathlib import Path
dst = Path(sys.argv[1])
fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
os.close(fd)
source = sqlite3.connect('file:/data/gps_observations.db?mode=ro', uri=True)
target = sqlite3.connect(str(dst))
try:
    source.backup(target)
    assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not target.execute('PRAGMA foreign_key_check').fetchall()
    print('Backup íntegro:', dst.name)
finally:
    target.close()
    source.close()
PY
```

Si falla, no usar ese archivo como respaldo válido; el nombre queda reservado y
debe usarse un nombre nuevo en el siguiente intento.

Guardar copia fuera del volumen y del repositorio:

```bash
read -r -p 'Directorio privado absoluto de backups, fuera del checkout: ' BACKUP_DIR
umask 077
mkdir -p -- "$BACKUP_DIR"
BACKUP_FILE="${BACKUP_PATH##*/}"
docker cp "$CONTAINER_NAME:$BACKUP_PATH" "$BACKUP_DIR/$BACKUP_FILE"
chmod 600 "$BACKUP_DIR/$BACKUP_FILE"
```

Ensayar restauración sobre una base temporal usando la imagen desplegada, sin
red, sin .env, sin montar la base activa y sin arrancar el servidor:

```bash
RUNNING_IMAGE=$(docker inspect "$CONTAINER_NAME" --format '{{.Image}}')
docker run --rm -i --network none --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$BACKUP_DIR,dst=/backup,readonly" \
  --entrypoint python "$RUNNING_IMAGE" - "$BACKUP_FILE" <<'PY'
import sqlite3, sys, tempfile
from pathlib import Path
from gps_emi.analysis.sessions import SessionStore
from gps_emi.catalog import CatalogStore
with tempfile.TemporaryDirectory() as folder:
    restored = Path(folder) / 'restored.db'
    src = sqlite3.connect((Path('/backup') / sys.argv[1]).as_uri() + '?mode=ro', uri=True)
    dst = sqlite3.connect(str(restored))
    src.backup(dst)
    assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not dst.execute('PRAGMA foreign_key_check').fetchall()
    print('Esquema restaurado:', dst.execute('PRAGMA user_version').fetchone()[0])
    dst.close()
    src.close()
    SessionStore(restored).initialize()
    CatalogStore(restored).initialize()
    print('Restauración temporal y apertura con almacenes actuales: OK')
PY
```

Esto acredita restauración y compatibilidad de los almacenes con la imagen actual,
no entrega WhatsApp ni recuperación de vigilancias. La copia en el mismo servidor
protege frente a errores de operación, no frente a pérdida completa de Oracle:
conservar además una copia privada fuera del servidor si se requiere esa protección.

## 9. Reinicio controlado y persistencia

Prueba disruptiva: se perderán vigilancias, selecciones y conversaciones en memoria.
Realizarla solo con usuarios de prueba avisados y con una campaña de prueba vigente.

Antes del reinicio, anotar el ID/plazo/conteos de campaña. Si se prueba la no
restauración de vigilancia, crear una expresamente para este ensayo.

```bash
dc exec -T gps-emi python -m gps_emi.collector status
dc restart gps-emi
dc ps
dc logs --since 5m --tail 100 gps-emi
dc exec -T gps-emi python -m gps_emi.collector status
```

Consultar de nuevo tras arrancar si el estado inicial es `starting`.
Esperado: mismo ID y mismo Ends, conteos conservados y reanudación si aún queda
plazo. Si venció durante el reinicio, COMPLETED con el fin original. No restaurar
la vigilancia de prueba; consultar `VIGILANCIAS` y crear otra solo si hace falta.
Enviar una ubicación: inicialización posible, después snapshot nuevo.

Verificar la ventana registrada y esquema sin volcar vehículos:

```bash
dc exec -T gps-emi python - "$SESSION_ID" <<'PY'
import sqlite3, sys
db = sqlite3.connect('file:/data/gps_observations.db?mode=ro', uri=True)
try:
    print('Esquema:', db.execute('PRAGMA user_version').fetchone()[0])
    print('Interrupciones de prueba:', db.execute(
        'SELECT count(*) FROM collection_interruptions WHERE session_id=?', (sys.argv[1],)).fetchone()[0])
    print('Admisiones incompletas de prueba:', db.execute(
        "SELECT count(*) FROM collection_batches WHERE session_id=? AND state='admitted'", (sys.argv[1],)).fetchone()[0])
finally:
    db.close()
PY
```

Una ventana no observada no determina el instante exacto de caída. Las admisiones
incompletas requieren revisión; no significan que exista un payload recuperable.
No provocar `kill -9`, fallos de red, credenciales inválidas o corrupción SQLite
en el servicio para repetir escenarios cubiertos offline.

## 10. Reversión al servicio anterior

No ejecutar como continuación automática de las pruebas. Usar solo si hay que
restablecer la instalación anterior o en un ensayo de reversión acordado.
Antes de detener el servicio, verificar que el contenedor anterior existe y conserva
imagen/configuración/volumen compatibles sin compartir la base v3. Si falta esa
evidencia, usar [restauración](procedimientos-recuperacion.md), sin ejecutar los
comandos siguientes por rutina.

```bash
read -r -p 'Contenedor anterior previamente verificado: ' OLD_CONTAINER
dc stop gps-emi
docker inspect "$CONTAINER_NAME" --format '{{.State.Status}}'
docker start "$OLD_CONTAINER"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
curl --fail --silent --show-error http://127.0.0.1:8000/health
```

Confirmar que el nuevo está detenido antes de iniciar el antiguo. El antiguo
utiliza su imagen, configuración y volumen anteriores; no conectarlo a la base
v3 nueva. Esta reversión pierde las vigilancias en memoria. El volumen nuevo se
conserva. El proveedor legado depende de que sus credenciales/sesión sigan vigentes:
health no garantiza que la reversión devuelva consultas GPS funcionales.

Para volver al oficial después de resolver la causa:

```bash
docker stop "$OLD_CONTAINER"
dc up -d --no-build
dc ps
```

No iniciar ambos ni eliminar volúmenes. Comprobar una consulta real tras cada cambio.

## 11. Qué sigue siendo una comprobación de desarrollo

| Comprobación | Cómo acreditarla |
|---|---|
| Límites de 300 s y doce horas, secuencias y carreras | Pruebas offline con relojes inyectados; no modificar el reloj de Oracle |
| Timeouts, respuestas inválidas, fallos SQLite y prioridad terminal | Transporte falso y bases temporales; no alterar credenciales reales |
| Exclusión entre procesos | Pruebas controladas en Linux sin autenticar otro adquirente |
| Fuera de orden, colisiones, deduplicación entre campañas | Fixtures y SQLite temporal; el tráfico real puede no presentar esos casos |
| Retención técnica de 30 días | Implementar fase 6 y probar umbrales con fechas sintéticas |
| Conservación de históricos y eventos | Prueba de que la limpieza técnica no borra campañas, observaciones, claves, asociaciones ni eventos |
| Marcas técnicas de idempotencia | La limpieza no debe borrar trabajo incompleto ni habilitar replay; validar antes de activarla |
| Secretos y reproducibilidad | Revisar diff/índice e imagen/configuración sin imprimir valores; registrar versión exacta |

La suite de fase 5 documenta 1022 pruebas, ejecutadas durante aquel cierre. Este
documento no las vuelve a ejecutar ni certifica aún la retención de fase 6.

## 12. Registro y criterio de cierre

Por cada caso anotar fecha, commit, ID de imagen, resultado esperado/observado,
evidencia mínima y estado: APROBADO, FALLIDO, NO EJECUTADO o NO OBSERVADO.
Evitar payloads, teléfonos, coordenadas y credenciales en la evidencia versionada.

Fase 6 se cierra cuando la retención está implementada y probada, la regresión
correspondiente pasa, la instalación Windows/Ubuntu tiene evidencia delimitada,
el respaldo/restauración y reversión están comprobados, y las pruebas operativas
acordadas se completan. Una limitación conocida debe quedar explícita; no marcar
entrega real de recuperación/llegada si solo se ejecutó una simulación.

Si aparecen errores terminales, reinicios continuos, permisos denegados, pérdida
inesperada de datos o envío a un destinatario incorrecto, detener la prueba, guardar
evidencia mínima y corregir antes de continuar. No reintentar en ráfaga ni borrar
el estado de adquisición para saltar el backoff.
