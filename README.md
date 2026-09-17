# GPS EMI — Incremento I1

Monitor de consola para **una ambulancia**, seleccionada por **placa o número de móvil**,
de Ambulancias Medellín y **un destino**.
Utiliza la pertenencia a geocercas reportada por WideTech en `Zones`: no calcula
distancias, no utiliza coordenadas para decidir llegadas y no garantiza posición actual.

Destinos admitidos, por nombre exacto:

- `EMI Medellin_Poblado`
- `EMI_Medellin_Taller`

`ZONA 2 - POBLADO` no equivale a `EMI Medellin_Poblado`.

## Arquitectura

`WideTechClient → Vehicle → find_vehicle → ArrivalMonitor → ArrivalEvent → NotificationService → ConsoleNotifier`

El adaptador concentra autenticación, petición, parser y normalización. Devuelve
exclusivamente registros cuyo `fltName` sea `Ambulancias Medellin;44986;0`.
No se presupone un número de móviles ni de ambulancias. El dominio no conoce
HTTP, cookies ni canales de notificación. `NotificationService` es un protocolo
mínimo para añadir otro canal en el futuro sin alterar el monitor.

```text
src/gps_emi/
    __init__.py
    models.py
    resolution.py
    cli.py
    providers/
        __init__.py
        widetech.py
    monitoring/
        __init__.py
        arrival.py
        observation.py
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

La selección se resuelve antes de crear el monitor y en cada consulta. El archivo
`ArrivalMonitor` y sus reglas no cambian. Para registros sin placa (`VEH_NAM`), una pequeña
adaptación utiliza el número de móvil (`VEH_LCNS`) únicamente en la copia que recibe su
interfaz de I1, que exige `plate` no vacío. El modelo resuelto y el evento que recibe
el notificador conservan los campos originales separados. La consola usa el número
de móvil si no hay placa disponible.

La primera lectura establece `OUTSIDE` o `INSIDE` y no produce evento. Solo una
transición observada `OUTSIDE → INSIDE` produce `ARRIVAL_DETECTED`. El notificador
muestra la llegada y la CLI termina. El monitor no vuelve a emitir eventos.
La placa o número de móvil se compara sin distinguir mayúsculas y quitando espacios exteriores;
no se eliminan guiones. Las geocercas se comparan exactamente.

El intervalo predeterminado es 30 segundos de espera **después** de cada consulta;
el tiempo HTTP se suma al ciclo. Debe ser finito y positivo. Ctrl+C termina sin
traceback (código 130). Errores de consulta, identificador inexistente/ambiguo o desaparición
del móvil detienen la vigilancia (código 1), sin inventar una salida de geocerca.
Una llegada termina con código 0. Reiniciar comienza una vigilancia nueva.

Si no se ha iniciado sesión en GPSpace o la cookie ya expiró, la consola indica
explícitamente que se debe iniciar sesión y actualizar `GPSPACE_COOKIE`. Los
problemas de red se reportan por separado como un fallo de conexión. Una respuesta
HTTP inesperada se muestra solo con su código, sin cuerpos, URLs de redirección ni
headers autenticados.

## Pruebas sin Internet

```powershell
.\.venv\Scripts\python.exe -m pytest
```

`pytest.ini` configura el directorio `src` y deshabilita `pytest-dotenv`.
Las pruebas bloquean las peticiones de red, eliminan las variables de autenticación
heredadas y sustituyen la carga de `.env`. Los ejemplos de telemetría son sintéticos,
salvo `tests/fixtures/emi_amb20.json`, que contiene exclusivamente los cuatro valores
no sensibles observados: VEHID, VEH_LCNS, VEH_NAM y fltName. Sus pruebas verifican el
mapping y que buscar AMB-20 o PJU886 devuelva el mismo objeto Vehicle con VEHID 433909.
Los valores de prueba de autenticación se generan temporalmente en memoria;
no se almacenan cookies en fixtures. Se cubren las diez situaciones de aceptación,
coincidencia exacta, ausencia de duplicados, parser con Sensors anidados, HTML,
comillas, new Date, filtrado de flota, contrato HTTP, errores seguros y CLI.

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

La consola muestra **última posición reportada**, fecha GPS y GPSFix en cada lectura.
Advierte si GPSFix es cero o falta información. No aplica un umbral arbitrario de
antigüedad ni descarta lecturas por GPSFix: el usuario debe revisar la fecha.
Una transición con reportes antiguos o desordenados aún puede producir un evento.
Tampoco se detectan entradas y salidas completas ocurridas entre dos consultas.
No hay reintentos, persistencia, múltiples vigilancias ni política de continuidad
si cambia el VEHID asociado a una placa o número de móvil. La validación automatizada utiliza HTTP
simulado; hace falta una prueba manual con sesión vigente para confirmar el servicio.

## Pendiente

I2: robustez frente a datos antiguos/desordenados, cambios de formato, fallos de red
y continuidad de identidad. Futuros incrementos: WhatsApp (otro notificador),
recepción de comandos y despliegue VPS Ubuntu. Nada de esto está implementado en I1.
