# WideTech oficial — fase 1 aislada

**Fase 1 cerrada para avanzar a integración; proveedor oficial todavía no activado.**

Siguiente paso documental: [especificación de fase 2](widetech-official-phase2-spec.md).
El encargo de cierre del 8 de octubre de 2026 prevalece sobre las propuestas
anteriores. No se implementó fase 2 ni se hicieron nuevas peticiones reales en el cierre.

El adaptador `gps_emi.providers.widetech_official` no se registra ni se importa
desde los arranques operacionales. `WideTechClient`, `Vehicle`, CLI, WhatsApp,
vigilancias y collector conservan su comportamiento. No hay persistencia,
polling, caché, sleeps ni reintentos. No se usaron credenciales reales.

## Firma y configuración

Firma pública consultada sin credenciales el 7 de octubre de 2026:
[HistoryDataLastLocationByUserRenderExcel](https://web1ws.widetech.co/wsHistoryGetByPlate.asmx?op=HistoryDataLastLocationByUserRenderExcel).
La página publica POST de formulario a
`https://web1ws.widetech.co/wsHistoryGetByPlate.asmx/HistoryDataLastLocationByUserRenderExcel`,
con `sLogin` y `sPassword` de tipo string y respuesta `DataTable` en namespace
`http://shareservice.co/`. No es un archivo Excel.

Configuración explícita: `OfficialConfig(login, password,
timezone_name="America/Bogota", connect_timeout=10, read_timeout=30)`.
El llamador suministra los secretos; este módulo no lee variables, `.env`,
cookies ni estado LoadDataLog. Las credenciales no aparecen en su `repr`.
Los timeouts deben ser finitos, mayores que cero y como máximo 120 segundos.
Son límites de conexión y de inactividad de lectura de requests, no un plazo
global de ejecución ni una frecuencia de consulta.

`OfficialWideTechClient(config, transport=transporte_falso).acquire()` devuelve
un `AcquisitionResult`. El transporte inyectado implementa `post(url, **kwargs)`
y devuelve una respuesta compatible con `requests.Response`. Debe respetar el
contrato de una petición, sin reintentos ni redirecciones propios.
Las pruebas muestran una implementación completa en `FakeTransport`.

El transporte predeterminado crea una sesión nueva, deshabilita `trust_env`
(incluidos netrc y proxies de entorno) y configura cero reintentos. Usa HTTPS,
verificación TLS normal y `allow_redirects=False`. Las credenciales se envían
solamente en el cuerpo del formulario. Cada adquisición llama una sola vez a
`post`; un error nunca dispara otra petición. No hay fallback al proveedor viejo.

## Contrato de datos y mapping

| Origen | Contrato del adaptador |
|---|---|
| `VEH_ID` | `vehicle_id`, identidad de vehículo; no se sustituye por `Id` |
| `Id` | `gps_record_id`, identidad del registro GPS |
| `Movil`, `VEH_NAM` | Se conservan en `raw`, sin asignar `mobile_number` o `plate` |
| `fltName` | Original en `raw`, `fleet_name` normalizado y `classification` |
| `FechaGPS`, `FechaServidor` | Originales en `raw`; interpretaciones aware separadas |
| `Latitude`, `Longitude`, `Velocidad` | `latitude`, `longitude`, `speed`: floats finitos o `None` |
| `StateIgnition` | `0`/`false` → False; `1`/`true` → True; vacío/nulo/ausente → None |
| `GPSFix` | Cadena original en `raw` y propiedad `gps_fix`, sin interpretación añadida |
| `Zones` | Original en `raw`, `zones_present` y tupla `zones` de nombres exactos |
| `Localizacion`, `Rumbo`, `MSGID`, `Mensaje`, `Altitud`, `VEH_DESC`, `StatusForm` | Valores originales reconocidos en `raw` |
| `mtlCelularID`, campos adicionales | No se conservan |

`raw` es un mapping inmutable de campos presentes: clave ausente, valor `None`
por `xsi:nil`, y cadena vacía son estados distintos. No se guardan cuerpos completos.
La extracción de geocercas reutiliza `zone_list`, sin cambiar su implementación.
Se admite el marcado observado `<Localizacion><B>…</B></Localizacion>`:
se conserva como texto XML serializado, incluidos texto previo y posterior,
sin ejecutarlo ni interpretarlo como instrucciones. Esta excepción se limita
a hijos `B` sin atributos ni descendientes. Otras estructuras anidadas se
diagnostican. No se modifica ni repara el XML de entrada.

La correspondencia observada en **LoadDataLog** (`VEH_LCNS` móvil, `VEH_NAM`
placa) no demuestra el significado de `Movil` en **RenderExcel**. La firma
pública no define esa equivalencia. Por eso no existe conversión automática a
`Vehicle`: la integración posterior aplicará el mapping y la política temporal
acordados para ese incremento. El modelo operacional sigue usando fechas naive.

Normalización de flota: Unicode NFC y eliminación de espacios en los extremos;
sin quitar acentos, cambiar mayúsculas, colapsar espacios internos ni eliminar
sufijos. Se aplica literalmente `startswith("Ambulancias")`, sensible a
mayúsculas: `AmbulanciasX` también cumple el prefijo; `ambulancias` y
`Ambulancia` no. Vacío/ausente/nulo → `unknown`; otro nombre → `other`.
`VEH_DESC=CAMIONETA` no cambia la clasificación. No hay política especial de
Medellín en esta fase. Se retienen todas las clasificaciones para el futuro catálogo.

Fechas aceptadas: ISO `YYYY-MM-DD[T o espacio]HH:mm:ss`, fracción opcional y
offset `±HH:mm` o `Z` opcional; también `YYYY/MM/DD HH:mm:ss`. Sin offset se
interpreta en la zona configurada; con offset se convierte a esa zona.
Fechas inválidas, ambiguas/inexistentes por DST o no representables generan
diagnósticos y `None`. No hay sustitución por fecha servidor o fecha de consulta.
Se conserva la precisión original en `raw`, incluso si excede los microsegundos
que admite datetime. No se aplican filtros de rango geográfico o plausibilidad.

## Parsing, calidad y errores

`parse_render_excel` es independiente del transporte. Reconoce DataTable con
un schema y un diffgram, y las envolturas SOAP 1.1/1.2 del método publicado.
Solo lee filas `Table` de `diffgram/NewDataSet` sin namespace (el dataset
restablece `xmlns=""`); no busca etiquetas por nombre local en todo el árbol.
Un diffgram sin dataset, o un dataset sin filas, representa un lote vacío válido.
Una respuesta HTTP vacía, estructura desconocida, SOAP Fault o XML truncado
no representa una flota vacía.

El parser estándar usa un TreeBuilder que rechaza DTD antes de expandir
entidades; no procesa XInclude ni carga schemas, entidades o recursos externos.
Límites locales defensivos: 8 MiB de XML y 64 niveles de profundidad.
El límite de bytes se comprueba antes del parsing, después de recibir el cuerpo;
no es un límite de descarga en streaming. No se pretende validar todo XSD.

`AcquisitionResult` entrega todos los registros, procedencia fija de servicio y
método, zona interpretativa, diagnósticos, identidades duplicadas, posiciones
de filas incompletas y `Retry-After` validado. Los índices de fila empiezan en 1.
Para esta fase una fila es incompleta si carece de identidad de vehículo,
identidad GPS, fecha GPS válida, coordenadas numéricas o nombre de flota.
Los opcionales ausentes no invalidan una fila; opcionales mal formados sí
generan diagnósticos. No se colapsan duplicados ni se elige arbitrariamente un ganador.
`has_quality_issues` refleja diagnósticos; **`coverage` siempre es `unknown`**.
No hay indicador que certifique cobertura total por estar bien formado el XML.

`OfficialAcquisitionError` hereda de `AcquisitionError`, con `kind`, `status`,
`retry_after`, `functional_code` y `functional_kind`. Categorías: configuración,
red, timeout, HTTP, autenticación (401/403 o código estructurado), autorización,
servicio no disponible, restricción, sin datos, otro fallo funcional, payload,
respuesta vacía y SOAP. Los códigos desconocidos conservan su entero y
`functional_kind=unknown`, con `kind=functional`.
Un HTTP 200 pasa por validación funcional/estructural. Los demás estados,
incluidas redirecciones y 5xx, conservan el status sin seguir el destino.
`Retry-After` admite segundos enteros o fecha HTTP con zona, normalizada a UTC;
no almacena cabeceras arbitrarias ni calcula esperas. También se entrega en
respuestas exitosas y fallos de parsing. No se registra contenido, credenciales
ni respuestas; las excepciones de requests no se encadenan ni se adjuntan.

**Catálogo aportado el 8 de octubre de 2026:** `classify_functional_code(int)`
clasifica un código ya extraído, sin examinar XML ni texto libre. Los grupos son:

| Categoría | Códigos |
|---|---|
| Éxito | 0, 100 |
| Autenticación | 1, 101, 106 |
| Autorización/asociación/caducidad | 6, 7, 102, 108, 116, 117 |
| Servicio no disponible | 4, 5, 103 |
| Restricción | 109, 1031 |
| Sin datos | 110, 119, 1014 |
| Otro resultado no exitoso para esta adquisición | Resto de códigos aportados |
| Desconocido | Entero no incluido en la tabla aportada |

Es una clasificación del adaptador, no una equivalencia entre todos los
métodos del proveedor. Por ejemplo, 1024 describe actualización de vehículo
y 1515 describe boot en proceso; ninguno acredita éxito de RenderExcel.
La categoría sin datos no se convierte automáticamente en un lote vacío;
0/100 tampoco certifican cobertura ni sustituyen el parsing del DataTable.
El catálogo describe 109 como intervalo **mayor a 20 segundos** y 1031 como
exceso de uso del módulo. No se deriva de ellos un Retry-After ni se configura
un intervalo global o específico de RenderExcel.

**Reconocimiento estructurado implementado:** antes de interpretar DataTable se
acepta exclusivamente la raíz `space`, sin namespace ni atributos, con un solo
`Response` y un solo `Status`; este contiene exactamente un `code` y como máximo
un `description`, ambos escalares, sin atributos. `description` es opcional.
Se permite espacio exterior en el código, que debe contener de 1 a 10 dígitos
ASCII; no signos, decimales, texto libre ni nodos anidados. No se admiten hermanos
extra, namespaces alternativos, estados/códigos repetidos o contradictorios,
ni una mezcla de status y DataTable en esa envoltura: son payload inválido y no
se elige arbitrariamente un código. No se buscan Status dentro de filas o SOAP.

La ruta `space/Response/Status/code` conecta con la tabla ya aportada. 108 produce
`authorization` y `functional_code=108`: denegación para la funcionalidad, sin
declarar credenciales inválidas ni indisponibilidad de otros métodos. 109 produce
`restriction` y conserva el código; no se infiere un Retry-After ni una espera
de su descripción. 0/100 sin DataTable se rechazan como payload conservando el
código; sin datos produce `no_data`, nunca un snapshot vacío. La descripción no
se incluye en errores/logs ni determina clasificación. HTTP 500 texto plano
conserva `http` sin inferencias. Retry-After sigue conservándose y no hay reintentos.

No se inventa correspondencia entre códigos SOAP y funcionales. Texto libre,
Mensaje, Id, Localizacion y faultstring no se examinan buscando números.
No se afirma que 20 o 40 segundos sean el contrato de RenderExcel. El intervalo
inicial aprobado para el futuro coordinador es 30 segundos configurable.

### Evidencia y alcance de las pruebas de cierre

| Nivel de evidencia | Qué acredita |
|---|---|
| Observado en RenderExcel | DataTable/diffgram con vehículos; con credenciales aleatorias, HTTP 500 texto plano por fallo de serialización, sin código funcional interpretable |
| Observado en GetMobileList y aportado por el usuario | `space/Response/Status`, code 108 y descripción de permiso denegado; la misma cuenta sí puede utilizar RenderExcel |
| Implementado y probado offline | Validación estricta de la envoltura, clasificación por código, preservación de Retry-After, errores seguros y no interferencia con DataTable |
| Soportado mediante pruebas sintéticas | 109 y otros códigos en esa envoltura; variantes mal formadas, ambiguas, éxito sin DataTable, sin datos y números dentro de vehículos |
| No demostrado | Que RenderExcel emita esa envoltura, ni su frecuencia efectiva por método/cuenta/IP |

La fixture `widetech_status_108.xml` transcribe la envoltura no sensible aportada
de GetMobileList; `widetech_status_109_synthetic.xml` es exclusivamente sintética.
El soporte del parser para 109 no se presenta como observación de RenderExcel.
GetMobileList no es dependencia ni health check: no se consulta ni se usa para
decidir disponibilidad de RenderExcel. El aviso del navegador sobre estilos no
forma parte del payload y no se añade a ninguna fixture.

El adjunto aportado en la misma fecha es un DataTable exitoso, sin elementos
de estado/error funcional. La inspección local permitió verificar campos
opcionales, marcado `B` en Localizacion y etiquetas que no siempre coinciden.
No se incluyen filas operativas ni conteos de flota en este documento o las
fixtures. El encabezado de texto
del visor del navegador se excluyó explícitamente solo para esta inspección;
el parser HTTP no elimina encabezados arbitrarios ni repara respuestas.

Prueba manual expresamente autorizada por el usuario el 8 de octubre: un solo
POST al método con usuario y contraseña aleatorios, sin redirecciones ni
reintentos. Resultado: HTTP 500, Content-Type text/plain, 113 bytes y cuerpo
no XML. Se inspeccionó solo metadata/estructura, sin registrar el cuerpo.
Esto no demuestra un código funcional concreto ni una envoltura de 109;
el adaptador conserva la categoría HTTP. La suite sigue siendo enteramente
offline y reproduce el caso con texto sintético, sin copiar la respuesta.

## Validación y pendientes de integración

**Validación del cierre (ejecuciones nuevas):** `-m pytest -q
tests/test_widetech_official.py`: **187 aprobadas en 1,69 s**. `-m pytest -q
--basetemp=$testTemp`: **892 aprobadas en 11,21 s**. Los comandos completos
de intérprete, PYTHONPATH y temporal seguro figuran abajo. El conteo 851 de
la revisión anterior se mantiene solo como antecedente, no como resultado actual.

En la revisión inicial del cierre faltaban en el archivo del adaptador el
clasificador funcional y el soporte B de Localizacion, aunque sus pruebas y
documentación seguían presentes. Se restablecieron ambas implementaciones
acotadas antes de conectar la nueva envoltura. Se añadieron 41 casos de cierre.
No se cambió código operacional ni se realizaron nuevas consultas reales.
Se conservaron los cambios ajenos encontrados en README.md, multiple-watches.md,
vehicle-selection.md y los demás documentos nuevos del usuario.

Fixtures exclusivamente sintéticas; `conftest.py` impide red y sleeps reales.
El ejecutable de `.venv` falla al lanzar su Python base 3.14 con «Acceso denegado»;
también se comprobó el fallo al lanzar directamente ese ejecutable base.
No se cambiaron permisos ni instalaron dependencias. Se usó Python 3.12.14
incluido en Codex y las dependencias existentes de `.venv` mediante PYTHONPATH.
La carpeta temporal habitual de pytest también tiene acceso denegado, por lo
que se selecciona una carpeta nueva bajo `.pytest_cache` en cada ejecución.

```powershell
$env:PYTHONPATH='C:\GPS_EMI\.venv\Lib\site-packages;C:\GPS_EMI\src'
$testPython='C:\Users\jjcor\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $testPython -m pytest -q tests/test_widetech_official.py
$testTemp=Join-Path 'C:\GPS_EMI\.pytest_cache' ('official-' + [guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $testTemp) { throw 'La carpeta debe ser nueva' }
& $testPython -m pytest -q --basetemp=$testTemp
git diff --check
```

Resultados ejecutados el 8 de octubre de 2026: ejecución inicial de pruebas
nuevas, 120 aprobadas; suite anterior, 825 aprobadas. Tras incorporar el catálogo
aportado, el marcado observado y la respuesta de la prueba manual, suite
completa de esa revisión: **851 aprobadas en 12,94 s** (incluye 146 pruebas del adaptador).
Regresión inicial del proveedor y geocercas: 35 aprobadas. El primer intento
de suite completa con temporales predeterminados produjo 769 aprobadas y
41 errores de preparación por permisos; la ejecución con temporales locales
resolvió esos errores. `git diff --check` sin incidencias. Se verificó también
que no hay diferencias en modelo, excepciones existentes, proveedor anterior,
CLI, WhatsApp, monitoring ni analysis. Los archivos ajenos preexistentes
`.codemapignore`, `docs/auditoria-api-oficial.md` y
`docs/prompt-integracion-api-oficial.md` se conservaron sin editar.

### Alcance de las decisiones posteriores

No está confirmado que RenderExcel utilice la envoltura funcional observada en
GetMobileList. Esa es la limitación de envoltura que permanece abierta.
El HTTP 500 observado no identifica su causa funcional: el fallo de serialización
no permite atribuir un código de autenticación/autorización/restricción.

Según la aclaración posterior del usuario, el tratamiento de límites de consulta,
mapping de etiquetas, semántica horaria y las decisiones de integración ya se
discutieron y decidieron para incrementos posteriores. Las notas técnicas de este
documento delimitan lo que implementa el adaptador; no reabren esas decisiones
ni las convierten en nuevos bloqueos. Su consolidación documental posterior debe
recoger los valores acordados, sin sustituirlos por propuestas de este cierre.

El coordinador se especifica con fuentes falsas. Catálogo, campañas y continuidad de vigilancia se implementan en sus
fases respectivas: consultas/campañas nacionales por prefijo Ambulancias,
vigilancias exclusivamente Medellín, terminación por cambio confirmado de flota
y sin restauración automática. No se despliega ni se activa el proveedor aquí.
