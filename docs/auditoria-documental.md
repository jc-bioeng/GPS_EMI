# Auditoría documental y preparación para portafolio

**Auditoría inicial: 19 de octubre; cierre editorial: 20 de octubre de 2026**. Workspace `C:\GPS_EMI`, rama `master`, HEAD `a8f3f24`.
Incremento exclusivamente documental: no cambia funcionalidades ni crea una demo.
Esta auditoría no sustituye las [decisiones aprobadas](decisiones-arquitectonicas-renderexcel.md).

## Alcance y método

Antes de editar se revisaron Git, documentos versionados y sin seguimiento y
artefactos relacionados. No se encontró AGENTS.md en el proyecto ni en `C:\`.
Herramientas: `rg --files`, `git ls-files`, `git status --short`, `git diff`,
`git log --all`, inventario de archivos y lectura íntegra del README y los
21 Markdown de `docs/` existentes. También se leyeron el informe privado de
campaña y sus dos scripts, sin ejecutar el análisis ni copiar datos a esta auditoría.

Se leyó la fuente del PDF y se extrajo el texto de sus ocho páginas con `pypdf`
del runtime disponible. Se inspeccionó visualmente `updated-review.png`.
Las vistas PNG son revisiones: el montaje conserva comandos con nombres anteriores
y no acreditaba correspondencia exacta con aquel PDF. La revisión y sustitución
final del PDF se describen en el cierre de este documento.

El contraste de implementación incluyó composición y entrypoints, runtime de
adquisición, conexión SQLite, Continuity, confirmación en FleetPolling/MessageService,
parser de comandos, esquema catálogo/collector, pruebas existentes de confirmación,
fixture offline, manifests de dependencias, Dockerfile y Compose. Las búsquedas
localizaron código; la clasificación documental no se basa solo en títulos.

No se consultaron WideTech, Meta, SSH, GitHub ni servicios externos. No se identificó
la imagen remota. No se abrió la base operativa ni se cargó `.env` para ejecutar la
aplicación. Las fuentes originales CSV/chat fuera del repositorio se identifican
en el informe privado: no se releen ni revalidan aquí. Sus JSON/CSV derivados se
inventarían sin repetir el análisis de filas ni certificar aceptación operacional.

## Estado inicial y conservación

Había cambios locales en README, índice, decisiones y múltiples vigilancias; ocho
Markdown sin seguimiento en `docs/`, además de `.codemapignore`, `output/` y `tmp/`.
Se conservaron los acuerdos, evidencias y correcciones previas. No hubo reset,
checkout, limpieza, staging, commit ni reescritura de historial.

El README previo, incluidos sus cambios locales, se trasladó a
[antecedentes I1–I4](antecedentes-i1-i4.md), con aviso histórico y enlaces relativos
corregidos. El enlace de mantenimiento al README histórico apunta ahora allí.
Antes del saneamiento se guardaron 45 archivos originales y un manifiesto
SHA-256 en `data/documentacion-original-20261019/`, ignorado por Git. El PDF se
sustituyó por una edición derivada del Markdown; las revisiones PNG antiguas
permanecen privadas en `tmp/`. No se eliminaron originales. El manual de mantenimiento
conserva evolución, mapa de código y verificación; remite a guía/operación para evitar
mantener otra explicación paralela del sistema.

## Inventario y clasificación inicial

Git inicial: **V** versionado; **M** con cambios previos; **U** sin seguimiento;
**I** ignorado. Sensibilidad **P**: candidato a presentación tras revisión;
**O**: contexto operativo o ejemplos observados que requieren revisión de publicación;
**R**: evidencia privada, excluir de publicación. P no certifica ausencia de secretos.

| Archivo | Propósito y público | Vigencia / Git inicial | Sensibilidad | Relación y función |
|---|---|---|---|---|
| `README.md` | Presentación / nuevo lector | Actual reconciliado / M | P; original O | Entrada e instalación; anterior conservado en antecedentes |
| `docs/README.md` | Navegación / todos | Actual / M | P | Índice por necesidad y estado general |
| `docs/decisiones-arquitectonicas-renderexcel.md` | Acuerdos / responsable y mantenedor | Aprobado y actualizado por encargos / M | O | Única referencia normativa; distingue implementación |
| `docs/guia-del-sistema.md` | Arquitectura / lector técnico | Actual reconciliado / V | O | Componentes, flujo y responsabilidades |
| `docs/operacion.md` | Configuración / operador | Actual reconciliado / V | O | Variables, CLI, Docker y campañas |
| `docs/manual-mantenimiento.md` | Mantenimiento / desarrollador | Actual reconciliado / U | P | Evolución, módulos y verificación; enlaza guía, operación y SQLite |
| `docs/base-de-datos.md` | Diccionario / mantenedor SQLite | Esquema v3 y catálogo v1 / U | P | Tablas, consistencia y compatibilidad; enlaza recuperación |
| `docs/procedimientos-recuperacion.md` | Incidentes / operador | Procedimientos no ejecutados aquí / U | O | Backup, restauración, reversión y diagnóstico |
| `docs/comandos-whatsapp.md` | Referencia / usuario y soporte | Ajuste incluido en `a8f3f24` / U | P | Alias y confirmación; evidencia offline histórica |
| `docs/multiple-watches.md` | Subsistema / mantenedor | Actual con prueba manual histórica / M | O | Concurrencia, estados, notificación; enlaza confirmación |
| `docs/vehicle-selection.md` | Protocolo / mantenedor | Actual reconciliado / V | O | Identidad, propietario, TTL y ambigüedad |
| `docs/gps-collector.md` | Captura / mantenedor | Fase 4 vigente, pruebas previas históricas / V | O | Contrato de captura y deduplicación |
| `docs/collection-sessions.md` | Campañas / operador técnico | Fase 4 vigente, pruebas previas históricas / V | O | Ciclo, admisión, plazo y observabilidad |
| `docs/widetech-official-phase1.md` | Evidencia / revisor | Histórico `eda2606` / V | O | Adaptador aislado; integración posterior en fase 2 |
| `docs/widetech-official-phase2-spec.md` | Evidencia y contrato / revisor | Histórico `24dae94` / V | O | Adquisición central y exclusión; alcance de su fecha |
| `docs/widetech-official-phase3.md` | Evidencia / revisor | Histórico `a171b37` / V | O | Catálogo y consultas nacionales; collector Medellín en ese cierre |
| `docs/widetech-official-phase4.md` | Evidencia / revisor | Histórico `18d2661` / V | O | Captura nacional, SQLite y campañas |
| `docs/widetech-official-phase5.md` | Evidencia / revisor | Histórico `0f97e1f` / V | O | Continuidad; alta interior modificada después |
| `docs/guia-comprobaciones-oracle-fase6.md` | Procedimiento / operador | Reconciliado con reporte posterior, sin SSH / U | O | Guía interna; overrides ausentes del checkout |
| `docs/widetech-official-phase6-campaign-analysis.md` | Método y límites / revisor | Análisis parcial histórico del 14 de octubre / U | O | No cierra fase 6; evidencia privada enlazada |
| `docs/auditoria-api-oficial.md` | Auditoría inicial / revisor | Propuestas superadas / U | O | Antecedente subordinado a decisiones |
| `docs/prompt-integracion-api-oficial.md` | Encargo antiguo / revisor | Sustituido / U | O | Complementa auditoría API; no instrucción vigente |
| `docs/antecedentes-i1-i4.md` | Evidencia histórica / revisor | Nuevo traslado | O | Texto completo del README previo; no manual actual |
| `docs/auditoria-documental.md` | Trazabilidad / mantenedor y evaluador | Nuevo | P | Inventario y matriz; no especificación de negocio |

### Artefactos, fuentes y evidencia fuera de docs

| Archivo o conjunto completo | Propósito / público | Vigencia y relación | Sensibilidad / Git |
|---|---|---|---|
| `output/pdf/GPS_EMI-referencia-comandos.pdf` | Referencia portátil / operador | Ocho páginas, 14 de octubre, código `a8f3f24`; derivado de fuente siguiente | O / U: contiene host, ruta de clave y ejemplos operativos |
| `tmp/pdfs/build_commands.py` | Fuente ReportLab / editor | Contenido embebido, no generado desde Markdown | O / U; conservar con PDF y anonimizar conjuntamente antes de publicar |
| `tmp/pdfs/updated-1.png` a `updated-8.png`, `updated-review.png` | Vistas / editor | Ocho páginas y montaje; comandos no totalmente sincronizados con PDF | O / U; no captura actual certificada |
| `tmp/pdfs/commands-1.png` a `commands-7.png`, `review.png`, `renamed-5.png` | Revisiones anteriores / editor | Derivados del mismo PDF; no manual independiente | O / U |
| `data/phase6-analysis-20261014/report.md` | Informe empírico / operador autorizado | Informe privado completo; origen del resumen de fase 6 | R / I |
| `data/phase6-analysis-20261014/analyze.py`, `scenarios.py` | Método / analista | Fuentes de informe, métricas, escenarios y gráfico; leídas, no ejecutadas | R / I; referencias operativas |
| `data/phase6-analysis-20261014/metrics.json`, `vehicles.json`, `transitions.json`, `gaps.json`, `out_of_order.json`, `scenarios.json` | Derivados / analista | Respaldan informe; no logs completos del servicio | R / I |
| `data/phase6-analysis-20261014/selected-timeline.csv`, `run-summary.txt`, `quality.svg` | Cronología, salida y gráfico / analista | Evidencia de campaña, no de imagen desplegada | R / I |
| `build/phase2-review.diff`, `staged-review.diff`, `staged-review.json`, `phase3-reviewed-staged.json`, `phase5-commit-manifest.json`, `phase5-reviewed-index.sha256`, `phase5-regression-a.txt` | Evidencia auxiliar / mantenedor | Cierres locales; último TXT vacío, no acredita pruebas | O / I; inventariados, no certificados como fuente normativa |
| `build/phase2-paths.txt`, `phase3-files.txt`, `phase3-commit-paths.json` | Listas / mantenedor | Apoyo a selección de cierres; subordinadas a Git | O / I |
| `build/doc_finish.py`, `phase3_close_docs.py`, `phase3_docs.py`, `reconcile_docs.py` | Fuentes de ediciones / mantenedor | Scripts históricos; no ejecutar para restablecer estado vigente | O / I |
| `build/audit_staged.py`, `entropy_review.py`, `final_staged_check.py`, `phase3_review.py`, `prepare_selection.py`, `resolve_entropy.py`, `verify_commit.py` | Auditoría/selección / mantenedor | Auxiliares históricos; se consultaron patrones existentes, sin ejecutar mutaciones de Git | O / I |
| `tests/fixtures/emi_amb20.json` | Mapping / desarrollador | Cuatro identificadores observados; calificarlos antes como no sensibles no equivale a consentimiento de publicación | O / V |
| `tests/fixtures/render_excel.xml`, `widetech_status_109_synthetic.xml`, `widetech_status_108.xml` | Contrato / desarrollador | Primeros dos sintéticos; último transcribe estructura reportada de otro método, no error real RenderExcel | P / V |
| `.codemapignore` | Inventario auxiliar / desarrollador | Preexistente; sin función de runtime | P / U; preservado |

Se excluyen dependencias, caches, bytecode, bases de pruebas y salidas generadas sin
función documental. `.env` y `data/gps_observations.db` son configuración/datos
operativos, no documentación; preservados y fuera del contenido público. Dockerfile,
Compose, pyproject y requirements se leyeron como evidencia, sin editarlos.
No se encontró otro PDF fuera de dependencias. Los scripts/resultados auxiliares
de esta auditoría se dejan en `build/`, ignorado; no son otro manual ni aplicación.

## Sensibilidad del historial local

Recorrido efectuado con Git y Python: `git for-each-ref`,
`git rev-list --objects --all --reflog` y `git cat-file`. Abarcó **24 commits y
381 blobs únicos, 5.369.123 bytes**. Incluyó rama local, ref remota almacenada
`origin/master` y refs internas de Codex presentes; había 30 entradas de reflog.
Una ref remota local no equivale a GitHub. No hubo fetch ni revisión de objetos
huérfanos no alcanzables desde refs/reflogs. Los patrones omiten binarios; el PDF
se revisó aparte mediante extracción de texto.

`gitleaks`, `detect-secrets` y `trufflehog` no estaban disponibles en PATH. Se
buscaron claves privadas, formatos de tokens, JWT, credenciales en URL, literales
de credenciales/Parameters, cadenas de alta entropía, IP e identificadores
operativos. La salida del escáner contiene ruta, blob, línea y categoría, **sin
valores detectados**. Son heurísticas, no certificación de ausencia de secretos.

Hubo 26 coincidencias de literales, 10 de entropía, 93 de IP y 1.050 de identificadores
entre versiones; no son cantidades de secretos únicos. No hubo coincidencias de
formatos de claves privadas, tokens conocidos, JWT ni credenciales en URL bajo esas
reglas. Se distinguieron construcción de cuerpos HTTP y datos sintéticos de tests
de un literal opaco `PARAMETERS` en `gpspace_loaddatalog.py:13` del commit inicial
`286c343`, trasladado luego al proveedor y retirado mediante `fbe41e4`.

### Evidencia específica de Parameters

La revisión del código precisa la clasificación inicial del literal: **Parameters
es un cuerpo ofuscado ligado al contexto de sesión, no evidencia de una credencial
autónoma**. En `src/gps_emi/providers/load_data_log.py`, `build_parameters`
(línea 104) usa `session.uid` como `strUserID`, conserva los siete campos de
estado y añade `bolAddDriver`; `generate_parameters` (línea 127) usa
`session.uname` para ofuscar el JSON. No toma la cookie como entrada ni incorpora
un TTL o fecha de expiración. Con los mismos insumos genera el mismo resultado.

`src/gps_emi/providers/widetech.py`, función `load_data_log`, exige por separado
`GPSPACE_COOKIE` y la envía en el encabezado Cookie. Sin ella termina antes de
HTTP; 401/403 y redirecciones de autenticación terminan la sesión. El cambio
`fbe41e4` reemplazó el literal por generación dinámica: la cookie ya se obtenía
externamente en el commit inicial `286c343` y siguió separada después del cambio.
Se contrastaron esas revisiones mediante Git y AST, sin imprimir valores.

El operador informa que **las cookies históricas vencieron**. Eso es evidencia
reportada, no una validación del servidor realizada aquí. El código respalda la
separación entre payload y autenticación; no permite fechar la caducidad efectiva
de aquellas cookies ni afirmar que Parameters caduque por sí mismo. No se deduce
la necesidad de rotar una credencial únicamente de la entropía del literal.
Su contexto interno puede requerir tratamiento de privacidad aunque no autentique.

El 19 de octubre se ejecutaron ocho casos offline existentes de
`tests/test_load_data_log.py`: roles y orden del payload, generación de la petición,
ausencia de cookie y estados terminales parametrizados. **8 aprobados, 0,68 s**,
sin HTTP real, sin alterar tests. Los vectores de prueba son sintéticos.

La documentación visible usa ahora ejemplos sintéticos y parámetros de instalación.
Los identificadores observados en fixtures e historial siguen fuera del saneamiento
documental: revisar procedencia y autorización antes de publicar el repositorio
completo. No se reescribe Git ni se revocan sesiones en este incremento.

## Matriz de desajustes

Las secciones localizan el texto previo; «resuelto documentalmente» no implica
validación operativa. Los acuerdos y aplazamientos se mantienen intactos.

| ID | Archivo / sección | Evidencia sin datos sensibles | Acción | Estado |
|---|---|---|---|---|
| D01 | README, Arquitectura/Pendiente | Una vigilancia, adquisición directa y Docker futuro frente a runtime y fases 1–5 | Presentación actual; traslado histórico saneado, original privado conservado | Resuelto documentalmente |
| D02 | README e índice, estado | Resumen omitía `a8f3f24`; confirmación presente en código y tests | Actualizar código de referencia sin atribuir despliegue | Resuelto documentalmente |
| D03 | Guía, Llegadas; operación, Consola | Alta inmediata con opción de cancelar frente a confirmación previa implementada | Documentar alta y exterior fresco antes de llegada/presencia | Resuelto documentalmente |
| D04 | Collector, Identidad/campañas | STALE solo diagnóstico contradice `Continuity.observe` | Remitir a fase 5, preservar diagnóstico GPSFix | Resuelto documentalmente |
| D05 | Decisiones, Estado posterior | Fase 5 sin commit frente a `0f97e1f` | Separar encargo original y versionado posterior | Resuelto documentalmente |
| D06 | Fases 3–5, introducción | «Sin commit» puede confundirse con estado actual | Rótulo histórico y hash; conservar evidencia original | Resuelto documentalmente |
| D07 | Mantenimiento, §§1 y 3–9 | Duplicación de guía, reglas, operación y comandos | Conservar evolución, mapa y verificación; enlaces a referencias dueñas | Resuelto documentalmente |
| D08 | Selección, diagrama/CREATE_WATCH | Snapshot llamado persistido, aviso interior anterior | Corregir memoria y enlazar confirmación | Resuelto documentalmente |
| D09 | Campañas, introducción/límites | «Sin despliegue» y «no hay fase 5» sin contexto | Delimitar historia y subsistema vigente | Resuelto documentalmente |
| D10 | Oracle, §§1–4, 8 y 10 | Análisis posterior/fuente PDF reportan nombres nuevos, mismo proyecto y override adicional | Reconciliar comandos, comprobar recursos históricos antes de reversión | Texto resuelto; verificación remota pendiente |
| D11 | Análisis fase 6, Contradicciones | Tres hallazgos históricos ahora corregidos | Añadir seguimiento sin borrar tabla histórica | Resuelto documentalmente |
| D12 | PDF pág. 5, fuente y PNG | Host/ruta de clave y ejemplos operativos; previews desfasadas | Conservar originales privados; generar desde Markdown saneado y revisar cada página | Resuelto documentalmente |
| D13 | Historial, literal PARAMETERS | Literal temprano retirado por `fbe41e4` | Contrastar generación, cookie separada e historial; registrar caducidad reportada | Naturaleza aclarada; privacidad histórica pendiente |
| D14 | Historia documental y fixture observado | Identificadores reales llamados antes no sensibles | Sustituir ejemplos documentales y conservar originales privados | Documentos saneados; fixture e historial pendientes |
| D15 | Guía Oracle/estado general | Reportes y campaña no determinan imagen actual | Separar código, pruebas, reporte y aceptación por escenario | Límite explícito; imagen no comprobada |
| D16 | PER-03/TEC-08, fase 6 | Retención aprobada sin implementación de purga técnica | Mantener pendiente, sin añadir código ni borrar datos | Fuera del alcance documental |
| D17 | Análisis fase 6, informe privado | Evidencia ignorada, ausente de un clon | Retirar enlaces y comandos dependientes del informe privado; conservar método y límites | Resuelto; reproducción empírica requiere evidencia privada |
| D18 | README, Instalación | Manifests existentes; instalación limpia/build no ejecutados ahora | Instrucciones y ayudas locales con alcance de verificación | Ayudas comprobadas; instalación limpia pendiente |
| D19 | .gitignore, artefactos | Temporales, overrides y derivados privados podían incorporarse por accidente | Exclusiones selectivas; excepción para PDF final y .env.example | Resuelto; no afecta archivos ya versionados |
| D20 | README y documentación pública | Nombres técnicos no acreditan afiliación o permiso de terceros | Presentación neutral, ejemplos sintéticos; conservar campos y comandos reales | Resuelto editorialmente; autorización externa no inferida |

## Ubicación y fuente canónica final

| Antes | Ahora / responsabilidad |
|---|---|
| README extenso, mezcla histórica y actual | README: presentación e instalación; `docs/antecedentes-i1-i4.md`: evolución I1–I4, saneada y rotulada |
| Índice cronológico disperso | `docs/README.md`: navegación por necesidad y estado |
| Arquitectura y uso repetidos en mantenimiento | `guia-del-sistema.md`: componentes; `operacion.md`: configuración; `manual-mantenimiento.md`: módulos y verificación |
| Acuerdos y fases mezclados | `decisiones-arquitectonicas-renderexcel.md`: acuerdos/aplazamientos; fases: evidencia fechada |
| SQLite y recuperación repetidos | `base-de-datos.md`: esquema; `procedimientos-recuperacion.md`: incidentes |
| Catálogo PDF embebido en fuente temporal | `comandos-whatsapp.md` y `operacion.md`: contenido; `generar-referencia-comandos.py`: generador; PDF: derivado |

La tabla de inventario anterior describe el material recibido, no su autorización
de publicación. La edición final de Markdown y PDF sustituye ejemplos identificables;
conserva geocercas, campos, módulos y contratos técnicos necesarios. El título público
es neutral. Las fuentes privadas originales, PNG históricos e informe de campaña
siguen ignorados; no se requieren para instalar el sistema desde un clon.

El generador documental requiere ReportLab en el entorno del editor (no en el
runtime del sistema). Desde la raíz: `python docs/generar-referencia-comandos.py`.
Lee ambos Markdown completos; incluye sus SHA-256 en metadatos, no vuelve a
mantener un catálogo paralelo. El antiguo script temporal delega en esa fuente.

## Verificación del incremento

Primera pasada: **24 Markdown, cero enlaces locales rotos, cero cercas abiertas
y ocho ayudas CLI con salida 0**, usando Python 3.14.2. Las ayudas no iniciaron
adquisiciones. El contraste puntual de Parameters añadió los ocho casos offline
indicados arriba; no se ejecutó una nueva regresión completa. Las cifras históricas
en los documentos mantienen su fecha y procedencia.

El cierre comprueba enlaces también frente a exclusiones Git, preservación SHA-256
de código/tests/configuración, bloques Markdown, `git diff --check`, exclusiones
selectivas y texto/metadatos del PDF. Los originales privados se conservan con
manifiesto. El PDF se renderiza para inspección visual de todas sus páginas.
Resultado final del 20 de octubre: **24 Markdown, cero enlaces rotos o dirigidos
a archivos ignorados, cero cercas abiertas y `git diff --check` sin errores**.
Diez comprobaciones de inclusión/exclusión Git aprobadas. Los hashes de código,
tests y configuración permanecen iguales al estado inicial; las excepciones
autorizadas son documentación, `.gitignore`, PDF y su fuente temporal delegada.
El PDF tiene **siete páginas**, todas renderizadas e inspeccionadas visualmente;
se corrigió un encabezado aislado. Sus metadatos coinciden con los SHA-256 de las
dos fuentes actuales y no contiene adjuntos. La búsqueda final en Markdown y
texto/metadatos del PDF no encontró los identificadores operativos conocidos,
rutas personales, nombres privados de infraestructura ni IP externas bajo las
reglas usadas. Es una comprobación acotada, no una garantía de anonimato integral.

No se ejecutaron instalación limpia, build Docker, migraciones, servicios,
llamadas autenticadas ni validación en producción. No se identifica una imagen
desplegada. `.env` solo participó en el hash de preservación, sin imprimir su
contenido ni cargarlo como configuración. No hubo commit, push ni publicación.

## Pendientes reales para un segundo incremento

- Revisar fixtures observados e historial antes de publicar el repositorio completo;
  decidir su tratamiento y verificar derechos sobre material de terceros. El
  saneamiento documental no garantiza ausencia de información sensible en todo Git.
- Completar evidencia operativa de fase 6 con responsable autorizado: imagen efectiva,
  escenarios faltantes, permisos/volúmenes y recuperación. No convertir el reporte
  parcial ni la campaña privada en aceptación integral.
- Mantener PER-03/TEC-08 pendiente: la retención técnica aprobada no implementa por
  sí sola una purga. Cualquier incremento funcional requiere alcance separado.
- Verificar instalación limpia/Python mínimo y presentación Mermaid en el destino
  de portafolio. No hace falta construir una demo para describir el sistema existente.

## Plan de commits y asignación por rol

Asignación registrada el 20 de octubre de 2026 por petición del usuario. El encargo inicial fue solo de planificación. La solicitud posterior de aplicar
el logo y realizar el commit autoriza versionar C01–C02; los demás trabajos
siguen como plan, sin tareas enviadas a terceros. Los identificadores
C01–C15 son unidades de trabajo, no hashes Git. Los responsables quedan asignados
por función; no se presupone que una persona haya aceptado una tarea. La ejecución
funcional, las intervenciones operativas y la publicación conservan sus límites
de autorización. Este plan no modifica acuerdos ni activa aplazamientos.

### Control obligatorio de secretos en cada commit

Por instrucción del usuario, **siempre revisar que no se filtren secretos**:
antes de preparar un commit y de nuevo sobre su contenido exacto antes de crearlo
o compartirlo. Se aplica también a cambios pequeños, tests, fuentes documentales,
PDF, imágenes, metadatos, adjuntos y mensajes de commit.

El ejecutor inspecciona solo los archivos previstos y el diff; el revisor de
seguridad comprueba valores de credenciales, cookies, tokens, claves, URL
autenticadas, identificadores operativos y datos privados de infraestructura.
Las salidas compartidas registran categoría, archivo y ubicación, nunca el valor.
No volcar `.env`, configuración expandida, logs o bases para efectuar la revisión.
Combinar patrones con lectura contextual: nombres de variables y ejemplos
sintéticos no son por sí mismos secretos. En binarios, extraer texto/metadatos
y revisar visualmente; una búsqueda sin coincidencias no garantiza ausencia.

Comprobar la lista exacta del índice antes del commit y evitar incorporaciones
globales indiscriminadas. `.gitignore` no protege contenido ya versionado. Si
aparece material sensible, detener esa unidad, sanearla preservando el original
privado y repetir la revisión; si está en historial, registrar la remediación
sin reescribirlo ni revocar credenciales automáticamente. Antes de publicar,
repetir la revisión sobre todo el conjunto publicable y el historial disponible.
La comprobación del incremento actual no sustituye estos controles futuros.

### Cambios existentes listos para preparación selectiva

| ID / mensaje de commit previsto | Responsable asignado | Revisor | Contenido exacto y criterio de cierre | Dependencia / estado |
|---|---|---|---|---|
| C01 · `chore: excluir configuración y artefactos privados` | Mantenimiento del repositorio | Seguridad y privacidad | Solo `.gitignore`. Mantener visibles Markdown, generador, ejemplos permitidos y PDF final; comprobar exclusiones de overrides, temporales y originales privados. Aplicar control de secretos. | Completado: `9e84f1d`; exclusiones y diff revisados |
| C02 · `docs: reorganizar y sanear documentación del sistema existente` | Documentación técnica | Mantenedor de aplicación y seguridad | `README.md`, los 23 Markdown actuales de `docs/`, `docs/generar-referencia-comandos.py`, `docs/assets/gps-emi-logo.png` y `output/pdf/GPS_EMI-referencia-comandos.pdf`. Incluye el plan presente y los cambios documentales previos integrados. Cerrar con enlaces válidos, acuerdos preservados, hashes de fuentes PDF coincidentes, revisión visual y control de secretos. | Después de C01; incluido en el commit que incorpora esta revisión y el logo |

C02 permanece unido porque el README, índice, fuentes canónicas, antecedentes,
auditoría y PDF se enlazan entre sí. Dividirlo por archivo dejaría referencias
incompletas o un PDF desfasado en commits intermedios. Los originales, renders,
scripts auxiliares de `build/` y wrapper temporal no forman parte de C02.
El wrapper local se preserva fuera de Git; el generador publicable está en `docs/`.

### Pendientes asignados y commits futuros

Todos requieren el control obligatorio de secretos anterior, además del criterio
específico de cada fila. Un resultado que no exige cambiar archivos no justifica
un commit vacío: se registra su evidencia saneada en el documento dueño del tema.

| ID / mensaje previsto | Responsable asignado | Revisor | Alcance y criterio de cierre | Dependencia / estado |
|---|---|---|---|---|
| C03 · `test: sustituir fixtures operativos por datos sintéticos` | Mantenedor de pruebas | Seguridad y mantenedor de aplicación | Revisar `tests/fixtures/emi_amb20.json` y consumidores; sustituir identidades observadas conservando semántica y cobertura, revisar fixtures restantes. Pruebas afectadas aprobadas, sin alterar comportamiento. Vincula D14. | Tras C02; asignado, fuera del incremento documental |
| C04 · `docs: registrar revisión de privacidad del historial y derechos` | Seguridad y privacidad | Responsable del proyecto | Actualizar esta auditoría con procedencia, alcance local revisado y tratamiento decidido de material histórico/terceros; distinguir Parameters de autenticación y caducidad reportada. No copiar valores ni inferir autorización. Una eventual reescritura sería una actuación separada. Vincula D13/D14/D20. | Tras C03 y evidencia del responsable; asignado, publicación pendiente |
| C05 · `docs: verificar instalación limpia y presentación del portafolio` | QA de compatibilidad | Documentación técnica | Verificar instrucciones del README en entorno aislado, Python mínimo declarado y entorno actual; registrar plataforma, dependencias, resultados y render Mermaid en el destino elegido. Sin arrancar proveedores ni servicios. Si requiere fixes funcionales, separarlos del commit documental. Vincula D18. | Tras C02; asignado, requiere entorno/destino |
| C06 · `docs: registrar identidad y comprobaciones de la instalación` | Operación de infraestructura | QA operativo | Completar guía de fase 6 con evidencia saneada de versión de checkout e imagen por separado, servicio/proyecto/contenedor, UID, permisos, volumen, exclusión local y recursos. No publicar nombres privados ni salidas de entorno. Vincula D10/D15 y validación Windows/Ubuntu. | Tras C02; asignado, ejecución operativa pendiente |
| C07 · `docs: registrar aceptación por escenario de fase 6` | QA operativo | Operador autorizado y mantenedor de aplicación | Registrar consultas nacionales, sedes, alta interior, salida/regreso, frescura, recuperación, gestión, campañas y exportación según la guía; distinguir evento, intento, aceptación y entrega. Confirmar mapping TEC-02 cuando haya evidencia. Casos no observados permanecen abiertos. No inducir movimientos, errores ni ráfagas. | Tras C06; asignado, ejecución operativa pendiente |
| C08 · `docs: acreditar respaldo restauración y reversión compatibles` | Operación de infraestructura | Mantenedor SQLite | Ensayo aislado de restauración, integridad y compatibilidad con binario/esquema; evidencia de reinicio y plazo original de campaña. Reversión real solo con ventana autorizada, respaldo verificado y escritores controlados. Sin bases ni CSV en Git. Vincula TEC-08. | Tras C06; asignado, ejecución operativa pendiente |
| C09 · `feat: aplicar retención técnica aprobada` | Mantenedor de persistencia | Mantenedor de aplicación y QA | Concretar inventario técnico de PER-03/TEC-08 e implementar los 30 días aprobados, preservando históricos/eventos permanentes. Incluir pruebas temporales de fronteras, integridad, concurrencia y reinicio; actualizar SQLite/operación. No purgar base operativa en este trabajo. | Tras inventario TEC-08 y alcance de implementación separado; asignado, no ejecutado |
| C10 · `docs: registrar cierre verificable de fase 6` | QA de integración | Responsable del proyecto | Consolidar regresión fechada, instalación, evidencias operativas y retención verificada. Actualizar estado en índice, auditoría y fase 6 solo donde exista evidencia; regenerar PDF si cambia operación/comandos. Límites externos no observados siguen explícitos. | Tras C05–C09; asignado, cierre condicionado |
| C11 · `chore: documentar exclusiones locales de Codemap` | Mantenimiento del repositorio | Responsable del proyecto | Resolver el archivo preexistente `.codemapignore`: versionarlo solo si la herramienta forma parte del flujo adoptado; en caso contrario conservarlo local sin mezclarlo con C01/C02. Comprobar que no oculta fuentes necesarias. | Independiente; asignado, adopción pendiente |

Seguridad/privacidad es revisor obligatorio adicional de C03–C11. Publicar no es
un efecto automático de completar estos commits: la revisión de derechos y del
conjunto publicable continúa siendo necesaria.

### Aplazamientos con responsable, sin activación

| ID / commit reservado | Responsable asignado | Revisor | Condición y criterio para un futuro incremento |
|---|---|---|---|
| C12 · `feat: seleccionar flotas en campañas` · APL-01 | Mantenedor de collector | Responsable de producto y QA | Mantener aplazado hasta el incremento correspondiente; selección por `fltName` sin alterar identidad, adquisición central ni política nacional aprobada. Definir pruebas de selección y persistencia al activar su alcance. |
| C13 · `feat: restaurar vigilancias tras reinicio` · APL-02 | Mantenedor de vigilancias | Responsable de arquitectura y QA | Mantener comportamiento actual en memoria. Antes de implementar, acordar el contrato de restauración y validar propietario, vencimiento, frescura y ausencia de avisos duplicados. |
| C14 · `feat: informar desapariciones y causas de finalización` · APL-03/APL-04 | Mantenedor de WhatsApp | Responsable de producto y QA | Reservado, aplazado. Concretar cada mensaje y sus condiciones sin confundir evento, intento, aceptación o entrega. Separar en dos commits si sus alcances o validaciones no son atómicos. |
| C15 · `feat: presentar información y advertencias de flota` · APL-05 | Mantenedor de WhatsApp | Responsable de producto y QA | Reservado para el incremento de integración previsto; sin extender vigilancias fuera de Medellín ni reabrir COB-03/VIG-11. No bloquear por ello la recuperación ya aprobada. |

Los límites del proveedor (cobertura, envoltura real de errores y cuota efectiva)
quedan asignados a **responsable de integración externa**, con revisión de QA.
Se registrarán en C07/C10 únicamente si aparece evidencia válida; no autorizan
pruebas de carga ni constituyen defectos que puedan cerrarse con datos sintéticos.
La ausencia de informe privado en el clon público es intencional (D17), no un
pendiente para incorporar datasets. Los TEC ya resueltos y D01–D12/D17/D19
corregidos documentalmente no se reabren mediante este plan.

### Secuencia y seguimiento

Preparación documental: C01 → C02. Después pueden avanzar por separado privacidad
(C03 → C04), compatibilidad (C05), validación operativa (C06 → C07/C08) y retención
(C09, con inventario y alcance habilitados). C10 integra los resultados sin
equiparar un commit a validación en producción. C11 es independiente y C12–C15
permanecen aplazados.

Cada responsable actualizará en esta sección estado, evidencia saneada, revisión
de secretos y hash real cuando exista. No marcar «cerrado» por asignación,
planificación o mero versionado. La planificación no creó commits ni avisos a
terceros. C01–C02 se versionan por la autorización posterior; su ejecución se
registra a continuación.


## Presentación del README y versionado autorizado

El 20 de octubre el usuario aportó el logo y solicitó un README profesional y su
commit. La presentación incorpora cabecera, navegación, stack, diagrama Mermaid
y evidencia técnica, sin añadir funcionalidades ni afirmar validación externa.
`docs/assets/gps-emi-logo.png` conserva los bytes del PNG aportado y su
transparencia. El contenedor PNG incluye procedencia C2PA (`caBX`), que se conserva;
no contiene chunks de texto libre o EXIF. La revisión de metadatos distingue
coincidencias heurísticas en datos binarios de credenciales reales. El aporte
del usuario autoriza incorporarlo aquí, sin acreditar titularidad de terceros.

El contenido del PDF no cambia: sus fuentes son comandos y operación. Se
regenera únicamente para sincronizar las huellas tras normalizar sus fuentes a
LF; las siete páginas renderizadas coinciden píxel a píxel con las ya revisadas.
La visualización del Mermaid en el destino final sigue dentro de C05.
El commit documental incluye las referencias pendientes necesarias para que los
enlaces existan en un clon; `.codemapignore` y los originales privados quedan fuera.


C01 quedó versionado en `9e84f1d`. C02 incorpora esta revisión, por lo que su hash
se consulta con `git log -1 -- README.md` después del commit, sin introducir una
autorrefencia circular. Se revisa el contenido exacto del índice antes de crearlo;
no se incluyen cambios de aplicación, configuración operativa, tests o datos.
La revisión de enlaces y preservación vuelve a pasar: 24 Markdown y hashes de
las fuentes del PDF coincidentes. El logo tiene transparencia y se incorpora
sin modificar sus píxeles ni su procedencia. No se realiza push ni publicación.

Al preparar el índice, Git advirtió conversión de saltos de línea del PDF.
C02 incluye `.gitattributes` para preservar PDF/PNG como binarios y las dos fuentes
canónicas del PDF con LF. Se comprueba igualdad de bytes entre índice y archivos
revisados; estas reglas no alteran configuración de producción.
