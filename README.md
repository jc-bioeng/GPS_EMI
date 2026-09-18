# GPS EMI — I1 e I2

Monitor de consola para **una ambulancia**, seleccionada por **placa o número de móvil**,
de Ambulancias Medellín y **un destino**.
Utiliza la pertenencia a geocercas reportada por WideTech en `Zones`: no calcula
distancias, no utiliza coordenadas para decidir llegadas y no garantiza posición actual.

I1 está implementado y validado manualmente contra GPSpace. I2 añade robustez de
ejecución continua: reintentos con backoff, continuidad por VEHID, validación de
timestamps y logging. Los errores de adquisición nunca son observaciones del móvil.

Destinos admitidos, por nombre exacto:

- `EMI Medellin_Poblado`
- `EMI_Medellin_Taller`

`ZONA 2 - POBLADO` no equivale a `EMI Medellin_Poblado`.

## Arquitectura

`WideTechClient → Vehicle → WatchRunner → ObservationValidator → ArrivalMonitor → ArrivalEvent → NotificationService → ConsoleNotifier`

El adaptador concentra autenticación, petición, parser y normalización. Devuelve
exclusivamente registros cuyo `fltName` sea `Ambulancias Medellin;44986;0`.
No se presupone un número de móviles ni de ambulancias. El dominio no conoce
HTTP, cookies ni canales de notificación. `NotificationService` es un protocolo
mínimo para añadir otro canal en el futuro sin alterar el monitor.
`find_vehicle` resuelve el identificador al iniciar. El runner coordina adquisición,
esperas y recuperación; `observation.py` valida el orden temporal y adapta la identidad
al monitor de I1. `ArrivalMonitor` conserva sus reglas deterministas y no contiene
HTTP, reintentos, relojes, esperas ni logging de infraestructura.

```text
src/gps_emi/
    __init__.py
    models.py
    config.py
    errors.py
    resolution.py
    cli.py
    providers/
        __init__.py
        widetech.py
    monitoring/
        __init__.py
        arrival.py
        observation.py
        runner.py
    notifications/
        __init__.py
        base.py
        console.py
tests/
    conftest.py
    test_arrival_monitor.py
    test_widetech_parser.py
    test_cli.py
    test_vehicle_resolution.py
    test_acquisition.py
    test_config.py
    test_observation.py
    test_runner.py
    fixtures/
        emi_amb20.json
gpspace_loaddatalog.py
pyproject.toml
pytest.ini
requirements.txt
```

## Entorno y configuración

Python 3.10 o posterior. Desde la raíz del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

En Ubuntu se utiliza `.venv/bin/python` en lugar del ejecutable de Windows.
Las dependencias de ejecución son `requests` y `python-dotenv`; las pruebas usan
`pytest`. No hay rutas específicas de Windows en el núcleo.

Variables, sin valores de credenciales:

- `GPSPACE_COOKIE`: requerida, desde el entorno del proceso o `.env` local.
- `GPSPACE_CONTENT_TYPE`: opcional; conserva la opción del prototipo para ajustar
  el Content-Type si cambia el comportamiento del endpoint.

La CLI carga únicamente `.env` del directorio de trabajo y no sobrescribe variables
ya definidas. Ejecutar desde la raíz. Importar el paquete no carga `.env`.
El adaptador usado directamente lee variables del proceso, no archivos.
`.env` está ignorado por Git. Nunca compartir su contenido, registrar headers
completos ni hacer dumps de peticiones autenticadas. No hay renovación de sesión.

## Ejecutar CLI

Modo interactivo:

```powershell
.\.venv\Scripts\python.exe gpspace_loaddatalog.py
```

La consola solicita `Placa o número de móvil:`. Con argumentos (sustituir el
identificador de ejemplo por una placa o número de móvil real de la flota):

```powershell
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --identifier AMB-20 --destination "EMI_Medellin_Taller" --interval 30
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --identifier DEU942 --destination "EMI Medellin_Poblado" --interval 30
```

Después de instalar el paquete también se puede ejecutar `gps-emi` o
`python -m gps_emi.cli` con los mismos argumentos. El script original ahora es una
entrada al monitor: ya no imprime el listado completo de vehículos y coordenadas.
`--plate` permanece como alias de `--identifier` para compatibilidad con I1.

Configuración de I2 (segundos, sin nuevas dependencias):

| Argumento | Campo de WatchConfig | Predeterminado |
| --- | --- | --- |
| `--interval` | `polling_interval` | 30 |
| `--initial-backoff` | `initial_backoff` | 5 |
| `--max-backoff` | `max_backoff` | 30 |
| `--stale-warning-seconds` | `stale_warning_seconds` | 300 |
| `--log-level` | Nivel de logging de la CLI | INFO |

Los intervalos deben ser finitos y positivos; el máximo debe ser al menos el
backoff inicial. El umbral STALE admite cero, pero no valores negativos ni infinitos.
Niveles admitidos: DEBUG, INFO, WARNING y ERROR. INFO muestra inicio, estados nuevos,
recuperación y llegada; un nivel superior oculta esos mensajes informativos.

```powershell
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --identifier AMB-20 --destination "EMI Medellin_Poblado" --interval 30 --initial-backoff 5 --max-backoff 30 --stale-warning-seconds 300 --log-level INFO
```

El modelo conserva los identificadores por separado con la correspondencia
empíricamente observada y utilizada actualmente por EMI/GPSpace:

| Campo WideTech | Campo Vehicle | Significado utilizado |
| --- | --- | --- |
| `VEHID` | `vehid` | Identificador del vehículo |
| `VEH_LCNS` | `mobile_number` | Número/código de móvil |
| `VEH_NAM` | `plate` | Placa física |

La validación manual del registro `VEHID=433909` devolvió `VEH_LCNS=AMB-20`
y `VEH_NAM=PJU886`. Operacionalmente, AMB-20 es el número de móvil y PJU886
es su placa. Esta evidencia respalda el mapping actual del adaptador, pero **no
constituye una garantía universal ni un contrato oficial de WideTech**.
Si falta un campo queda vacío; no se intercambian campos ni se deduce su significado
por el formato. `Vehicle` conserva además `gps_timestamp`, `location`, `speed`,
`ignition`, `gps_fix` y `zones`.

`find_vehicle(vehicles, identifier)` busca en ambos campos con `strip()` y
comparación sin distinción de mayúsculas. Recibe la lista ya filtrada por
`WideTechClient.get_vehicles()`; el filtro exacto de flota se mantiene. Cero
coincidencias informa que no se encontró el móvil; varias informa identificador
ambiguo y detiene la operación, incluso si coinciden campos distintos. Coincidir
en ambos campos del mismo vehículo cuenta una vez. No se prioriza placa sobre número.

La selección se resuelve antes de crear el monitor. Desde entonces se busca únicamente
el mismo `VEHID` dentro de la flota autorizada, aunque cambie la placa/número visible.
No se cambia a otro VEHID que reutilice el identificador inicial. Un VEHID ausente
al inicio o duplicado en una respuesta impide seleccionar una identidad segura y
termina la vigilancia con error.

`ArrivalMonitor` no cambia. La adaptación de `observation.py` comprueba el VEHID y
presenta la clave inicial a su interfaz heredada. La copia de entrada es privada;
el modelo resuelto y el evento conservan la placa y el número de móvil recibidos
en esa consulta. La consola usa el número si no hay placa disponible.

La primera lectura establece `OUTSIDE` o `INSIDE` y no produce evento. Solo una
transición observada `OUTSIDE → INSIDE` produce `ARRIVAL_DETECTED`. El notificador
muestra la llegada y la CLI termina. El monitor no vuelve a emitir eventos.
La placa o número de móvil se compara sin distinguir mayúsculas y quitando espacios exteriores;
no se eliminan guiones. Las geocercas se comparan exactamente.

## Polling, backoff y recuperación

El polling normal espera 30 segundos **después** de consultar y procesar una respuesta;
el tiempo HTTP se suma al ciclo. También se espera el intervalo normal cuando el
vehículo está disponible pero el timestamp no es nuevo o no se puede validar.

Un fallo recuperable genera WARNING y espera con backoff antes de la próxima
consulta: **5, 10, 20, 30, 30… segundos**. Se duplica la espera hasta el máximo
configurado; no se agrega además el intervalo normal. No hay límite de intentos
transitorios: puede seguir esperando hasta recuperación, error fatal o Ctrl+C.
El estado de `ArrivalMonitor` y el último timestamp procesado se conservan.

Al recuperar una adquisición con el vehículo vigilado disponible, se emite INFO,
`consecutive_failures` vuelve a cero y el próximo fallo vuelve al backoff inicial.
Se restaura el polling normal incluso si esa respuesta contiene un timestamp duplicado.

| Condición | Clasificación y acción |
| --- | --- |
| Timeout, ConnectionError, transferencia cortada o fallo de decodificación HTTP | Transitorio; backoff |
| HTTP 408, 429, 500, 502, 503, 504 | Transitorio; backoff |
| HTTP 200 con cuerpo vacío/blanco | Transitorio; backoff |
| VEHID ya resuelto ausente de la lista filtrada, incluida Rows vacía | Transitorio; backoff sin observar ni reiniciar el monitor |
| HTTP 401/403 o redirección 3xx | Sesión/autorización no utilizable; ERROR y finalización |
| Respuesta sin Rows con indicadores de login, password, Unauthorized o sesión expirada/inválida | Sesión no utilizable; ERROR y finalización |
| Configuración de autenticación ausente | ERROR y finalización |
| Otros HTTP, incluida respuesta 501/505 | No recuperable automáticamente; ERROR y finalización |
| Respuesta sin Rows no reconocida, Rows truncado o error de normalización | Formato no reconocido; ERROR y finalización |
| Otras excepciones de petición | No recuperable automáticamente; ERROR y finalización |
| Identificador inicial inexistente/ambiguo o VEHID ambiguo | ERROR y finalización |

Los indicadores de login son heurísticos del adaptador, no un contrato oficial:
solo se buscan cuando no hay Rows para no confundir texto válido de Location.
Una respuesta vacía o un formato desconocido no se diagnostican como sesión expirada
con certeza. No hay login automático, renovación de cookie ni navegador automatizado.
Un 403 también puede indicar falta de permisos; requiere intervención manual.

Un error fatal termina con código 1. Una llegada notifica una sola vez y termina
con código 0. Si falla la notificación, se termina sin reintentar para evitar un envío
duplicado. Ctrl+C durante la consulta, el polling o el backoff muestra
`Vigilancia cancelada.` (INFO) y termina sin traceback, código 130. Una nueva ejecución
comienza una vigilancia nueva, sin persistencia.

## Validación del reporte GPS

Se diferencia la hora de consulta del `gps_timestamp` reportado por el móvil.
`report_age = hora_de_consulta - gps_timestamp`, expresado en segundos.

- **STALE:** `report_age > stale_warning_seconds` (300 por defecto) produce WARNING.
  No descarta una observación nueva. La advertencia se emite una vez por timestamp,
  incluso si el reporte se vuelve antiguo durante consultas repetidas.
- **GPSFix=0:** WARNING diagnóstico, sin descartar ni cambiar el estado por sí mismo.
  No se atribuye un significado adicional a otros valores; se muestran como recibidos.
- **OUT_OF_ORDER:** timestamp menor que `last_processed_gps_timestamp`; WARNING,
  no entra al monitor y no cambia el último timestamp procesado.
- **DUPLICATE:** timestamp igual al último procesado, aunque Zones sea distinto;
  no entra al monitor ni genera transición. Solo se registra en DEBUG. Consultar
  cada 30 segundos no implica recibir un reporte GPS cada 30 segundos.
- **Timestamp ausente:** WARNING `MISSING_TIMESTAMP`; se espera otra consulta sin
  observar, porque no se puede saber si el reporte es nuevo.
- **Fechas con/sin zona incompatibles:** WARNING `TIMEZONE_MISMATCH`; no se comparan
  ni procesan como una observación nueva.

El timestamp se confirma únicamente después de pasar la observación al dominio.
Los diagnósticos repetidos del mismo reporte se limitan para no saturar la consola;
no se imprimen OUTSIDE/INSIDE por cada consulta duplicada.

El parser observado entrega fechas sin zona. El reloj local del equipo debe estar
sincronizado y usar la misma referencia horaria de esos reportes; I2 no inventa una
zona del proveedor. Si una fecha queda en el futuro respecto al reloj local, se
advierte, pero no se descarta automáticamente. Una fecha futura procesada puede
hacer que reportes posteriores parezcan fuera de orden hasta superar ese timestamp.

## Logging

Se usa `logging` estándar con un handler de consola en stdout, hora y nivel.
INFO incluye inicio, identificador resuelto, VEHID, placa/número, destino, estados
nuevos, recuperación, ARRIVAL_DETECTED y finalización. WARNING incluye errores
transitorios, STALE, GPSFix=0 y reportes no utilizables. ERROR indica finalización
por sesión o fallo no recuperable. DEBUG permite observar timestamps duplicados.
`ConsoleNotifier` también utiliza logging; no se crean archivos de logs.

No se registran cookies, headers completos, cuerpos de respuestas, Parameters,
tokens ni trazas de excepciones originales. Los errores de adquisición tienen
mensajes públicos controlados. La salida estándar permite capturarlos más adelante
sin modificar el dominio; no se incluye configuración de systemd en I2.

## Pruebas sin Internet

```powershell
.\.venv\Scripts\python.exe -m pytest
```

`pytest.ini` configura el directorio `src` y deshabilita `pytest-dotenv`.
Las pruebas bloquean las peticiones de red, conexiones de sockets y `time.sleep`,
eliminan las variables de autenticación heredadas y sustituyen la carga de `.env`.
El runner permite inyectar `sleep` y `now`; las pruebas usan esperas simuladas y reloj
fijo, sin esperar segundos reales. Los ejemplos de telemetría son sintéticos,
salvo `tests/fixtures/emi_amb20.json`, que contiene exclusivamente los cuatro valores
no sensibles observados: VEHID, VEH_LCNS, VEH_NAM y fltName. Sus pruebas verifican el
mapping y que buscar AMB-20 o PJU886 devuelva el mismo objeto Vehicle con VEHID 433909.
Los valores de prueba de autenticación se generan temporalmente en memoria;
no se almacenan cookies en fixtures. Se cubren las diez situaciones de aceptación,
coincidencia exacta, ausencia de duplicados, parser con Sensors anidados, HTML,
comillas, new Date, filtrado de flota, contrato HTTP, errores seguros y CLI. I2 añade
secuencias de recuperación, backoff, orden temporal, duplicados, calidad diagnóstica,
continuidad por VEHID, cancelación y ausencia de detalles sensibles en los logs.

## Endpoint observado y límites

GPSpace/WideTech utiliza un endpoint **interno/no documentado**:
`https://gpspace.app/EMI/ajax/Widetech.WEB.OnLine,Widetech.ashx`, con
`_method=LoadDataLog` y `_session=rw`. Se conservan el POST, los headers y el cuerpo
`Parameters` funcionales del prototipo. El valor opaco de `Parameters` permanece
dentro del adaptador por compatibilidad; no constituye un contrato oficial ni
reemplaza la autenticación. Cambios del proveedor pueden invalidarlo.
El timeout es de 60 segundos y las redirecciones se rechazan para evitar continuar
una consulta autenticada hacia otro destino.

El parser extrae campos sin ejecutar JavaScript. Conserva el formato observado
`new Date(año, mes desde cero, día, hora, minuto, segundo)` y conserva por separado
`VEH_LCNS` y `VEH_NAM`. Ignora campos anidados de Sensors al buscar claves del
vehículo y rechaza respuestas sin Rows o con Rows incompleto. No es un intérprete
general de JavaScript. Nuevos formatos de fechas necesitan muestras y pruebas;
una fecha no reconocida se muestra como no disponible. No se infiere zona horaria
para fechas que el proveedor entrega sin ella.

La consola muestra **última posición reportada**, fecha GPS y GPSFix para cada
observación nueva aceptada. Una transición entre reportes STALE cronológicamente
crecientes puede producir llegada: I2 advierte su antigüedad, no garantiza posición
actual. No se detectan entradas y salidas completas entre dos reportes adquiridos.
No hay persistencia ni múltiples vigilancias. Si cambia el VEHID asignado a una
ambulancia, no se adopta automáticamente la nueva identidad. La validación de I2
usa HTTP simulado; la prueba manual real corresponde al usuario con su sesión local.

La principal deuda sigue siendo la autenticación: la sesión/cookie se obtiene
externamente. Si expira, la vigilancia debe terminar para que el usuario la renueve
por fuera del programa. Los cambios de formato del endpoint interno y las diferencias
de reloj/zona horaria requieren validación adicional con evidencia del proveedor.

## Pendiente

I3: consulta UBICACION por placa o número. I4: WhatsApp. I5: despliegue VPS Ubuntu.
No están implementados. Tampoco se incluye renovación automática de autenticación,
persistencia, API, interfaz web, contenedores ni geocercas propias.
