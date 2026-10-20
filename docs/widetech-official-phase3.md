# Fase 3 — catálogo nacional, consultas y reclasificaciones

> Evidencia histórica de fase, posteriormente versionada en `a171b37`.
> Las expresiones «sin commit/despliegue» inferiores describen el encargo original.
> Para el estado actual consultar el [índice](README.md); no ejecutar sus planes
> como autorización vigente.

Implementación local del 9 de octubre de 2026, sobre fase 2 versionada en
`24dae94e5994889cb0c30f8e6ad3dbd0e71f6151`. Referencia de autoridad:
[decisiones aprobadas](decisiones-arquitectonicas-renderexcel.md).
Sin llamadas a WideTech, arranque WhatsApp, cambios al .env, migración de bases
operativas, despliegue, commit ni push en este encargo.

## Integración y responsabilidades

Se conserva AcquisitionRuntime → Coordinator → SnapshotSource y los casos de
uso compartidos por CLI/WhatsApp. No hay nueva autoridad HTTP, planificador ni
adquisiciones del catálogo. El catálogo tampoco añade demanda por su cuenta.

| Componente | Responsabilidad en fase 3 |
|---|---|
| AcquisitionRuntime | En modo `--official`, inicializa el catálogo tras reservar HostLease; usa GPS_EMI_DATA_DB. El legado no deriva un catálogo oficial. |
| Coordinator | Interpreta identidades una vez, prepara snapshot, persiste catálogo y solo entonces publica. Un fallo de escritura conserva la publicación anterior. |
| SnapshotSource | Una proyección con política explícita: `query` nacional; `watch` y `collector` Medellín. Mantiene versión, origen y edad de posiciones conservadas. |
| Consultas, resolución y PendingSelections | Conservan búsquedas por móvil, placa, VEH_ID, selección y geocercas. Los candidatos llevan metadatos de la adquisición original; paginar no adquiere ni actualiza catálogo. |
| WatchManager / WatchRunner | Actualizan nombres por identidad y terminan ante flota distinta confirmada, incluso con GPS inválido. No notifican proactivamente la causa por WhatsApp. |
| FleetPolling | Distribuye publicaciones; reconcilia metadatos de vigilancias antes de procesar nuevas observaciones. Collector conserva su alcance Medellín. |
| Nuevo `catalog.py` | Responsabilidad nacional de identidad, presencia, reconciliación y persistencia. No encaja dentro de WhatsApp, monitoring ni collector. |
| Nuevo `database.py` | Extrae conexión SQLite/UTC ya usados por collector: una conexión por transacción, WAL, claves foráneas y espera de bloqueo de 0,25 s. Ambos almacenes reutilizan esta infraestructura. |

No cambian el esquema de observaciones, campañas, columnas CSV, heartbeat ni
deduplicación histórica. No se implementa fase 4 por ampliar las consultas.

## Identidad, presencia y calidad

VEH_ID es identidad; Id sigue siendo el registro GPS. La identidad debe aparecer
una sola vez y no tener errores estructurales en VEH_ID/Table. Se preservan todas
las filas de origen, incluidas otras compañías/flotas, antes de proyectarlas.

La presencia y el nombre/flota se interpretan por campo. GPS repetido, inválido,
sin coordenadas o sin Zones no impide reconocer una presencia inequívoca. Una
flota ausente/nil/vacía/ambigua no sobrescribe una flota válida anterior ni confirma
reclasificación. Los nombres válidos actualizan el catálogo aunque el GPS no cambie.
No se escoge arbitrariamente una identidad duplicada.

La calidad de ubicación conserva la política de fase 2: filas defectuosas no
congelan el lote; se conserva la última fila utilizable completa por vehículo,
sin mezclar coordenadas, fechas o zonas de reportes distintos. Los metadatos
vigentes de identidad se aplican aparte de esa posición conservada. Su epoch,
versión, acquired_at, fuente y edad siguen siendo los de la adquisición original.
Los campos originales del reporte GPS permanecen intactos.

El catálogo no restaura ubicaciones de SQLite al arrancar. Hasta el primer
snapshot se informa inicialización. Una identidad persistida sin posición
utilizable recibida en este proceso no se convierte en una ubicación actual.

## Cobertura de cada consumidor

Consultas por móvil, placa, ID y sede admiten `fltName.startswith('Ambulancias')`,
con la normalización existente NFC y eliminación de espacios exteriores. No se
añaden variantes especulativas, heurísticas de placa o filtros geográficos.
Las geocercas siguen siendo `EMI Medellin_Poblado` y `EMI_Medellin_Taller`.

Admisión de vigilancias y collector siguen limitados a `Ambulancias Medellin`
y `Ambulancias Medellín`. Ambos usan solo filas utilizables de la adquisición
actual, como en fase 2. El estado de presencia del catálogo no introduce un
nuevo veto de alta ni añade candidatos persistidos al selector. Se conserva la
política anterior de posiciones retenidas en consultas; no se aprueban propuestas
nuevas sobre ausentes y selectores. No se muestran nuevos mensajes de flota APL-05.

Renombrar no cambia VEH_ID ni interrumpe vigilancia. Una flota diferente confirmada
termina la vigilancia activa con estado terminal existente FAILED y causa interna
`fleet_changed`; no es llegada ni desaparición. FleetPolling reconcilia al recibir
la publicación, aun si la cola de observaciones está atrasada. WatchRunner también
observa publicaciones para no perder un cambio intermedio entre dos lecturas CLI.
No se llama al callback de notificación terminal WhatsApp para esta causa.
La causa queda en el estado en memoria/log técnico, sin restauración de vigilancias.

## TEC-01: política aprobada durante este encargo

El usuario aprobó expresamente el 9 de octubre esta política operacional:

1. Solo adquisiciones nuevas, no vacías, sin diagnósticos de filas ni identidades
   duplicadas, con identidad y flota interpretables en todas sus filas, cuentan
   ausencias. Cada snapshot expone `catalog.absence_eligible` separado de
   `coverage=unknown`; ser apto no certifica cobertura completa del proveedor.
2. Tras tres adquisiciones aptas consecutivas sin una identidad previamente
   conocida se marca `disappeared` y se registra un evento de desaparición.
   Significa ausencia observada; no baja definitiva ni cambio de flota.
3. Error global, fallo de persistencia o adquisición no apta reinicia todas las
   secuencias provisionales. No se unen observaciones separadas por un intento
   cuya cobertura/calidad no permite sostener la consecutividad. Inactividad sin
   intento nuevo no suma ni reinicia; releer caché tampoco.
4. Una presencia inequívoca vuelve a `present`, incluso con GPS repetido/inválido,
   y registra reaparición si el estado anterior era `disappeared`. No borra eventos.
5. El reinicio descarta contadores provisionales en memoria y conserva estados y
   eventos confirmados: se necesitan tres nuevas adquisiciones aptas para una
   nueva confirmación provisional pendiente antes de reiniciar.

No hay umbrales porcentuales ni certificación exigida al proveedor. La evidencia
disponible incluye diagnósticos individuales y filas sin flota; esos lotes no
cuentan ausencias, aunque sí actualizan presencias válidas. **Un recorte silencioso
entregado sin errores puede pasar esta política** y producir ausencia observada.
Ese límite fue presentado al usuario y aceptado; las pruebas sintéticas verifican
la política, no demuestran que WideTech entregue lotes completos.

## SQLite y consistencia

Migración aditiva, transaccional y repetible:

- `catalog_schema`: versión propia 1; no cambia `PRAGMA user_version` del collector.
- `catalog_vehicles`: identificación/flota vigentes, primera/última aparición,
  estado de presencia y últimas fechas confirmadas de desaparición/reaparición.
- `catalog_acquisitions`: clave única epoch/version, fecha y aptitud para ausencias.
- `catalog_events`: desaparición/reaparición, fecha y adquisición causante; clave
  única por identidad, tipo y adquisición. Sin historial específico de flota.

CatalogStore serializa sus escrituras y contadores con RLock; SQLite coordina con
las escrituras de campañas mediante BEGIN IMMEDIATE, WAL y espera acotada.
Cada operación abre/cierra su conexión. No hay HTTP ni notificaciones dentro de
la transacción. El esquema existente y las observaciones previas se conservan.

La transacción actualiza identidades, estados, eventos y marca de adquisición
en conjunto. La vista inmutable incluida en el snapshot se construye en esa misma
transacción y solo se entrega después de commit. Los contadores provisionales
avanzan después del commit. Repetir la misma adquisición no duplica efectos.

Coordinator publica bajo su Condition después de la escritura; queries consumen
la vista ligada a esa publicación, nunca una lectura SQLite independiente. Si
falla escritura, se descarta la candidata para consumidores, se rompe la secuencia
provisional y se aplica el backoff central con categoría `persistence`. No se
reclasifica una vigilancia con cambios no persistidos. `received()` conserva la
candidata diagnóstica, con `catalog=None` si falló su persistencia; no es publicación.

Una caída después de commit y antes de publicación puede dejar metadatos/eventos
confirmados en SQLite sin haberlos entregado a consumidores. Tras reinicio estos
se conservan, no se repiten por caché, no se restauran vigilancias ni posiciones,
y los contadores provisionales comienzan de cero. No se promete atomicidad con
notificaciones externas. La exclusión local de fase 2 sigue siendo obligatoria;
otras instalaciones/hosts no quedan coordinados.

La configuración sigue siendo GPS_EMI_DATA_DB, compartida con campañas. Su valor
predeterminado legado `data/gps_observations.db` es relativo al cwd; para una
instalación usar ruta absoluta idéntica entre CLI/servidor. GPS_EMI_STATE_DIR sigue
siendo la ruta estable de exclusión; una ruta de base distinta no crea otra autoridad.
En Docker la configuración existente apunta a /data/gps_observations.db. No se
ejecutó ninguna migración sobre la base operacional en este trabajo.

## Decisiones aplicadas y límites

ARQ-01/02/03: única adquisición, snapshots y planificación preservados.
CAT-01–09: identidad estable, metadatos, tres ausencias aptas, eventos y reinicios.
COB-01/03/04/05: consultas nacionales, vigilancia Medellín y clasificación oficial.
DAT-01/02/03/04/08: originales, conservación, advertencia, parcialidad e inicialización.
VIG-08/09/11: sin restauración, continuidad por identidad y fin por reclasificación.
PER-01/02 y VAL-01: SQLite coordinado, migración aditiva y regresión offline.
TEC-01 queda resuelto como política operacional aceptada, con su límite externo;
TEC-02 reutiliza mapping explícito y variantes ya documentadas, sin inferencias.

No se implementan campañas nacionales, deduplicación/CSV fase 4, recuperación o
vencimientos fase 5, bloqueo STALE de llegadas, restauración, mensajes proactivos,
ni limpieza HTML. GPSFix conserva su política independiente. Quedan pendientes
validación real nacional, entrega WhatsApp, Docker/Ubuntu y límites/envolturas
del proveedor; no se realizaron llamadas autenticadas ni despliegues.

## Pruebas y archivos

Las pruebas usan XML sintético y SQLite bajo basetemp temporal. Se verifican
consultas/selector nacionales, admisión Medellín, nombres, duplicados, flota
desconocida, reclasificación con GPS inválido y sin notificación proactiva,
ausencias aptas/interrumpidas, reapariciones, idempotencia, reinicios,
migración desde observaciones previas y escritura concurrente con campañas.
Un trigger de fallo demuestra rollback y conservación de publicación/vigilancias.

Resultados finales de este encargo:

- 49 pruebas específicas de catálogo, integración WhatsApp y selector: aprobadas
  en 4,80 s.
- Regresión completa: 958 aprobadas, 0 fallidas, en 28,90 s.
- `git diff --check` limpio y enlaces locales de los documentos modificados válidos.
- Se verificó también bloqueo real SQLite en una base temporal: la publicación
  anterior se conserva y la secuencia provisional se reinicia. Un esquema futuro
  desconocido se rechaza antes de crear tablas de catálogo.

Comando: `python -m pytest -q -p no:cacheprovider --tb=short
--basetemp=<directorio nuevo bajo build>`. Python 3.12 del runtime local con
`.venv/Lib/site-packages` y `src` en PYTHONPATH. Las pruebas prohíben red y usan
relojes inyectados; las conexiones SQLite se limitan a archivos temporales.
Las cifras de fase 2 y su evidencia manual siguen siendo históricas. Esta
regresión no constituye validación real de WideTech ni aceptación de despliegue.

## Archivos modificados en este encargo

- Documentación: `docs/README.md`, `docs/decisiones-arquitectonicas-renderexcel.md`,
  `docs/guia-del-sistema.md`, `docs/multiple-watches.md`, `docs/operacion.md`,
  `docs/vehicle-selection.md`, `docs/widetech-official-phase2-spec.md` y este
  nuevo documento `docs/widetech-official-phase3.md`.
- Adquisición/persistencia: `src/gps_emi/acquisition.py`,
  `src/gps_emi/acquisition_runtime.py`, `src/gps_emi/analysis/collector.py`,
  nuevos `src/gps_emi/catalog.py` y `src/gps_emi/database.py`.
- Dominio/consumidores: `src/gps_emi/monitoring/fleet_polling.py`,
  `src/gps_emi/monitoring/runner.py`, `src/gps_emi/monitoring/watches.py`,
  `src/gps_emi/queries.py`, `src/gps_emi/resolution.py`, `src/gps_emi/selection.py`,
  `src/gps_emi/whatsapp/service.py`, `src/gps_emi/whatsapp/vehicle_selection.py`.
- Pruebas: `tests/conftest.py`, nuevos `tests/test_phase3_catalog.py` y
  `tests/whatsapp/test_national_catalog.py`.

Se conservaron sin modificar `.codemapignore`, la auditoría y el prompt históricos.
El índice permanece vacío y HEAD continúa en el commit de fase 2 `24dae94`.
No hay criterios materiales pendientes para esta implementación local de fase 3;
las limitaciones externas y fases posteriores descritas arriba siguen vigentes.

## Revisión cruzada de decisiones — 9 de octubre de 2026

Se contrastaron los acuerdos con catálogo, adquisición/runtime, proyección,
consultas/selector y ciclos de vigilancia CLI/servidor, además de persistencia
compartida y documentación vigente. No se usaron propuestas históricas como
autorización para ampliar el alcance.

| Decisiones | Invariante y evidencia offline |
|---|---|
| ARQ-01/02/03 | Catálogo sin HTTP; publicación solo desde Coordinator. Regresión central de caché, exclusión, backoff y consumidores. |
| CAT-01/02/03 y VIG-09 | VEH_ID estable, etiquetas mutables, selector compartido. Renombrados y etiquetas duplicadas probados; nombres vigentes no retroceden al drenar cola. |
| CAT-04/09, COB-03 y VIG-11 | Flota interpretada por campo; otra flota confirma reclasificación, no desaparición. GPS inválido no impide ese cambio; identidad duplicada/flota desconocida no lo confirma. |
| CAT-05/06/07/08, DAT-04 y TEC-01 | Tres adquisiciones aptas nuevas, reinicio de secuencia ante fallo/lote no apto, eventos persistentes y reaparición por identidad. Caché/replay no avanzan contadores. |
| COB-01/04/05 | Consultas por prefijo oficial Ambulancias, sin inferencias geográficas; vigilancia y collector conservan Medellín. |
| DAT-01/02/03/08 | Originales GPS y procedencia conservados, advertencia de antigüedad existente y ninguna ubicación restaurada del catálogo al arrancar. |
| PER-01/02 | WAL y transacción aditiva; fallo/bloqueo SQLite conserva publicación previa. Históricos/campañas existentes siguen compatibles. |
| VIG-08 y APL-02/03/04/05 | Sin restauración de vigilancias ni mensajes proactivos nuevos de flota, desaparición o causa de fin. |
| VAL-01 | Regresión offline y casos nuevos de cola atrasada, con XML sintético y bases temporales. |

La revisión encontró una contradicción posible en FleetPolling: una solicitud
pendiente podía crearse desde una publicación antigua en cola después de haberse
confirmado otra flota. Además, procesar esa cola podía revertir un nombre vigente.
Se corrigió en el distribuidor existente: se drenan observaciones pendientes antes
de admitir nuevas vigilancias; al procesarlas se aplican los metadatos vigentes del
catálogo sin cambiar sus registros GPS originales. Dos pruebas reproducen estos
casos. No se añade otro planificador ni se descarta la cola para resolverlos.

Los acuerdos COB-02/COL, DAT-06/07 relativos al histórico, continuidad VIG-03–07/10,
retención PER-03 y despliegue DEP siguen asignados a fases 4–6. El comportamiento
STALE aún diagnóstico del monitor no se presenta como cumplimiento de VIG-10.
TEC-02 conserva mapping explícito: su correspondencia con datos reales sigue
requiriendo verificación externa, no inferencias ni una nueva decisión de cobertura.
La frase de autorización documental original del registro se precisó para no
contradecir los encargos posteriores de implementación local.

Esta revisión no garantiza ausencia de cualquier defecto futuro. Sus garantías
están acotadas por las pruebas y por una autoridad local correctamente configurada;
no certifica cobertura completa de WideTech ni coordinación entre instalaciones.
El límite de recortes silenciosos de TEC-01 permanece expresamente aceptado.

Validación de esta revisión: 27 pruebas específicas de catálogo/WhatsApp aprobadas
en 2,91 s; regresión completa de 960 pruebas aprobadas en 25,91 s. `git diff --check`
sin errores. Se modificaron FleetPolling, sus pruebas en `test_phase3_catalog.py`,
este documento y la precisión de autoridad en el registro de decisiones. Sin
llamadas al proveedor, cambios de .env/base operativa, commit ni push.

## Versionado selectivo posterior

Por indicación posterior del usuario se prepara el commit de fase 3 antes de
continuar fase 4. Incluye los 24 archivos enumerados arriba y las correcciones
de cola atrasada de la revisión. Se separaron los cambios incipientes de fase 4
en adquisición, modelos, catálogo y collector; no forman parte del commit.
También se excluyen `.codemapignore` y los dos documentos históricos ajenos.

Sobre el árbol de fase 3 aislado se ejecutó nuevamente la regresión completa:
960 pruebas aprobadas en 25,84 s. Revisión íntegra del diff staged y archivos
nuevos, comprobación de rutas excluidas y búsqueda local de patrones de secretos
sin hallazgos; gitleaks, detect-secrets y trufflehog no están disponibles en el
entorno. Los identificadores/teléfonos de las pruebas nuevas son sintéticos.
Se verifica `git diff --cached --check` y el contenido final del índice antes de
confirmar. No se incluyen .env, datos operativos, SQLite ni artefactos de build.
El hash resultante se informa en la entrega; no se hace push ni despliegue.
Los apartados anteriores conservan las condiciones de sus encargos originales.
