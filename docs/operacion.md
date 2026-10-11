# Manual de operación

Revisión del 11 de octubre de 2026, reconciliada con fase 5 local. Estos comandos son instrucciones para el
operador; documentarlos no implica ejecutarlos ni certificar un despliegue.
Consultar [arquitectura](guia-del-sistema.md) y [estado de implementación](README.md).

## Entorno y configuración

El paquete requiere Python 3.10 o superior. Usar el entorno virtual del proyecto
y las dependencias declaradas en `pyproject.toml`; el contenedor tiene su propio
entorno. La CLI operacional y el servidor cargan la configuración local; la CLI
de sesiones no carga `.env` ni consulta GPSpace.

| Configuración | Finalidad |
| --- | --- |
| `GPSPACE_COOKIE` | Solo legado: sesión externa del portal |
| `WIDETECH_LOGIN`, `WIDETECH_PASSWORD` | Oficial: credenciales del método, sin valores en documentación |
| `WIDETECH_PLATE_FIELD`, `WIDETECH_MOBILE_FIELD` | Oficial: asignación obligatoria y complementaria de Movil/VEH_NAM |
| `WIDETECH_TIMEZONE` | Oficial: America/Bogota por defecto |
| `GPS_EMI_STATE_DIR` | Directorio absoluto de estado/exclusión, común a CLI y servidor |
| `GPSPACE_SESSION_INFO`, `GPSPACE_LOADDATALOG_STATE` | Insumos para generar Parameters dinámicos |
| `GPSPACE_CONTENT_TYPE` | Ajuste opcional del tipo de contenido |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | Envío por Cloud API |
| `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` | Verificación del webhook y firma |
| `WHATSAPP_ALLOWED_NUMBERS` | Remitentes admitidos |
| `WHATSAPP_API_VERSION` | Versión de API configurada |
| `WHATSAPP_ARRIVAL_MODE`, `WHATSAPP_ARRIVAL_TEMPLATE`, `WHATSAPP_TEMPLATE_LANGUAGE` | Modalidad y plantilla de llegada |
| `GPS_EMI_DATA_DB` | SQLite compartido por catálogo oficial/campañas; por defecto `data/gps_observations.db` |
| `GPS_EMI_COLLECTION_HEARTBEAT_SECONDS` | Compatibilidad heredada; no duplica reportes GPS en fase 4 |
| `LOG_LEVEL`, `GPS_EMI_LOG_SUMMARY_SECONDS` | Nivel y frecuencia de resúmenes; INFO y 300 s por defecto |

Los nombres no son credenciales. No copiar valores de sesión a documentación,
comandos compartidos ni Git. La autenticación del portal sigue siendo externa,
sin renovación automática. `--official` selecciona RenderExcel usando las
variables WIDETECH; sin esa opción se usa el legado. No hay fallback automático.
Los dos modos comparten Coordinator y su política de adquisición. En modo oficial,
el arranque prepara de forma aditiva las tablas catalog_* antes de adquirir.
Usar una ruta absoluta de GPS_EMI_DATA_DB común a CLI y servidor: su valor
predeterminado relativo conserva compatibilidad, pero depende del cwd.
Respaldar la base antes de una activación posterior. Este encargo solo migró bases
temporales de pruebas; no iniciar el servicio sobre la base operativa para probar.

## Consola y WhatsApp

Desde `C:\GPS_EMI`, con instalación y configuración existentes:

```powershell
.\.venv\Scripts\python.exe gpspace_loaddatalog.py
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --action location --identifier amb20
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --action site --site EMI_Medellin_Taller
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --action site --site "EMI Medellin_Poblado"
.\.venv\Scripts\python.exe -m gps_emi.whatsapp.server
```

Los comandos anteriores seleccionan el legado. Añadir `--official --interval 30`
a la CLI o al servidor para RenderExcel, con mapping obligatorio ya configurado.
Ejemplo sin datos operativos: `gps-emi --official --action location --identifier SYNTHETIC-MOBILE-A`.
Tras reinicio se espera el primer snapshot; la aplicación informa inicialización
y no presenta posiciones de SQLite como actuales. Consultas con caché muestran
su antigüedad. CLI y servidor requieren ejecución exclusiva en esa instalación:
ambos deben usar el mismo GPS_EMI_STATE_DIR, independiente del cwd. No hay IPC
ni coordinación con otras instalaciones/hosts. En modo oficial, las consultas
y el collector son nacionales de ambulancias; vigilancias siguen en Medellín.
Desaparición confirmada no equivale a baja o reclasificación; no introduce un
filtro nuevo de candidatos. La reclasificación confirmada termina internamente
la vigilancia sin notificación proactiva. No se restauran vigilancias ni posiciones.

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

## Continuidad y vencimiento de vigilancias

CLI y servidor aceptan `--watch-inactivity-seconds 43200`: positivo y finito,
predeterminado doce horas. Se aplica al iniciar el proceso; no cambia .env.
El origen es el alta local y después cada GPS nuevo y fresco aceptado, medido
con reloj monotónico. Datos iniciales antiguos/ausentes no vencen retroactivamente.
Se vence al **superar**, no igualar, el límite efectivo. Causa interna inactivity;
no se incorpora un nuevo aviso WhatsApp de finalización.

GPS de más de 300 segundos no puede causar llegada ni renovar actividad.
`--stale-warning-seconds` solo ajusta la advertencia, no esa barrera de seguridad.
A los 300 segundos sin actividad empieza interrupción individual. Tres GPS nuevos
y frescos en una misma sede confirman presencia, avisan una vez y terminan. Un
exterior fresco devuelve al seguimiento normal. No se afirma hora de llegada.

Fallos recuperables de adquisición y persistencia local pausan el vencimiento
hasta publicar un snapshot válido, sin cambiar su categoría ni atribuir caída
al proveedor. Repetir GPS no pausa. Errores terminales prevalecen. Mientras un
intento está pendiente se difiere la decisión de vencer hasta conocer su resultado;
no se añade HTTP ni un límite alternativo de pausa. Campañas conservan su fin original.

La presencia confirmada se envía como texto específico por Messenger, también en
modo de llegada template. Si la ventana está cerrada, queda fallida y no se
reintenta ni se sustituye por la plantilla de llegada. Aceptación no es entrega.
Estado, contabilidad y evidencia: [fase 5](widetech-official-phase5.md).

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
offset y se aplican a la primera recepción en esa campaña (session_received_at),
no al timestamp GPS. La exportación global sigue filtrando acquired_at.

Fase 4 migra SQLite de forma aditiva a user_version=3. Los binarios anteriores
pueden rechazar ese esquema: no basta con revertir la imagen. Respaldar antes de
migrar mediante la API backup de SQLite o escritores detenidos; comprobar el
respaldo con su binario compatible. Para revertir, detener escritores, preservar
la base v3 y restaurar una copia previa verificada con el binario anterior. Los
datos posteriores permanecen en la copia v3 para revisión; no reducir user_version
ni borrar columnas para forzar compatibilidad. Este encargo solo usó bases temporales.

Reiniciar conserva el plazo original y registra una ventana de interrupción;
no recupera muestras perdidas. Una escritura admitida antes del cierre termina
sin prolongar la campaña; un lote solo encolado se revalida al iniciar escritura. La sesión
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
y persiste SQLite y `/data/state/acquisition.lock`. Docker configura
`GPS_EMI_STATE_DIR=/data/state`; la imagen prepara /data para UID/GID 10001
con modo 700. Volúmenes previos/bind mounts requieren permisos adecuados
preparados por el administrador. La aplicación no eleva privilegios ni cambia
de lock ante permisos insuficientes. El plazo de próxima adquisición persiste
al reiniciar; no borrar el lock para saltar la espera.
El puerto se liga a `127.0.0.1:8000`. Los logs json-file rotan
a 10 MB y tres archivos. El cierre dispone de 15 segundos de gracia, con esperas
internas acotadas; un HTTP en curso no es cancelable instantáneamente.

Editar código local no actualiza una imagen en ejecución: reconstruir y recrear
cuando corresponda. Reiniciar pierde vigilancias, conversaciones y selecciones,
aunque conserva campañas y datos en el volumen. No usar `down -v` si se deben
conservar datos. Este contenedor no proporciona por sí solo dominio, HTTPS ni
administración de VPS.

La validación real de fase 2 en Docker/Ubuntu sigue pendiente: el último intento
de consultar Docker no encontró el motor Linux. No se verificó UID 10001,
permisos POSIX, persistencia de volumen ni flock en contenedor. El CMD existente
no activa `--official`; activar el modo es una operación explícita posterior.

Para respaldar SQLite, usar su API de backup o una copia consistente con escritores
detenidos. Copiar únicamente el archivo `.db` mientras WAL está activo puede
omitir datos. Guardar respaldos fuera de Git, restringir su acceso y comprobar
restauración antes de migraciones. No hay backup automático ni cifrado añadido
por el programa. Un rollback de imagen no garantiza reversión del esquema.

## Diagnóstico

| Síntoma | Interpretación y revisión |
| --- | --- |
| `SESSION_EXPIRED` (legado) | Renovar autenticación externamente; reiniciar y recrear vigilancias fallidas |
| `INITIALIZING` | Todavía no hay publicación inicial |
| `READY` / `RECOVERING` | Publicación disponible; recuperación reduce gradualmente el backoff |
| `UNAVAILABLE` | Último intento global fallido; conservar snapshot anterior y su edad |
| `BLOCKED_METHOD` | Fallo terminal de autenticación/autorización/configuración o funcional; requiere intervención, no implica caída general de WideTech |
| `STOPPED` | Autoridad detenida; no admite adquisiciones |
| Categoría `persistence` | SQLite impidió persistir el catálogo; se conserva el snapshot anterior y se reinicia la secuencia provisional de ausencias |
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
Fase 2 registra 919 tests anteriores y 933 tras cerrar los dos hallazgos.
La [especificación de fase 2](widetech-official-phase2-spec.md) separa la regresión
ejecutada para este commit y las pruebas CLI reportadas por el usuario el
9 de octubre. La [fase 3](widetech-official-phase3.md) registra su propia ejecución
offline y migraciones temporales. Revisar por separado pruebas offline, aceptación externa y despliegue.

Excluir secretos, SQLite, CSV, logs, caches y artefactos de prueba. Preservar
cambios locales ajenos al incremento. `.codemapignore` procede del uso de Codemap
en WSL para excluir artefactos, especialmente `.pytest_cache`; no es una
dependencia de ejecución y su versionado requiere una decisión separada.
