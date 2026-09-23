# GPS EMI — I1, I2, I3 y piloto WhatsApp I4-P

Consola para vigilar la llegada a EMI de **una ambulancia**, consultar su última
ubicación por **placa o número de móvil**, o listar ambulancias por sede.
Utiliza la pertenencia a geocercas reportada por WideTech en `Zones`: no calcula
distancias, no utiliza coordenadas para decidir llegadas y no garantiza posición actual.

I1 está implementado y validado manualmente contra GPSpace. I2 añade robustez de
ejecución continua: reintentos con backoff, continuidad por VEHID, validación de
timestamps y logging. Los errores de adquisición nunca son observaciones del móvil.
I3 añade el menú operacional, consultas puntuales y vigilancia de EMI como unión
de Poblado y Taller. Las consultas conservan la última información reportada;
no garantizan ubicación física actual.

Destinos admitidos, por nombre exacto:

- `EMI Medellin_Poblado`
- `EMI_Medellin_Taller`

`ZONA 2 - POBLADO` no equivale a `EMI Medellin_Poblado`.

## Arquitectura

`WideTechClient → Vehicle → WatchRunner → ObservationValidator → ArrivalMonitor → ArrivalEvent → NotificationService → ConsoleNotifier`

La CLI coordina entrada/salida y llama a `watch_arrival`, `get_vehicle_location`
o `list_vehicles_at_site`. Las dos consultas usan `WideTechClient`, el resolver
existente y `ObservationValidator`, y devuelven `LocationResult` o `SiteResult`.
`formatting.py` convierte esos resultados en texto sin HTTP ni reglas de selección.
`sites.py` centraliza los dos nombres exactos. Los casos de uso no necesitan
`input()` ni `print()` y pueden reutilizarse desde otro canal.

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
    sites.py
    queries.py
    formatting.py
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
    test_emi_arrival.py
    test_queries.py
    test_formatting.py
    test_menu.py
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
Las dependencias de ejecución son `requests`, `python-dotenv`, `Flask`, `waitress`
y `tzdata` (base IANA para `zoneinfo`, necesaria en Windows o sistemas sin ella).
`requirements.txt` incluye `requirements-runtime.txt`, con versiones exactas de
dependencias directas y transitivas. Para desarrollo y pytest instala en su lugar
`requirements-dev.txt`; no se necesita pytest en runtime. `pyproject.toml` mantiene
rangos de compatibilidad; usa los requirements para reproducir las versiones
validadas y actualízalos juntos tras ejecutar la suite. Python mínimo: 3.10.
No hay rutas específicas de Windows en el núcleo.

En Linux, instalación de runtime:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-runtime.txt
.venv/bin/python -m pip install --no-deps .
```

Para desarrollo: `python -m pip install -r requirements-dev.txt` seguido de
`python -m pip install --no-deps -e .`, usando el Python del entorno.
Los requirements fijan dependencias de aplicación; la versión de Python y la
herramienta de build de la futura imagen deberán fijarse al preparar Docker.

Variables, sin valores de credenciales:

- `GPSPACE_COOKIE`: requerida, desde el entorno del proceso o `.env` local.
- `GPSPACE_SESSION_INFO`: JSON obligatorio con `UID` y `UNAME` de la sesión
  actual. Conserva el tipo JSON de UID (texto o entero); UNAME es texto.
- `GPSPACE_LOADDATALOG_STATE`: JSON obligatorio con los siete campos de estado
  indicados abajo, conservando sus valores y tipos observados. No tiene defaults.
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

Sin argumentos se muestra:

```text
1. Vigilar llegada a EMI
2. Consultar ubicación de ambulancia
3. Ver ambulancias en sede
0. Salir
```

Las opciones 1 y 2 solicitan `Placa o número de móvil:`. Solo la opción 3 solicita
sede (1: Poblado, 2: Taller). Una selección inválida permite reintentar. Al completar
una operación correctamente se vuelve al menú. Salir con 0 no carga configuración
de autenticación ni consulta GPSpace. Ctrl+C termina con código 130.

Con argumentos se ejecuta una sola operación y se termina:

```powershell
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --identifier AMB-20 --interval 30
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --action location --identifier AMB-20
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --action location --identifier PJU886
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --action site --site "EMI Medellin_Poblado"
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --action site --site "EMI_Medellin_Taller"
```

Después de instalar el paquete también se puede ejecutar `gps-emi` o
`python -m gps_emi.cli` con los mismos argumentos. El script original ahora es una
entrada a la consola: no imprime coordenadas ni el listado completo de la flota.
`--plate` permanece como alias de `--identifier` para compatibilidad con I1.
`--identifier` sin `--action` inicia vigilancia de la unión EMI sin pedir sede.
`--action watch` permite indicar esa operación explícitamente.
`--destination` se conserva temporalmente como opción **obsoleta**, con WARNING:
si se proporciona, mantiene la vigilancia de una sola sede de I1/I2. Es una excepción
de compatibilidad al nuevo comportamiento agregado; el menú nunca solicita destino.
Los argumentos de polling, backoff y logging siguen disponibles. Las consultas
puntuales solo utilizan el umbral STALE; no hacen polling ni reintentos automáticos.

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
.\.venv\Scripts\python.exe gpspace_loaddatalog.py --identifier AMB-20 --interval 30 --initial-backoff 5 --max-backoff 30 --stale-warning-seconds 300 --log-level INFO
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

La adaptación de `observation.py` comprueba el VEHID y
presenta la clave inicial a su interfaz heredada. La copia de entrada es privada;
el modelo resuelto y el evento conservan la placa y el número de móvil recibidos
en esa consulta. La consola usa el número si no hay placa disponible.

En I3, EMI significa `EMI Medellin_Poblado OR EMI_Medellin_Taller`. La primera
lectura establece `OUTSIDE_EMI` o `INSIDE_EMI` y no produce evento. Solo una transición
observada `OUTSIDE_EMI → INSIDE_EMI` produce `ARRIVAL_DETECTED`. Taller → Poblado
y Poblado → Taller sin observación exterior intermedia permanecen dentro de EMI:
no son nuevas llegadas. Salir de ambas y volver a cualquiera produce una llegada.
El notificador muestra la sede detectada y la vigilancia finaliza. El monitor
no vuelve a emitir eventos. El modo histórico con destino explícito mantiene
los estados `OUTSIDE`/`INSIDE` y sus reglas anteriores.

`ArrivalEvent` conserva `vehicle`, `destination` y `event_type`, y añade `sites`
(tupla de sedes exactas detectadas) y la propiedad `site` para una sola sede.
Normalmente `destination` y `site` contienen el nombre exacto de la sede de llegada.
Si un reporte contiene ambas sedes, se conservan ambas en orden Poblado/Taller,
`destination` muestra ambas y `site` es `None`: no se inventa una sede física única.
La placa o número de móvil se compara sin distinguir mayúsculas y quitando espacios exteriores;
no se eliminan guiones. Las geocercas se comparan exactamente.

## Consultar ubicación y ambulancias en sede

Cada operación realiza **una adquisición LoadDataLog**, sin monitor, bucle, espera
ni reintento automático. El cliente conserva el filtro exacto de Ambulancias Medellín.
La consulta individual reutiliza `find_vehicle`: AMB-20 y PJU886 resuelven el mismo
vehículo del fixture observado. Un identificador inexistente o ambiguo da un error
claro; en el menú permite volver a elegir. Los errores de adquisición se comunican
sin detalles sensibles y terminan con código 1; un fallo transitorio invita a consultar
de nuevo, sin simular recuperación automática.

`LocationResult` contiene `vehicle`, `queried_at`, `assessment`, `stale`, y expone
`report_age` numérico y `movement`. La salida muestra número de móvil, placa,
Location original, hora GPS, antigüedad, velocidad numérica y humana, ignición y GPSFix.
Location no se sustituye por el nombre de una sede, incluso cuando Zones contiene EMI.
No se muestran campos de latitud/longitud.

- Velocidad 0: **Detenida**; mayor que 0: **En movimiento**. No se asume cero
  si falta. Valores negativos no reciben una categoría de movimiento inventada.
- Ignición 0/1: **Apagada/Encendida**; otros valores: **N/D**.
- Antigüedad: `43 s → hace 43 s`, `125 s → hace 2 min`, `786 s → hace 13 min`,
  `7200 s → hace 2 h`. Se conserva el valor numérico sin redondear para decisiones.
- STALE reutiliza exactamente `report_age > stale_warning_seconds` de I2 (300 s
  por defecto). No oculta Location ni descarta vehículos. GPSFix=0 se conserva
  con advertencia diagnóstica, sin invalidar automáticamente la posición.
- Datos faltantes: **N/D**. Si falta el timestamp o no es comparable, la antigüedad
  y el estado de frescura quedan desconocidos (`stale=None`). Una fecha futura
  muestra una advertencia de reloj, sin cambiar la política temporal de I2.

`SiteResult` contiene `site`, `queried_at` y una tupla `entries` de `LocationResult`.
Una única adquisición construye toda la lista, sin peticiones por ambulancia.
La pertenencia exige que `Zones` contenga el nombre exacto elegido; `ZONA 2 - POBLADO`
por sí sola no basta. La tabla muestra móvil, placa, velocidad/movimiento, antigüedad
y GPSFix. Su significado es **ambulancias cuya última posición reportada pertenece
a esta geocerca**, no presencia física actual garantizada.

Orden: reportes no STALE primero, del más reciente al más antiguo; después STALE
en el mismo orden; timestamps ausentes/no comparables al final. Los empates se
resuelven por número de móvil, placa (sin distinguir mayúsculas) y VEHID.
Los STALE permanecen visibles y etiquetados. Una lista vacía se informa explícitamente.

## Polling, backoff y recuperación

Esta sección corresponde exclusivamente a la vigilancia continua.

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

Un error fatal termina con código 1. Una llegada notifica una sola vez y completa
la operación con código 0 (en modo interactivo vuelve al menú). Si falla la notificación,
se termina sin reintentar para evitar un envío
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

El parser conserva `Fecha` de GPSpace (`new Date(...)`) sin offset ni conversión.
`clock.operational_now()` obtiene explícitamente la hora de `America/Bogota` con
`zoneinfo` y entrega hora de pared naive para mantener esa representación.
Es la referencia operativa EMI, no una garantía universal de WideTech. No se usa
`vehDateTimeUTC` para reinterpretar `Fecha`. La timezone del host no afecta
report_age, STALE ni el orden temporal; su reloj sí debe estar sincronizado.
El evaluador conserva el umbral estricto `report_age > threshold`, duplicados,
fuera de orden y rechazo de mezclas naive/aware. Si una fecha queda en el futuro
respecto al reloj operativo, se
advierte, pero no se descarta automáticamente. Una fecha futura procesada puede
hacer que reportes posteriores parezcan fuera de orden hasta superar ese timestamp.

## Logging

Se usa `logging` estándar con un handler en stdout, fecha/hora ISO con offset de
Bogotá y nivel. Código y mensajes son Unicode; usar UTF-8 en stdout/stderr del
runtime Linux (por ejemplo `PYTHONUTF8=1` si el entorno impone otro encoding).
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
I3 añade las transiciones de la unión EMI y entre sedes, sede del evento, recuperación
en modo agregado, consultas por ambos identificadores, una sola adquisición por
operación, umbral STALE compartido, orden y permanencia de STALE, datos incompletos,
formato humano, menú y compatibilidad CLI.

## Endpoint observado y límites

GPSpace/WideTech utiliza un endpoint **interno/no documentado**:
`https://gpspace.app/EMI/ajax/Widetech.WEB.OnLine,Widetech.ashx`, con
`_method=LoadDataLog` y `_session=rw`. Se conservan el POST y los headers.
`Parameters` ahora se genera en cada consulta: sesión/estado explícitos → dict
en el orden observado → JSON compacto UTF-8 → XOR y rotación circular de tres
bits → Base64 URL-safe sin padding → cuerpo `Parameters=<generado>`.
UID alimenta `strUserID`; UNAME se utiliza solo como clave de ofuscación
(si es explícitamente vacío, se usa `wtApi`, como en el JavaScript suministrado).
No queda fallback al valor opaco anterior. Esto reproduce el código observado,
no constituye un contrato oficial ni reemplaza la autenticación.
Cambios del proveedor pueden invalidarlo.
El timeout es de 60 segundos y las redirecciones se rechazan para evitar continuar
una consulta autenticada hacia otro destino.

Los campos `intLastUpdate`, `intTimer`, `strMobiles`, `intConsoleType`, `idFleet`,
`intFrom` y `strOriginQuery` no tenían valores independientes recuperables en el
código anterior. Deben configurarse explícitamente a partir del cliente oficial;
no se infiere su semántica ni se presupone que `idFleet` sea `44986`.
`bolAddDriver` es siempre `true`, según el código suministrado. El filtro posterior
sigue siendo exactamente `fltName == "Ambulancias Medellin;44986;0"`.
El estado configurado se reutiliza sin avanzar cursores ni deducir incrementales.
Debe validarse manualmente que corresponde a una consulta con todos los vehículos
necesarios. Se preservan texto, enteros seguros de JavaScript, booleanos y null;
se rechazan fracciones, objetos y listas hasta disponer de evidencia para ellos.
La configuración inválida falla antes del POST con un error no recuperable y sin
mostrar sus valores. Importar o construir el cliente no lee esa configuración.

### Prueba manual de Parameters dinámico

Aceptación manual reportada el **19/09/2026** contra GPSpace/WideTech real con
una sesión autenticada: generación dinámica de `Parameters` validada mediante
`--action location --identifier AMB-20` y los inventarios de
`EMI_Medellin_Taller` y `"EMI Medellin_Poblado"`. Se conservaron móvil/placa,
ubicación, timestamp GPS, antigüedad/STALE y GPSFix; la consulta individual mostró
velocidad/movimiento e ignición correctos y los inventarios conservaron el orden
temporal. Deben usarse los nombres exactos de geocerca y comillas si contienen
espacios. Esta aceptación no valida autenticación automática.

La cookie y la autenticación siguen siendo externas/manuales. No hay login
automático, renovación automática de sesión ni bypass de Turnstile. Una API o
autenticación soportada por WideTech sigue siendo la solución futura preferida.
Pasar pytest por sí solo no valida la sesión ni la integración real.

1. Iniciar sesión normalmente en GPSpace. En DevTools → Sources, localizar la
   llamada `wtApi.ObfuscateString(JSON.stringify(Parameters), ...)` y colocar un
   breakpoint después de construir `Parameters`, antes de ofuscarlo. Esperar una
   consulta normal de la página y seleccionar ese frame cuando se detenga.
2. Desde la consola de ese frame copiar únicamente la configuración necesaria
   al portapapeles, sin imprimirla. Primero ejecutar:

   ```javascript
   copy(JSON.stringify({UID: wtApi.SesInfo.UID, UNAME: wtApi.SesInfo.UNAME}))
   ```

   En la misma ventana PowerShell que se usará para la prueba, ejecutar:

   ```powershell
   $env:GPSPACE_SESSION_INFO = Get-Clipboard -Raw
   ```

   Después, volver al frame detenido en DevTools y ejecutar:

   ```javascript
   copy(JSON.stringify({intLastUpdate: Parameters.intLastUpdate, intTimer: Parameters.intTimer, strMobiles: Parameters.strMobiles, intConsoleType: Parameters.intConsoleType, idFleet: Parameters.idFleet, intFrom: Parameters.intFrom, strOriginQuery: Parameters.strOriginQuery}))
   ```

   En PowerShell, ejecutar y después reanudar la página:

   ```powershell
   $env:GPSPACE_LOADDATALOG_STATE = Get-Clipboard -Raw
   Set-Clipboard -Value ''
   ```

   Estos snippets solo copian datos existentes: no realizan consultas adicionales.
3. Conservar `GPSPACE_COOKIE` vigente en la configuración local por el procedimiento
   manual existente. Las dos variables anteriores duran esa sesión PowerShell,
   prevalecen sobre `.env` y evitan transformar el JSON mediante interpolación de
   dotenv. No compartir estos valores ni incorporarlos al repositorio.
4. Desde PowerShell, en `C:\GPS_EMI`, ejecutar una consulta de ubicación:

   ```powershell
   .\.venv\Scripts\python.exe gpspace_loaddatalog.py --action location --identifier AMB-20
   ```

   Comprobar la identificación y la posición reportada, incluyendo fecha GPS y
   STALE. Esta operación realiza una adquisición; no inicia vigilancia continua.
   Un error de configuración exige revisar los JSON; un error de sesión exige
   renovar manualmente la cookie y los datos de sesión. No hacer dumps de requests.

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
usa HTTP simulado, al igual que I3; la prueba manual real corresponde al usuario con su sesión local.

La principal deuda sigue siendo la autenticación: la sesión/cookie se obtiene
externamente. Si expira, la vigilancia debe terminar para que el usuario la renueve
por fuera del programa. Los cambios de formato del endpoint interno y las diferencias
de reloj/zona horaria requieren validación adicional con evidencia del proveedor.

## Piloto I4-P — WhatsApp Cloud API

El emisor es **el número de prueba de Meta**. El celular institucional de Biomédica
es el destinatario de prueba y usuario autorizado. **No registrar ni migrar ese
celular institucional como emisor.** I4-P es un piloto local, no el I4 definitivo.

Se conservan los valores recibidos: `MOVIL- 96` no se convierte en `AMB-96`.
El mapping de identificadores sigue siendo el empíricamente observado para EMI,
no una garantía universal de WideTech.

### Arquitectura y ejecución

```text
Meta → Flask /webhook → firma + extracción + Inbox/deduplicación → HTTP 200
                                            │
                                  worker secuencial de mensajes
                                            │
                         autorización → Conversation/parser
                                            │
                    ┌───────────────────────┼────────────────────┐
             get_vehicle_location   list_vehicles_at_site   WatchManager
                    │                       │                    │
                LocationResult          SiteResult         hilo único
                    │                       │                    │
                    └────── formatters ─────┘           FleetPolling (1 snapshot)
                                  │                     N Watches / N monitores
                                  │                          ArrivalEvents
                              Messenger                          │
                                  │                       WhatsAppNotifier
                                  └──────── WhatsAppClient ──────┘
                                            │
                                      Meta Graph API
```

Flask aporta únicamente las dos rutas y un cliente de pruebas sin sockets.
Waitress sirve WSGI en Windows con un proceso, sin debugger ni reloader; no se usa
el servidor de desarrollo de Flask para el túnel. Ver la
[guía oficial Flask/Waitress](https://flask.palletsprojects.com/en/stable/deploying/waitress/).

Los módulos están en `src/gps_emi/whatsapp/`: `config.py`, `client.py`, `delivery.py`,
`webhook.py`, `worker.py`, `routing.py`, `service.py`, `formatting.py`, `notifier.py`
y `server.py`. Los tests están en `tests/whatsapp/`.

### Interfaz WhatsApp

`MENU`, `MENÚ` e `INICIO` envían una lista nativa con el encabezado
«🚑 GPS EMI — Biomédica», la pregunta «¿Qué deseas hacer?» y el botón
«Ver opciones». Sus filas son Vigilar llegada, Consultar ubicación,
Ver ambulancias en sede, Ayuda y Gestionar vigilancias. `menu.py` centraliza los IDs estables y el
payload; las respuestas `button_reply` y `list_reply` se convierten a comandos
del mismo flujo existente, sin depender del título visible. Los números 1–4
y los comandos de texto siguen funcionando. Se utiliza lista porque los reply
buttons admiten hasta tres opciones ([referencia de Meta](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/messages/interactive/)).

Ubicación y sede envían un único «🔎 Consultando ...» desde el worker antes de
consultar GPSpace, seguido del resultado o error. No hay nuevos hilos; si hay
trabajo previo en la cola, el feedback espera su turno. Un fallo de envío del
feedback no cancela la consulta. La aceptación del envío por Meta no garantiza
entrega inmediata. El menú respeta la misma ventana de atención de 24 horas.

WhatsApp muestra «⚠️ Hace 6 min» o «🟢 Hace 28 s» sin la palabra técnica STALE.
La clasificación, umbral y orden internos permanecen iguales. Los inventarios
conservan móvil, placa y GPSFix, y muestran movimiento. La consola conserva su
presentación. En ambos canales, la resolución compartida acepta `amb20` como
`AMB-20`; solo admite este alias para AMB seguido de dígitos, sin cambiar los
nombres recibidos ni eliminar separadores de otros identificadores. Si el alias
coincide con varios vehículos, informa ambigüedad.

Prueba manual con la configuración y el webhook reales ya existentes:

1. Reiniciar el proceso desde la raíz con
   `.\.venv\Scripts\python.exe -m gps_emi.whatsapp.server`, conservando el túnel
   HTTPS y la suscripción de Meta configurados. No iniciar una segunda instancia.
2. Desde un número autorizado, enviar MENU y tocar Ver opciones. Probar las
   cinco filas; en ubicación responder `amb20`, en sede probar 1 y 2. Vigilar
   llegada inicia la vigilancia real existente; usarla cuando se quiera monitorear.
3. Probar también `UBICACION amb20`, `SEDE POBLADO`, `SEDE TALLER`, `AYUDA` y
   MENU seguido de los números 1–4. Confirmar un feedback y después el resultado
   en cada consulta, así como reportes recientes/antiguos sin la palabra STALE.
4. Comparar identidad, posición, antigüedad y GPSFix con los datos reportados;
   `MOVIL- 96` debe conservarse literalmente. En consola probar
   `.\.venv\Scripts\python.exe gpspace_loaddatalog.py --action location --identifier amb20`.

Estas pruebas manuales quedan pendientes para esta mejora de interfaz. Los tests
son offline y no validan la visualización ni entrega reales en WhatsApp.

Ubicación y sede llaman a los casos de uso I3 originales, con una adquisición por
operación. No se duplican geocercas, resolución, clasificación de velocidad, orden
fresh/STALE ni antigüedad. `FleetPolling` obtiene un snapshot por ciclo y el
`WatchManager` de dominio lo distribuye a N Watches, cada una con su propio
`ObservationValidator` y `ArrivalMonitor`. `WatchRunner` y `ConsoleNotifier`
se conservan para consola. Véase [gestión de múltiples vigilancias](docs/multiple-watches.md).
`ArrivalMonitor`, `Vehicle` y la CLI I3 permanecen intactos. El parser WideTech
normaliza el markup HTML de `Zones` antes de entregar los nombres al dominio;
la comparación posterior de geocercas sigue siendo exacta.

El POST solo valida y encola: no espera HTTP de GPSpace/Meta ni polling. Un worker
procesa consultas y respuestas en orden de recepción local. Las vigilancias utilizan
otro hilo compartido: las altas pendientes se resuelven con el mismo snapshot
que alimenta las Watches activas. La unicidad es **owner_id + VEHID + ACTIVE**;
una solicitud por placa y otra por móvil no crean un duplicado para ese propietario.
No ejecutar varias instancias del piloto
ni una vigilancia CLI en paralelo: no existe coordinación entre procesos.

SIGTERM y Ctrl+C/SIGINT detienen la admisión y señalan parada a Inbox y polling
antes de esperar los hilos. Se cierran listeners y canales de Waitress; las esperas
de workers comparten un presupuesto de seis segundos. Los manejadores anteriores
se restauran al salir. SIGTERM termina con código 0 y SIGINT con 130, sin traceback
de cierre normal. Un HTTP ya iniciado no se puede cancelar; puede quedar truncado
al salir el proceso porque los hilos son daemon. No se garantiza drenaje/entrega.
Las esperas de polling/backoff son interrumpibles y se rechazan nuevas adquisiciones.
**Las vigilancias activas se pierden al reiniciar el proceso.**
Se conservan en memoria las completadas, canceladas y fallidas durante la sesión.

`GET /health` devuelve HTTP 200, `application/json`, `{"status":"ok"}`. Es solo
liveness HTTP: no accede a configuración, watches, Inbox, Meta ni GPSpace; tampoco
valida cookies ni garantiza readiness del polling. No usar un fallo de sesión
externa como motivo de reinicio automático mediante este endpoint.

El entrypoint conserva `--host` y `--port`, por defecto `127.0.0.1:8000`.
Una futura configuración de contenedor podrá pasar `--host 0.0.0.0`; esto no
publica el puerto ni implementa proxy, TLS o Docker.

### Configuración local

El comando del servidor carga `.env` del directorio actual con `override=False`,
igual que la CLI. Importar módulos, construir la app y los tests no leen `.env`.
`.env` continúa ignorado. Introducir los valores localmente sin compartirlos ni
ponerlos en comandos, capturas, logs o Git.

| Variable | Uso / predeterminado |
| --- | --- |
| `WHATSAPP_ACCESS_TOKEN` | Obligatoria; token de la app con permiso de mensajería |
| `WHATSAPP_PHONE_NUMBER_ID` | Obligatoria; ID del **número de prueba emisor**, no el teléfono del usuario |
| `WHATSAPP_VERIFY_TOKEN` | Obligatoria; secreto aleatorio elegido localmente y repetido en Meta |
| `WHATSAPP_APP_SECRET` | Obligatoria; App Secret de la misma app Meta |
| `WHATSAPP_ALLOWED_NUMBERS` | Obligatoria; números internacionales con país, separados por comas |
| `WHATSAPP_API_VERSION` | `v25.0`, configurable en un solo lugar |
| `WHATSAPP_ARRIVAL_MODE` | `template` por defecto; `text` para piloto dentro de ventana |
| `WHATSAPP_ARRIVAL_TEMPLATE` | `ambulance_arrival_notification` |
| `WHATSAPP_TEMPLATE_LANGUAGE` | `es`; debe coincidir con el idioma aprobado |
| `GPSPACE_COOKIE` | Configuración local existente de I1–I3 |
| `GPSPACE_CONTENT_TYPE` | Opción existente de I1–I3 |

Los números se comparan tras retirar `+`, espacios, guiones y paréntesis; se exige
código de país y no se adivina. La lista vacía impide arrancar. Identificadores
distintos de números telefónicos (por ejemplo BSUID) no se convierten ni autorizan.
Falta de token/App Secret/verify token o configuración inválida impide el arranque.

Desde `C:\GPS_EMI`, instalar las dependencias y actualizar la entrada de consola:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

Después de configurar localmente las variables, levantar el webhook:

```powershell
.\.venv\Scripts\python.exe -m gps_emi.whatsapp.server
```

Escucha en **127.0.0.1:8000**, ruta **/webhook**. También existe `gps-emi-whatsapp`
tras reinstalar el paquete. Opciones disponibles:

```powershell
.\.venv\Scripts\python.exe -m gps_emi.whatsapp.server --host 127.0.0.1 --port 8000 --interval 30 --initial-backoff 5 --max-backoff 30 --stale-warning-seconds 300
```

### Seguridad, recepción y deduplicación

GET exige `hub.mode=subscribe`, verify token correcto y `hub.challenge`, y devuelve
el challenge como texto con HTTP 200. Token/modo incorrecto devuelve 403.

POST exige `X-Hub-Signature-256`: `sha256=` seguido del HMAC-SHA256 hexadecimal
de **los bytes originales del cuerpo**, con App Secret como clave. Se compara con
`hmac.compare_digest` antes de interpretar JSON. No hay opción para desactivar firma.
Una firma ausente/incorrecta devuelve 403; JSON inválido devuelve 400; cuerpo superior
a 1 MiB devuelve 413. El verify token de GET no reemplaza la firma de POST.

Referencias oficiales consultadas: [Webhooks de Graph API](https://developers.facebook.com/docs/graph-api/webhooks/getting-started/),
[verificación documentada en el SDK oficial de Meta](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/webhooks/start/)
y [código oficial de webhooks](https://github.com/WhatsApp/WhatsApp-Nodejs-SDK/blob/main/src/api/webhooks.ts).
El portal developers.facebook.com respondió 429 durante esta revisión; se contrastó
el mecanismo con las fuentes oficiales accesibles. El SDK está archivado y **no se
instala ni se depende de él**; es una referencia del protocolo, no una garantía de
vigencia futura. La verificación real del panel corresponde a la prueba manual.

Solo se aceptan mensajes de texto del `phone_number_id` configurado en eventos
`whatsapp_business_account` / `messages`. Estados de entrega, imágenes y estructuras
válidas sin mensajes procesables se ignoran con 200. No se interpretan como comandos.
La autorización ocurre antes de crear clientes GPS o ejecutar casos de uso.
Un remitente no autorizado recibe como máximo el mensaje de acceso denegado y no
recibe placas, ubicación, existencia de identificadores ni estado de GPSpace.

`Inbox` reserva IDs de mensaje al encolar bajo un lock: el mismo ID no consulta,
responde ni inicia vigilancia otra vez durante su retención. Conserva hasta 10.000
IDs durante 7 días y una cola de 100 mensajes; un lote se acepta completo o ninguno.
Si no cabe, devuelve 503 sin marcar sus nuevos IDs, para permitir reintento de Meta.
No se expulsan IDs vigentes para hacer espacio. El orden es el de recepción local;
no se reconstruye un orden global si Meta entrega eventos fuera de orden.

La deduplicación y la cola son **solo memoria**: no garantizan procesamiento después
de un corte/reinicio, ni deduplicación entre procesos o después del plazo de retención.
Una vez aceptado el mensaje, un fallo de procesamiento/envío no hace que se ejecute
otra vez al repetirse el webhook. El usuario puede enviar una nueva solicitud.

### Menú y comandos

`MENU`, `MENÚ` e `INICIO` muestran el menú y restablecen `IDLE` para ese remitente:

```text
🚑 GPS EMI — Biomédica
1️⃣ Vigilar llegada de ambulancia
2️⃣ Consultar ubicación
3️⃣ Ver ambulancias en sede
4️⃣ Ayuda
```

1 pasa a `WAITING_WATCH_IDENTIFIER`; 2 a `WAITING_LOCATION_IDENTIFIER`; 3 a
`WAITING_SITE`; 4 o `AYUDA` muestra ayuda. Solo la opción 3 pide Poblado/Taller.
La siguiente entrada ejecuta el caso de uso correspondiente. Sede inválida conserva
la espera; después de una operación se regresa a `IDLE`. Ante un identificador
inexistente se informa sin escoger un vehículo. En WhatsApp, un identificador ambiguo
ofrece una lista de candidatos para continuar ubicación o vigilancia por VEHID exacto;
no se elige automáticamente ningún registro. Véase el
[protocolo de selección explícita](docs/vehicle-selection.md).

Comandos rápidos, también válidos con estado pendiente:

```text
VIGILAR AMB-20
VIGILAR PJU886
UBICACION AMB-20
UBICACIÓN PJU886
UBICACION MOVIL- 96
SEDE POBLADO
SEDE TALLER
MENU
MENÚ
INICIO
AYUDA
```

Los verbos ignoran mayúsculas y espacios exteriores/repetidos entre verbo y argumento.
El identificador se entrega al resolver existente conservando sus guiones y espacios
internos. Un comando rápido reconocido reemplaza el estado pendiente. MENU reinicia
la conversación, **no cancela la vigilancia**. Para detener esta en el piloto, usar
Ctrl+C en el servidor y volver a levantarlo.

Ubicación conserva Location, hora GPS, antigüedad humana, velocidad numérica/humana,
ignición y GPSFix. STALE queda marcado y no oculta el dato. No se muestran campos de
coordenadas. Inventario reutiliza orden y pertenencia exacta I3, conserva STALE y
aclara que representa la última posición reportada. Fechas desconocidas se marcan
con ❔. Textos largos se segmentan en mensajes de hasta 4096 caracteres.

### Envío de texto y plantilla de llegada

`WhatsAppClient.send_text` y `send_template` encapsulan exclusivamente HTTP hacia
`https://graph.facebook.com/<versión>/<phone-number-id>/messages`. No siguen
redirecciones, limitan tiempos de conexión/lectura y distinguen timeout, conexión,
autenticación, HTTP no exitoso y respuesta inesperada. Un ID de respuesta significa
**aceptación por Meta, no confirmación de entrega al celular**.

La [política oficial de WhatsApp](https://business.whatsapp.com/policy) permite texto
libre dentro de las 24 horas posteriores al último mensaje del usuario; fuera de esa
ventana exige plantilla aprobada. `ServiceWindow` centraliza esa regla, con reloj
inyectable y timestamp del mensaje firmado, no la hora de procesamiento. Mensajes
excesivamente futuros se rechazan; se toleran 60 s de diferencia de reloj.
Las ventanas solo se guardan para números autorizados. Tras un reinicio, el usuario
debe escribir de nuevo. No se prolonga la ventana por mensajes salientes.

La plantilla de llegada predeterminada debe existir y estar aprobada por Meta como
Utility. Este código no la crea ni da por aprobada. Nombre e idioma son configurables.
Propuesta de cuerpo, con cuatro variables de texto en este orden:

```text
🚑 Llegada de ambulancia
La ambulancia {{1}}, placa {{2}}, registró llegada a {{3}}.
Hora de la última posición reportada: {{4}}.
La información reportada no garantiza ubicación física actual.
```

Parámetros: `mobile_number`, `plate`, `site`, `gps_timestamp`; ausencias se representan
como N/D. Si `site=None` por pertenencia simultánea a ambas sedes, **se suprime la
plantilla** y se conserva el evento en memoria para revisión, sin inventar una sede.
En modo `text`, dentro de ventana, se muestran ambas con la aclaración de ambigüedad.

Para probar sin plantilla personalizada aprobada, configurar explícitamente
`WHATSAPP_ARRIVAL_MODE` con valor `text` y provocar la llegada dentro de la ventana.
Fuera de ventana se conserva el evento y se registra que no pudo enviarse; no hay
fallback automático a texto. Con `template`, se envía la plantilla tanto dentro
como fuera de ventana y Meta decide si la acepta según aprobación y permisos.
La disponibilidad de plantillas personalizadas con el emisor de prueba debe
confirmarse en la cuenta Meta; no se sustituye por `hello_world` para simular llegada.

`WhatsAppNotifier` conserva el último evento y su resultado (`accepted` o
`delivery_error`). Un error de envío no reinicia ni borra estado/timestamp del monitor.
El runner completa la llegada y no la repite. No se reintenta automáticamente un
envío fallido: un timeout puede haber ocurrido después de aceptarlo Meta. El último
runner/notificador está en memoria hasta iniciar otra vigilancia o cerrar el proceso;
no existe bandeja persistente ni reenvío manual implementado.

Los logs del canal registran verificación, autorización sin teléfonos, clase de
comando, consulta, watch y resultado del transporte. Nunca cuerpos de mensajes,
tokens, headers, URLs autenticadas ni excepciones originales. Los logs locales
del runner I2 conservan sus identificadores técnicos/operacionales. Los errores de
GPSpace recibidos por WhatsApp se traducen a mensajes controlados sin detalles HTTP.
No activar access logs que incluyan query strings: el GET de Meta lleva verify token.

### Pasos manuales en Meta y túnel HTTPS

1. Abrir la **app de prueba existente** en Meta for Developers y entrar a WhatsApp
   → API Setup / Configuración de la API (los rótulos pueden variar en el panel).
2. En el campo emisor seleccionar el **número de prueba de Meta**. Copiar su Phone
   Number ID a la configuración local. No usar “Add phone number” para registrar
   el número institucional como emisor.
3. En destinatarios de prueba agregar el celular de Biomédica con código de país
   y completar la verificación que solicite Meta. Incluir ese mismo número en
   `WHATSAPP_ALLOWED_NUMBERS`.
4. Obtener el token de la app para el piloto con `whatsapp_business_messaging` y
   guardarlo localmente. En App Settings → Basic obtener el App Secret de esa app.
   Elegir un verify token aleatorio y guardarlo localmente. No compartir capturas
   ni volcar estos valores. Los tokens temporales caducan y requieren renovación manual.
5. Configurar las variables de la tabla y arrancar el servidor con el comando anterior.
6. Instalar `cloudflared` siguiendo la [documentación oficial](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).
   En otra terminal, ejecutar:

   ```powershell
   cloudflared tunnel --url http://127.0.0.1:8000
   ```

   Copiar la URL HTTPS temporal `https://<subdominio>.trycloudflare.com` que imprime.
   No requiere guardar credenciales de túnel en el repositorio. Es solo para pruebas,
   no tiene garantía de disponibilidad y puede cambiar al reiniciarlo.
7. En WhatsApp → Configuration / Configuración → Webhook, indicar como callback
   `https://<subdominio>.trycloudflare.com/webhook` y el verify token local exacto.
   Pulsar Verify and Save. El log debe indicar “Webhook verificado”.
8. Suscribirse al campo **messages** del objeto `whatsapp_business_account`.
   Confirmar que la app está suscrita a la WABA del número de prueba; si no llegan
   mensajes, revisar esta suscripción siguiendo la
   [colección oficial de Meta](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api).
   No basta con que el GET de verificación funcione.
9. Usar la prueba del campo messages del panel. Un payload de ejemplo con otro Phone
   Number ID o remitente no autorizado puede ignorarse/denegarse: no quitar las
   validaciones para hacerlo pasar. Luego enviar un mensaje real desde Biomédica
   **al número de prueba de Meta** para abrir la ventana de atención.
10. Para notificaciones por plantilla, en WhatsApp Manager crear la Utility con el
    nombre/idioma/cuerpo de cuatro variables indicado y esperar aprobación. Si la
    cuenta de prueba no lo permite, usar el modo explícito `text` dentro de ventana.
11. Desde Biomédica ejecutar la secuencia siguiente y revisar mensajes/logs. Detener
    servidor y túnel con Ctrl+C al terminar. No dejar la URL temporal como despliegue.

### Secuencia de prueba real del usuario

1. `MENU`: comprobar las opciones originales y Gestionar vigilancias.
2. `2`, luego `AMB-20`: comprobar ubicación; repetir `UBICACIÓN PJU886` para la misma
   ambulancia. Verificar que `MOVIL- 96` se conserva cuando el proveedor lo entrega.
3. `3`, luego `1`: inventario Poblado. `SEDE TALLER`: inventario Taller, antigüedad visible sin la palabra STALE.
4. `4` o `AYUDA`. Iniciar `2` y después `MENU`: debe reiniciar el estado pendiente.
5. `VIGILAR AMB-20`: confirmar móvil/placa al resolver, sin elegir sede. Repetir
   `VIGILAR PJU886` mientras está activa: debe informar que ya existe una vigilancia.
6. Usar `MENU` y `UBICACION AMB-20` durante vigilancia: webhook y consultas siguen
   disponibles. MENU no cancela el watch.
7. Esperar una transición reportada fuera de ambas sedes → dentro de una. Una primera
   lectura ya dentro o un cambio Taller/Poblado sin exterior no genera llegada.
   Verificar plantilla aprobada o texto dentro de ventana según modo configurado.
8. Opcionalmente, con otro destinatario de prueba que no esté en la allowlist,
   comprobar que no obtiene información GPS. No ampliar autorización para esta prueba.

### Validación y límites del piloto

```powershell
.\.venv\Scripts\python.exe -m pytest
git diff --check
git status
git diff --stat
```

Las 265 pruebas I1–I3 se conservan. I4-P agrega HTTP simulado, firmas sobre bytes,
autorización, deduplicación concurrente, menú/comandos, formato, ventana de atención,
múltiples vigilancias, cancelación individual y respuestas HTTP mientras el polling está bloqueado.
No usan Meta/GPSpace real, `.env`, ni sleeps de polling reales. Las pruebas de hilos
usan eventos para sincronizar sin depender de la hora GPS real.

Pendiente para I4 definitivo: persistencia de conversaciones/deduplicación/entregas,
recuperación tras caída, seguimiento de estados de entrega, estrategia de reenvío,
cancelación remota y soporte para otras identidades de Meta si fuera necesario.
Las consultas se procesan secuencialmente: una adquisición lenta puede retrasar
respuestas posteriores, aunque el webhook ya haya confirmado la recepción.
Riesgos externos: caducidad de token/cookie, aprobación y disponibilidad de plantilla,
restricciones del número de prueba, cambios de Graph API, reloj local y túnel temporal.
La suite valida el software, no la configuración ni la entrega real de la cuenta Meta.

## Local Docker pilot

Requiere Docker con Compose y `.env` local, ignorado por Git. Compose carga ese
archivo únicamente como variables de runtime; no se copia al contexto ni a la imagen.

```sh
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f gps-emi
docker compose down
```

El puerto se publica solo en `localhost:8000` (127.0.0.1). `/health` es liveness
local y devuelve `{"status":"ok"}` sin consultar GPSpace ni Meta. Los logs salen
por stdout/stderr. El cierre dispone de 15 segundos de gracia para el presupuesto
interno de seis segundos. No hay volúmenes: reiniciar el contenedor pierde las
watches activas y el estado conversacional temporal. La sesión de GPSpace todavía
requiere renovación manual. Este piloto local no implementa VPS ni HTTPS.

## Pendiente

I4 definitivo e I5 (despliegue permanente) no están implementados. No se incluyen
VPS, systemd, base de datos, Redis/Celery, panel web,
login/renovación automática de GPSpace ni geocercas propias.
