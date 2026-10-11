# Fase 4 — collector nacional y campañas

Implementación local del 9 de octubre de 2026. Base: fase 3 versionada previamente,
por indicación del usuario, en `a171b378eb29fba95094c316c01eb9e8f5b5c81d`.
[Decisiones aprobadas](decisiones-arquitectonicas-renderexcel.md) prevalecen sobre
las políticas antiguas de heartbeat, última fila y alcance Medellín del collector.
No se modificó .env ni una base operativa; no se llamó WideTech/Meta, no se inició
WhatsApp, no se desplegó ni se hizo commit/push de fase 4.

## Componentes y contrato compartido

| Existente | Evolución |
|---|---|
| AcquisitionRuntime → Coordinator | Misma autoridad y planificador. Snapshot incorpora started_at del intento HTTP. |
| Snapshot / SnapshotSource | observations guarda filas utilizables recibidas; operational conserva última posición sin retroceder GPS. Una proyección, propósito collector nacional con originales. |
| FleetPolling | Entrega cada publicación al collector con inicio/fin; vigilancia sigue usando purpose=watch Medellín. |
| Vehicle | Campos opcionales de procedencia y originales para transportar la observación hasta la persistencia; legado queda sin metadatos inventados. |
| ObservationStore | Misma infraestructura database.py; claves globales, metadatos, colisiones y marca histórica. |
| SessionStore / SessionCollector | Asociaciones, admisión durable, reintento acotado y ventanas de interrupción; mantiene CLI de campañas. |
| export_observations / collector CLI | Exportación global/por campaña compatible con versiones previas, columnas nuevas al final. |
| CatalogStore | Acepta user_version=3 compartido; conserva esquema propio y eventos. |

No se crearon módulos ni servicios de negocio adicionales. Claves, asociaciones
y admisiones pertenecen a los almacenes existentes. No hay HTTP del collector,
ni fuente paralela para WhatsApp o CLI. El catálogo no exige absence_eligible al
collector: calidad individual y aptitud para contar ausencias son distintas.

## Captura y temporalidad

En RenderExcel, fltName normalizado debe empezar por Ambulancias. No se infiere
flota ni identidad; no hay selección manual APL-01. Cada fila exige la misma calidad
utilizable de fase 3 (identidad inequívoca, GPS/coordenadas/flota/Zones conocidos y
sin diagnósticos individuales); otra fila defectuosa no congela el lote.
Un GPSFix cero conserva la política existente. Filas retenidas no se recopilan.

observations contiene las filas recibidas que pasan esa política, incluso GPS
fuera de orden. operational conserva su registro anterior íntegro con motivo
out_of_order cuando llega un timestamp menor, sin refrescar su procedencia ni edad.
Consultas y vigilancias no retroceden. El catálogo puede actualizar nombre/flota
porque presencia y calidad GPS siguen separadas. La proyección del collector no
superpone el catálogo: conserva las etiquetas/flota del reporte original.
El legado usa la misma ruta de persistencia con metadatos oficiales NULL; su
fuente explícita mantiene el alcance disponible, sin fingir cobertura nacional.

## TEC-03 — identidad de observación

Clave SHA-256 de una serialización JSON estable de:

- Procedencia (método oficial o namespace interno legacy), VEH_ID e instante GPS.
- Coordenadas, velocidad, ignición, GPSFix, zonas normalizadas y Zones original,
  y ubicación reportada.

El instante oficial se interpreta con WIDETECH_TIMEZONE y se normaliza UTC;
FechaGPS original permanece aparte. El legado conserva su tiempo naive sin
inventar offset. No se deduplica entre fuentes cuya equivalencia no está probada.
No se incluyen etiquetas, nombre, flota, FechaServidor ni Id en la identidad GPS.
Id se guarda como referencia, sin asumir unicidad global ni equivalencia con VEH_ID.
Un cambio solo de nombre/flota/Id no añade GPS ni reescribe sus originales.

La tabla observation_keys cubre todo el histórico, no solo la última fila. Una
repetición se omite aunque pase el heartbeat o reinicie el proceso. Otro contenido
con igual timestamp se conserva con timestamp_collision=1. Un reporte único anterior
al mayor instante almacenado del mismo proveedor/VEH_ID se marca historical=1.
No se reetiquetan retroactivamente observaciones que ya existían. Sin identidad o
fecha no se inventa una clave; las filas legadas previas sin ellas se preservan.

collection_observations enlaza cada campaña y observación una sola vez, guardando
su primera recepción en esa campaña. Una campaña nueva puede asociarse al mismo
GPS sin duplicarlo. La observación conserva su acquired_at, etiquetas y metadata
de primera incorporación. La asociación nueva no prueba un GPS nuevo ni presencia
física continua. collection_session_id original permanece por compatibilidad;
la tabla de asociación es la autoridad para conteos y exportación por campaña.

## TEC-04 — admisión, carreras y cierre

Ventana de campaña [inicio, fin). El inicio HTTP y acquired_at deben estar dentro;
no se admite una petición que ya estaba en vuelo antes de start. Igualdad con el
inicio se admite a la resolución del reloj. Adquisiciones futuras respecto al reloj
del escritor se rechazan. No hay entrega de snapshot previo por iniciar campaña.
Se requiere sincronización del reloj del host; no se afirma inmunidad a saltos.

submit copia el lote a una cola limitada (32). Esa operación no autoriza escritura.
El worker abre BEGIN IMMEDIATE y comprueba estado COLLECTING, ventana de adquisición
y vigencia actual. Confirma collection_batches con token y estado admitted: ese es
el inicio durable de escritura. Stop/admisión se serializan por SQLite. Stop que
confirma primero impide admitir; admitted que confirma primero permite completar
sin extender la campaña, aunque stop o vencimiento ocurran antes de terminar.

Una segunda transacción escribe GPS, claves, asociaciones y written en conjunto.
Error hace rollback de todo ese conjunto; la admisión sigue disponible. Reintentar
el mismo token tras el cierre completa el lote, y un token written no repite efectos.
El worker hace dos intentos como máximo, sin otro HTTP ni reintento de notificaciones.
Cola no admitida consumida tras stop/fin se rechaza. El cierre intenta drenar en el
plazo acotado existente; no amplía planned_end_at ni restaura vigilancias.

Saturación, fallo SQLite persistente o cierre forzado pueden perder muestras.
La cola no es durable: admitted sin written identifica escritura incompleta pero
no permite reconstruir su payload tras caída. Esta limitación de fallos externos
no autoriza descartar una escritura válida solo por una carrera con stop/fin.
No se prometen entrega o captura exactamente una vez frente a cualquier fallo.

## Reinicio y ventanas no observadas

SessionCollector relee SQLite aproximadamente cada segundo. Una campaña vigente
se reanuda con el fin original; una vencida se completa con stopped_at igual al
fin planificado. collection_runtime conserva epoch del proceso y último contacto
local por campaña. Nuevo epoch produce collection_interruptions con ventana entre
último contacto y nuevo contacto, acotada al fin de campaña. No afirma instante de
caída ni que toda la ventana fuera interrupción. Primera conexión tardía se distingue
como first_attachment_window, con inicio de campaña como límite inferior conocido.
Un CLI status no simula un contacto del collector. Campañas observadas ya terminadas
no generan falsas interrupciones al reiniciar. No se inventan observaciones GPS.
Una caída del proveedor sigue siendo distinta del estado COLLECTING; su tratamiento
HTTP permanece en Coordinator, sin implementar reglas de caída general de fase 5.

## Esquema v3 y TEC-08

ObservationStore y SessionStore usan una sola transacción para su migración v1/v2
→ v3, incluido el hook de esquema de campañas. Repetir es seguro. WAL, conexión
por operación, foreign_keys y timeout 250 ms reutilizan database.py. Catálogo conserva
su esquema independiente. Una versión desconocida se rechaza.

Se añaden a gps_observations: fleet_name, fleet_raw, gps_original, server_original,
provider_record_id, provenance, gps_instant, historical, timestamp_collision.
VEH_ID y GPSFix ya estaban representados por vehicle_id y gps_fix. Las columnas
anteriores y valores previos no se cambian ni borran; las columnas nuevas de filas
legadas quedan NULL. observation_keys añade índices de identidad a históricos
interpretables; duplicados previos permanecen, enlazando nuevas recepciones al
primero de ellos. Asociaciones previas se copian sin modificar la tabla original.

| Registro | Clasificación / tratamiento |
|---|---|
| gps_observations, observation_keys | Históricos y soporte de deduplicación persistente; no purgar por retención técnica. |
| collection_sessions, collection_observations | Historial de campañas y asociaciones permanente. |
| collection_interruptions | Evidencia histórica de ventanas no observadas; conservar con la campaña. |
| catalog_vehicles, catalog_events | Identidad y eventos confirmados; conservar. |
| collection_runtime | Último contacto técnico, actualizado por campaña. |
| collection_batches, catalog_acquisitions | Marcas técnicas de admisión/idempotencia; una futura purga debe preservar trabajo incompleto y no permitir replay. |
| Logs y métricas | Evidencia técnica, sin payloads/secretos; política de retención pendiente de fase 6. |

No se implementa purga ni se aplica automáticamente el plazo aprobado de 30 días.
La lista y las dependencias anteriores concretan la parte de TEC-08 de esta fase;
el mecanismo de retención y validación de reversión desplegada siguen posteriores.

### Compatibilidad y reversión

Decisión posterior del usuario (11 de octubre de 2026): el próximo arranque
utilizará una base totalmente nueva, sin migrar datos del piloto. No es necesario
recuperar esos datos para avanzar. El procedimiento siguiente aplica cuando se
necesite conservar una base existente; no obliga a trasladar el piloto descartable.
La base nueva se inicializará con el esquema del ejecutable elegido. No se ha
cambiado la configuración ni creado, sustituido o eliminado una base operativa.

El ejecutable de fase 3 acepta user_version hasta 2: **rechaza v3**. Ser aditiva no
hace esta migración reversible cambiando el número de versión. Procedimiento para
un despliegue posterior, no ejecutado aquí:

1. Identificar binario/versión, detener autoridad y escritor; obtener backup
   consistente de SQLite con API backup o escritores detenidos, incluyendo WAL
   correctamente. No copiar solo .db en caliente. Probar restauración separada.
2. Probar migración y exportación en copia, conservar backup protegido fuera de Git.
3. Para volver: detener escritores nuevos, conservar íntegra la base v3 y restaurar
   una copia previa comprobada con el binario anterior. Los datos adquiridos después
   del backup quedan en v3 para revisión/exportación; no mezclarlos automáticamente.
4. No bajar user_version, borrar columnas/tablas ni eliminar el volumen para forzar
   arranque. Catálogo/eventos y campañas deben acompañar la copia coherente.

## CSV y comandos

Permanecen start --duration, status, stop y export --session de gps_emi.collector,
y exportación global de gps_emi.analysis.export_observations. Los comandos de
campañas no cargan .env ni consultan GPS. GPS_EMI_DATA_DB debe ser absoluto y común
entre procesos; default relativo legado se conserva. El servidor oficial sigue
requiriendo --official y mapping explícito. No se ha activado en este encargo.

Se mantienen columnas CSV y orden anteriores; metadata nueva va al final.
Por campaña se añade session_received_at; collection_session_id muestra la campaña
solicitada. acquired_at permanece como primera adquisición original del GPS.
--from/--to por campaña filtran recepción en ella; global filtra acquired_at.
Las bases v1/v2 se exportan en lectura sin migrarlas, con sus columnas originales.
El destino debe ser nuevo y los campos no se deben ejecutar como fórmulas.
Las variables HEARTBEAT heredadas siguen siendo configuración aceptada positiva,
pero ya no generan observaciones repetidas ni certifican continuidad física.

## Alcance y validación

Decisiones aplicadas: ARQ-01/02/03, COB-02/04/05, CAT-01/04, DAT-01/02/06/07,
COL-01–08, PER-01/02 y VAL-01. TEC-03/04 resueltos técnicamente; TEC-08 parcial.
Vigilancias siguen Medellín (COB-03); no se implementa fase 5, selección de flotas,
restauración, mensajes aplazados, limpieza HTML, geografía ni retención automática.

Pruebas con transporte falso, relojes controlados, bases temporales y red prohibida.
Se actualizan expectativas de pruebas previas que exigían heartbeat duplicado,
una nueva fila por campaña o collector Medellín; no se conservan como requisitos.
Los cierres/documentos de fases 2/3 y las validaciones antiguas de collector/campañas
se mantienen como evidencia histórica, sin atribuirles la implementación de fase 4.

Evidencia ejecutada en este encargo:

- Suite específica inicial de collector, campañas, catálogo y fase 4: 97 aprobadas
  en 11,98 s. Después se añadieron cinco casos de frontera.
- Los 17 casos nuevos de `tests/test_phase4_collector.py`: aprobados en 2,68 s.
- Regresión completa final, incluida la reconciliación de filas en una sola pasada:
  **977 aprobadas, 0 fallidas, en 27,53 s**.
- `git diff --check` sin errores; enlaces locales de los documentos modificados
  válidos y comprobación de codificación UTF-8 sin alertas.
- Revisión local de los 19 archivos de fase 4 y búsqueda de patrones de secretos
  sin hallazgos. No se incluyen .env, bases, CSV, logs ni artefactos de build.
  No hay detector especializado disponible; no se presenta esa búsqueda como
  certificación absoluta de ausencia de secretos.

Se ejecutó Python 3.12 del runtime local, con `.venv/Lib/site-packages` y `src`
en PYTHONPATH: `python -m pytest -q -p no:cacheprovider --tb=short
--basetemp=<directorio temporal nuevo bajo build>`. La suite prohíbe conexiones
de red y usa SQLite temporal. Los resultados anteriores de otras fases no se
reutilizan como ejecución actual.

## Archivos del incremento

- Adquisición/dominio: `src/gps_emi/acquisition.py`, `src/gps_emi/models.py`,
  `src/gps_emi/catalog.py`, `src/gps_emi/monitoring/fleet_polling.py`.
- Persistencia/exportación: `src/gps_emi/analysis/collector.py`,
  `src/gps_emi/analysis/sessions.py`, `src/gps_emi/analysis/export_observations.py`.
- Pruebas: `tests/test_collector.py`, `tests/test_collection_sessions.py`,
  `tests/test_phase3_catalog.py`, nuevo `tests/test_phase4_collector.py`.
- Documentación: `docs/gps-collector.md`, `docs/collection-sessions.md`,
  `docs/guia-del-sistema.md`, `docs/operacion.md`, `docs/README.md`,
  `docs/decisiones-arquitectonicas-renderexcel.md`, `docs/multiple-watches.md`
  y este nuevo `docs/widetech-official-phase4.md`.

Al terminar la implementación inicial, el índice estaba vacío y HEAD era el
commit selectivo de fase 3 `a171b37`; aún no se había creado el commit de fase 4.
Se conservaron ajenos `.codemapignore`, `docs/auditoria-api-oficial.md` y
`docs/prompt-integracion-api-oficial.md`.

### Cierre selectivo del 11 de octubre de 2026

Por solicitud posterior del usuario se prepara el commit de fase 4 junto con
la decisión de iniciar una base nueva sin trasladar el piloto. Nueva ejecución
offline con `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --tb=short
--basetemp=build/phase4-close-20261011`: **977 aprobadas en 36,79 s**.
No se ejecutó migración, borrado ni creación de bases operativas; no hubo llamadas
autenticadas ni despliegue. Los archivos ajenos indicados arriba quedan excluidos.

Pendiente externo: cobertura y metadata reales nacionales, cuota/envolturas de
WideTech, piloto acotado con credenciales oficiales, entrega WhatsApp, Docker/Ubuntu,
backup/restauración del entorno real. Ninguna prueba sintética demuestra esos puntos.
