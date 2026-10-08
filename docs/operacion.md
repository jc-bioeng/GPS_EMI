# Manual de operación

Revisión del 8 de octubre de 2026. Estos comandos son instrucciones para el
operador; documentarlos no implica ejecutarlos ni certificar un despliegue.
Consultar [arquitectura](guia-del-sistema.md) y [estado de implementación](README.md).

## Entorno y configuración

El paquete requiere Python 3.10 o superior. Usar el entorno virtual del proyecto
y las dependencias declaradas en `pyproject.toml`; el contenedor tiene su propio
entorno. La CLI operacional y el servidor cargan la configuración local; la CLI
de sesiones no carga `.env` ni consulta GPSpace.

| Configuración | Finalidad |
| --- | --- |
| `GPSPACE_COOKIE` | Sesión externa del portal |
| `GPSPACE_SESSION_INFO`, `GPSPACE_LOADDATALOG_STATE` | Insumos para generar Parameters dinámicos |
| `GPSPACE_CONTENT_TYPE` | Ajuste opcional del tipo de contenido |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | Envío por Cloud API |
| `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` | Verificación del webhook y firma |
| `WHATSAPP_ALLOWED_NUMBERS` | Remitentes admitidos |
| `WHATSAPP_API_VERSION` | Versión de API configurada |
| `WHATSAPP_ARRIVAL_MODE`, `WHATSAPP_ARRIVAL_TEMPLATE`, `WHATSAPP_TEMPLATE_LANGUAGE` | Modalidad y plantilla de llegada |
| `GPS_EMI_DATA_DB` | SQLite, por defecto `data/gps_observations.db` |
| `GPS_EMI_COLLECTION_HEARTBEAT_SECONDS` | Persistencia periódica de datos idénticos; 300 s por defecto |
| `LOG_LEVEL`, `GPS_EMI_LOG_SUMMARY_SECONDS` | Nivel y frecuencia de resúmenes; INFO y 300 s por defecto |

Los nombres no son credenciales. No copiar valores de sesión a documentación,
comandos compartidos ni Git. La autenticación del portal sigue siendo externa,
sin renovación automática. Las credenciales del adaptador oficial aislado se
entregan mediante su configuración explícita; aún no hay un cambio de proveedor
operacional mediante estas variables.

## Consola y WhatsApp

Desde `C:\GPS_EMI`, con instalación y configuración existentes:

```powershell
.\.venv\Scripts\python.exe gpspace_loaddatalog.py
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --action location --identifier amb20
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --action site --site EMI_Medellin_Taller
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --action site --site "EMI Medellin_Poblado"
.\.venv\Scripts\python.exe -m gps_emi.whatsapp.server
```

Las comillas de Poblado son necesarias por el espacio. Ctrl+C detiene el proceso.
No lanzar otra instancia sobre el mismo puerto. La CLI usa los nombres exactos
de sede; los atajos conversacionales se interpretan en WhatsApp.

MENU presenta opciones numéricas: 1 vigilar, 2 ubicación, 3 sede, 4 ayuda y
5 gestionar vigilancias. VIGILANCIAS ofrece 1 nueva, 2 listar, 3 detener y
4 menú principal. También se pueden escribir `UBICACION amb20`, `VIGILAR AMB-20`
y `SEDE TALLER`. Ante ambigüedad, responder al número de la lista vigente.

Si el móvil ya está dentro, el aviso inicial describe esa situación y ofrece
cancelar; no constituye una llegada. Mantenerla requiere observar una salida
antes de una futura entrada. `DETENER` permite escoger una vigilancia propia.
Un envío aceptado por Meta no prueba recepción en el teléfono.

## Sesiones de recolección

El servidor debe estar activo y apuntar a la misma base que estos comandos:

```powershell
$env:GPS_EMI_DATA_DB = 'C:\GPS_EMI\data\gps_observations.db'
.\.venv\Scripts\python.exe -m gps_emi.collector start --duration 24h
.\.venv\Scripts\python.exe -m gps_emi.collector status
.\.venv\Scripts\python.exe -m gps_emi.collector stop
.\.venv\Scripts\python.exe -m gps_emi.collector export --session ID_MOSTRADO --output observations-session.csv
```

Son ejemplos independientes del ciclo de vida: `stop` termina anticipadamente
la sesión activa. `--db RUTA`, antes del subcomando, sustituye la variable.
Solo hay una campaña activa por base. `status` puede crear/migrar el esquema y
reconocer expiraciones; el exportador abre la base en lectura y exige destino
nuevo. Los filtros `--from` inclusivo y `--to` exclusivo requieren fecha ISO con
offset y se aplican a la adquisición, no al timestamp GPS.

Reiniciar conserva el plazo original y no recupera muestras perdidas. La sesión
COLLECTING no garantiza que el proveedor esté respondiendo: revisar logs y
conteos. Ver [sesiones](collection-sessions.md) para ejemplos Docker y exportación
de datos históricos sin sesión.

## Docker y almacenamiento

Con Docker Desktop y motor Linux disponibles, desde el repositorio en Windows:

```powershell
docker compose --env-file NUL build
docker compose --env-file NUL up -d
docker compose --env-file NUL ps
Invoke-RestMethod http://127.0.0.1:8000/health
docker compose --env-file NUL logs --tail 100 gps-emi
docker compose --env-file NUL exec -T gps-emi python -m gps_emi.collector status
```

En Linux se utiliza `/dev/null` en lugar de `NUL`. Esta opción evita la carga para
interpolación de Compose; el `env_file` del servicio sigue inyectando su
configuración. No publicar una salida de configuración expandida ni de inspección
del entorno. Los logs son para revisión local, no un volcado para compartir.

La imagen ejecuta como UID/GID 10001. El volumen `gps-observations` monta `/data`
y persiste SQLite; el puerto se liga a `127.0.0.1:8000`. Los logs json-file rotan
a 10 MB y tres archivos. El cierre dispone de 15 segundos de gracia, con esperas
internas acotadas; un HTTP en curso no es cancelable instantáneamente.

Editar código local no actualiza una imagen en ejecución: reconstruir y recrear
cuando corresponda. Reiniciar pierde vigilancias, conversaciones y selecciones,
aunque conserva campañas y datos en el volumen. No usar `down -v` si se deben
conservar datos. Este contenedor no proporciona por sí solo dominio, HTTPS ni
administración de VPS.

Para respaldar SQLite, usar su API de backup o una copia consistente con escritores
detenidos. Copiar únicamente el archivo `.db` mientras WAL está activo puede
omitir datos. Guardar respaldos fuera de Git, restringir su acceso y comprobar
restauración antes de migraciones. No hay backup automático ni cifrado añadido
por el programa. Un rollback de imagen no garantiza reversión del esquema.

## Diagnóstico

| Síntoma | Interpretación y revisión |
| --- | --- |
| `SESSION_EXPIRED` | Renovar autenticación externamente; reiniciar y recrear vigilancias fallidas |
| Errores de red | Revisar conectividad y backoff, sin asumir que el móvil salió de sede |
| Respuesta vacía o malformada | Revisar categoría del proveedor; no equivale a flota vacía válida |
| STALE o DUPLICATE | Posición antigua o ya procesada; no implica movimiento nuevo |
| COLLECTING sin muestras | Revisar proveedor, ruta SQLite compartida, permisos y cola |
| Fallos SQLite | Revisar espacio, permisos y competencia de escritores; puede haber pérdida de muestras |
| Meta acepta pero no llega | Aceptación no confirma entrega; revisar ventana y configuración de plantilla |
| Health responde pero no hay GPS | Health es liveness local, no prueba de dependencias |

## Validación antes de otro commit

```powershell
.\.venv\Scripts\python.exe -m pytest
git diff --check
git status --short
```

Las pruebas usan datos sintéticos y no deben consultar servicios reales. La
[fase 1 oficial](widetech-official-phase1.md) registra su validación de 892 tests
y el entorno alternativo utilizado; no confundir esa ejecución con una nueva.
Revisar por separado pruebas offline, aceptación externa y estado desplegado.

Excluir secretos, SQLite, CSV, logs, caches y artefactos de prueba. Preservar
cambios locales ajenos al incremento. `.codemapignore` procede del uso de Codemap
en WSL para excluir artefactos, especialmente `.pytest_cache`; no es una
dependencia de ejecución y su versionado requiere una decisión separada.
