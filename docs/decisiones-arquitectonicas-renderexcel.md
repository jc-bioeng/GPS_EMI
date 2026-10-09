# GPS_EMI — Decisiones arquitectónicas aprobadas para RenderExcel

Consolidación documental: **8 de octubre de 2026**.
Fuente: consolidación definitiva del usuario del 7 de octubre y aclaraciones posteriores en el chat del proyecto.

## Autoridad y uso

Este es el registro de referencia de **decisiones aprobadas**, no una descripción de funcionalidades ya implementadas. Prevalece sobre las propuestas de `auditoria-api-oficial.md` y `prompt-integracion-api-oficial.md` cuando discrepen. Las instrucciones posteriores del usuario prevalecen sobre este documento.

Antes de planificar o implementar una fase, leer este documento y la especificación de esa fase. No presentar una decisión aprobada como una pregunta pendiente porque todavía no exista en el código. No confundir una funcionalidad aplazada con un requisito olvidado ni implementar automáticamente una ampliación aplazada para “cerrar deuda”.

La autorización original de este registro fue documentar estos acuerdos. Los encargos posteriores de implementación se registran por fase, separados de los acuerdos. Este registro por sí solo no activa el proveedor, autoriza cambios de bases operativas ni ejecuta despliegues. La aprobación arquitectónica del despliegue gradual define su procedimiento; no acredita su realización.

Estados utilizados:

- **Aprobado:** el comportamiento está decidido; puede faltar su implementación.
- **Aplazado:** exclusión deliberada del incremento actual.
- **Detalle técnico por concretar:** falta precisión de implementación, sin reabrir el comportamiento aprobado.
- **Limitación externa:** el proveedor no ha confirmado o demostrado un contrato; se documenta sin inventarlo.

## Arquitectura y cobertura

| ID | Decisión aprobada |
|---|---|
| ARQ-01 | Fuente oficial única de adquisición: `HistoryDataLastLocationByUserRenderExcel`. |
| ARQ-02 | Coordinador central y snapshot compartido. Ningún consumidor consulta WideTech de forma independiente, incluidos WhatsApp y CLI. |
| ARQ-03 | Una adquisición a la vez, sin solapamientos. Frecuencia inicial de **30 segundos configurable**, con backoff progresivo, recuperación gradual y respeto de `Retry-After`. |
| COB-01 | Consultas de ubicación nacionales de ambulancias. |
| COB-02 | Collector nacional de ambulancias mediante campañas controladas. |
| COB-03 | Vigilancias de llegada exclusivamente para la flota `Ambulancias Medellín`. |
| COB-04 | Clasificación nacional por `fltName` que comience por `Ambulancias`. No se exige una lista manual cerrada de flotas. |
| COB-05 | Clasificación de la compañía; no inferirla por posición geográfica, dirección, iconos o tipo de carrocería. Se revocó la propuesta de quitar el filtro y usar un polígono metropolitano. |

Los 30 segundos son configuración aprobada, **no un límite certificado por WideTech**. El usuario observó restricciones en algunos métodos y no logró activarlas en RenderExcel desde la página de muestra. Esa observación no demuestra consumo ilimitado. No sustituir el intervalo por 20 o 40 segundos solo por documentación genérica o propuestas antiguas.

## Identidad y catálogo nacional persistente

| ID | Decisión aprobada |
|---|---|
| CAT-01 | `VEH_ID` es la identidad principal. `Id` identifica el registro GPS, no el vehículo. |
| CAT-02 | Reutilizar el selector existente para nombres duplicados; no crear otro mecanismo paralelo. |
| CAT-03 | Cambios de nombre actualizan el nombre vigente sin cambiar `VEH_ID`. |
| CAT-04 | Cambios de flota sobrescriben `fltName` vigente, sin historial específico de cambios de flota. Las observaciones históricas conservan sus valores originales. |
| CAT-05 | Confirmar desaparición tras **tres adquisiciones válidas consecutivas** sin el vehículo. No equivale necesariamente a baja del vehículo. |
| CAT-06 | Registrar reapariciones conservando identidad e historial. |
| CAT-07 | SQLite conserva identificación vigente, flota, primera/última aparición, estado de presencia, fechas y eventos confirmados de desaparición/reaparición. |
| CAT-08 | Tras reinicio se conservan eventos confirmados y se reinician contadores provisionales de ausencia; se requieren tres nuevas adquisiciones válidas. |
| CAT-09 | Reclasificación y desaparición son diferentes: un vehículo presente con otra flota no está ausente de WideTech. |

No filtrar prematuramente filas de otras flotas si eso elimina la evidencia necesaria para distinguir reclasificación de desaparición.

## Adquisición, fechas y calidad

| ID | Decisión aprobada |
|---|---|
| DAT-01 | Zona horaria configurable, inicialmente `America/Bogota`. Conservar `FechaGPS` y `FechaServidor` originales. |
| DAT-02 | Mantener la última información válida y su antigüedad ante errores. |
| DAT-03 | Ubicaciones de más de **cinco minutos** se muestran como última ubicación conocida con advertencia. |
| DAT-04 | No usar adquisiciones sospechosamente parciales para confirmar desapariciones. |
| DAT-05 | Confiar en coordenadas de WideTech salvo errores de formato; no añadir un filtro de plausibilidad geográfica como requisito de negocio. |
| DAT-06 | No registrar nuevamente observaciones GPS duplicadas. |
| DAT-07 | Conservar observaciones fuera de orden históricamente, sin actualizar estado operativo ni reiniciar temporizadores de vigilancia. |
| DAT-08 | Después de reinicio, esperar el primer snapshot válido para responder ubicaciones; informar inicialización y no presentar datos persistidos como actuales. |

Una adquisición exitosa no implica una observación GPS nueva. La presencia en un lote válido sirve al catálogo incluso si el reporte GPS se repite. La recuperación de una vigilancia requiere observaciones GPS nuevas, no tres lecturas de la misma caché ni tres respuestas idénticas.

La zona configurada es una decisión de interpretación de la aplicación; no demuestra por sí misma la semántica horaria de todos los datos del proveedor. Conservar originales permite verificarla sin volver a decidir el valor inicial aprobado.

## Vigilancias y llegadas

| ID | Decisión aprobada |
|---|---|
| VIG-01 | Geocercas EMI Poblado y EMI Taller; preservar sus nombres exactos del dominio existente. |
| VIG-02 | Llegada normal por transición exterior→interior. Primera lectura dentro no genera llegada. |
| VIG-03 | Interrupción individual tras **cinco minutos sin observación GPS nueva**. |
| VIG-04 | Recuperación tras interrupción con **tres observaciones genuinamente nuevas** para confirmar presencia. |
| VIG-05 | Emitir una única notificación de presencia confirmada en recuperación. No presentarla como si se conociera el instante exacto de llegada. |
| VIG-06 | Máxima inactividad de **doce horas configurable**; finalizar al superar el plazo. |
| VIG-07 | Suspender el cómputo de vencimiento mientras esté confirmada la caída general de WideTech. |
| VIG-08 | No restaurar automáticamente vigilancias tras reinicio. |
| VIG-09 | Cambios de nombre no alteran vigilancias vinculadas a `VEH_ID`. |
| VIG-10 | Datos antiguos no generan llegadas. Esto modifica la política anterior, donde STALE era solo diagnóstico. |
| VIG-11 | **Cambio confirmado a otra flota termina la vigilancia activa**, según aclaración posterior del usuario. Flota ausente o respuesta inválida no demuestra cambio confirmado. |

Registrar internamente la causa de terminación. La notificación proactiva de esa causa por WhatsApp está aplazada; no confundirla con la notificación de presencia recuperada, que sí está aprobada.

Preservar funcionalidad existente de WhatsApp no significa congelar los comportamientos expresamente modificados aquí: consultas nacionales, restricción Medellín, tratamiento de datos antiguos y recuperación se integran y prueban en sus fases correspondientes.

## Collector y campañas

| ID | Decisión aprobada |
|---|---|
| COL-01 | Mantener campañas controladas, nacionales de ambulancias. |
| COL-02 | Iniciar con la primera adquisición compartida posterior al inicio de campaña. |
| COL-03 | Completar escrituras iniciadas durante la vigencia de la campaña. |
| COL-04 | Reanudar campañas automáticamente tras reinicio, conservando el vencimiento original sin extenderlo. |
| COL-05 | Registrar periodos interrumpidos sin inventar observaciones. |
| COL-06 | Migración SQLite aditiva. Metadatos: `VEH_ID`, `fltName`, `FechaServidor`, `GPSFix` y procedencia. |
| COL-07 | Guardar únicamente observaciones GPS nuevas para el histórico; las fuera de orden, no almacenadas antes, se guardan identificadas como históricas. |
| COL-08 | Mantener CSV existente y añadir columnas al final; conservar comandos de inicio, estado, detención y exportación. |

El heartbeat técnico no autoriza duplicar filas GPS. Si se necesita demostrar que hubo otra adquisición idéntica, debe distinguirse de una observación nueva. La identidad exacta de deduplicación se concreta técnicamente sin revertir COL-07.

## Persistencia, pruebas y despliegue

| ID | Decisión aprobada |
|---|---|
| PER-01 | SQLite WAL, escrituras coordinadas, transacciones cortas y esperas ante bloqueos. |
| PER-02 | Migraciones aditivas compatibles con históricos. |
| PER-03 | Retención técnica configurable de **30 días**, sin borrar históricos de campañas ni eventos del catálogo. |
| VAL-01 | Integración automatizada y regresión de WhatsApp, CLI, vigilancias, collector, SQLite, fallos, respuestas incompletas, duplicados, reinicios, concurrencia y observaciones fuera de orden. |
| DEP-01 | Validar primero en Windows; respaldar SQLite; identificar versión; desplegar gradualmente en Ubuntu y verificar funcionamiento. |
| DEP-02 | Procedimiento de reversión que considere compatibilidad de base de datos. Migración aditiva no garantiza que el ejecutable anterior acepte el nuevo esquema. |

No interpretar la retención técnica como autorización para purgar datos operativos o eventos confirmados.

## Incrementos aplazados deliberadamente

| ID | Funcionalidad | Estado |
|---|---|---|
| APL-01 | Seleccionar una o varias flotas por `fltName` en campañas | Siguiente incremento |
| APL-02 | Restaurar vigilancias tras reinicio | Incremento posterior |
| APL-03 | Notificar proactivamente desapariciones por WhatsApp | Incremento posterior |
| APL-04 | Informar por WhatsApp la causa de finalización de una vigilancia | Incremento posterior |
| APL-05 | Presentar información de flota y advertencias relacionadas en WhatsApp | Próximo incremento de integración, según acuerdo previo no revocado por la consolidación |

APL-05 no impide aplicar internamente COB-03 o VIG-11 ni ofrecer las consultas nacionales aprobadas. Tampoco aplaza la notificación de recuperación VIG-05.

## Fases acordadas y criterios de cierre

| Fase | Alcance | Criterio de cierre |
|---|---|---|
| 1 | Contrato y adaptador aislado RenderExcel | Parsing, errores y pruebas documentados; proveedor operacional sin sustituir. Véase [fase 1](widetech-official-phase1.md). |
| 2 | Adquisición central y snapshot | Ningún consumidor con HTTP independiente, sin solapamientos; inicialización y caché explícitas; manejo de restricciones. Véase [especificación fase 2](widetech-official-phase2-spec.md). |
| 3 | Catálogo nacional y consultas | Identidad persistente, cambios de nombre/flota, desapariciones/reapariciones, consultas nacionales y vigilancia restringida; finalización por reclasificación. |
| 4 | Collector y campañas | Captura nacional sin duplicados, históricos fuera de orden, continuidad de campañas, migración y CSV compatibles. |
| 5 | Continuidad de vigilancias | Antigüedad, interrupción, recuperación, vencimiento y suspensión de cómputo con pruebas deterministas. |
| 6 | Validación y despliegue gradual | Regresión integral, retención técnica, Windows, respaldo, versión, Ubuntu y reversión comprobable. |

Las pruebas acompañan cada fase. La fase 6 no es el primer momento para probar. Las interfaces entre fases se diseñan antes de necesitarlas, sin adelantar funcionalidades aplazadas.

## Detalles técnicos por concretar, sin reabrir acuerdos

| ID | Detalle | Fase | Límite de la decisión pendiente |
|---|---|---|---|
| TEC-01 | Admisión de adquisiciones para contar ausencias | 3 (política aprobada el 9 de octubre) | Nuevas, no vacías, sin diagnósticos ni identidades duplicadas y con identidad/flota interpretables en todas las filas. Error/lote no apto reinicia secuencia. El usuario aceptó que no detecta recortes silenciosos; no certifica cobertura ni usa porcentajes. Véase [fase 3](widetech-official-phase3.md). |
| TEC-02 | Mapping y normalización de etiquetas y nombres reales de flota | 1–3 | `VEH_ID`, prefijo Ambulancias y cobertura Medellín ya están aprobados. Falta verificar correspondencia exacta Movil/VEH_NAM y variantes observadas, sin deducir placa por formato. |
| TEC-03 | Identidad de observación/deduplicación y colisiones de timestamp | 4 | Debe impedir duplicados, admitir históricos nuevos fuera de orden y mantener identidad por VEH_ID. |
| TEC-04 | Admisión de lotes y drenaje de escrituras al terminar campaña | 4 | Concretar inicio de escritura/admisión y fronteras temporales conservando COL-02/03. No extender duración ni perder escrituras autorizadas por una carrera. |
| TEC-05 | Secuencia exacta de confirmación tras interrupción | 5 | Tres observaciones nuevas y una notificación ya están aprobadas. Falta precisar reinicio de la secuencia, observaciones exteriores y estado posterior a la notificación. |
| TEC-06 | Criterio de caída general confirmada y contabilidad del vencimiento | 5 | No equiparar automáticamente un HTTP 500, credenciales inválidas o fallo local con caída general de WideTech. |
| TEC-07 | Mecanismo de autoridad única entre CLI y servidor/procesos | 2 | Resuelto en fase 2 mediante exclusión local verificable, sin IPC; CLI y servidor no operan simultáneamente con el mismo directorio de estado. No cubre otros hosts. Véase [especificación](widetech-official-phase2-spec.md). |
| TEC-08 | Inventario de registros técnicos sujetos a retención y reversión de esquema | 4–6 | Los 30 días y las exclusiones ya están aprobados. Concretar tablas/archivos y procedimiento recuperable. |

Resolver decisiones materiales al entrar en su fase, no pedir nuevamente el alcance nacional, los 30 segundos, la zona inicial, los cinco minutos, las doce horas o la retención aprobada.

## Estado de implementación posterior (separado de los acuerdos)

Fase 2 está versionada en `24dae94`. Fase 3 se implementó localmente sin despliegue;
su commit selectivo posterior, resultados y pruebas se documentan en
[fase 3](widetech-official-phase3.md). TEC-01 fue resuelto mediante la pregunta
concreta del encargo y aprobación expresa del usuario, con el límite indicado.
Los acuerdos CAT, DAT, VIG y APL permanecen intactos. No se aprueban propuestas
sobre mostrar ausentes en selectores o bloquear nuevas vigilancias por ese estado.

## Evidencia externa y cierre de errores de fase 1

- RenderExcel devolvió DataTable/diffgram con posiciones, `fltName` y `VEH_ID`. No requiere Excel ni GetMobileList para interpretar esas filas.
- GetMobileList devolvió un estado estructurado `space/Response/Status` con código **108**: permiso denegado para esa funcionalidad. No demuestra pérdida de acceso a RenderExcel y no debe usarse como health check de este último.
- RenderExcel con credenciales aleatorias devolvió HTTP 500 y texto plano por serialización. No permite inferir código funcional, autenticación confirmada ni restricción 109.
- La tabla de códigos ya fue aportada. No volver a solicitarla por falta de envoltura de RenderExcel: significado y formato de transmisión son evidencias distintas.
- Se aprobó cerrar fase 1 con reconocimiento de la envoltura estructurada observada y pruebas sintéticas de otros códigos, incluido 109. Verificar implementación y resultados en su documento de cierre; esta aprobación no reemplaza evidencia de ejecución.
- Permanece abierta la confirmación de que RenderExcel use esa envoltura en errores. Las pruebas sintéticas no demuestran una respuesta real del proveedor.
- El límite efectivo por método/cuenta/IP sigue siendo una limitación externa. No bloquea diseñar y probar el coordinador con transporte falso ni reabre ARQ-03. Tampoco autoriza pruebas de carga o ráfagas para provocar restricciones.

## Registro de propuestas superadas

| Propuesta antigua | Decisión vigente |
|---|---|
| ByUser como fuente principal y consultas individuales para completar flota | ARQ-01: RenderExcel aporta flota y posiciones conjuntamente. |
| Falta total de fuente oficial de flota / catálogo manual obligatorio | CAT/COB: fltName oficial; catálogo persistente derivado de adquisiciones. |
| Cuarenta segundos como límite universal | ARQ-03: treinta configurables; límites externos no certificados. |
| Consultar todos los vehículos sin filtro y advertir por polígono metropolitano | COB-04/05: prefijo Ambulancias, clasificación de compañía. |
| Vigilancias nacionales con advertencia de otra flota | COB-03 y VIG-11: solo Medellín; terminar ante cambio confirmado. |
| Mantener exclusivamente consultas de Medellín durante toda la integración | COB-01: consultas nacionales, integradas por fases. |
| STALE solo informativo para decidir llegada | VIG-10: datos antiguos no generan llegadas. |
| Repetir una observación GPS por heartbeat | DAT-06/COL-07: no duplicar observaciones. |
| Recuperar automáticamente vigilancias al reiniciar | VIG-08/APL-02: aplazado; campañas sí reanudan. |

## Cómo gestionar nueva deuda o hallazgos

1. Relacionar el hallazgo con un ID de este documento y comprobar si es implementación pendiente, aplazamiento deliberado, detalle técnico o limitación externa.
2. Si ya está decidido, implementar/probar en su fase; no volver a pedir la misma decisión.
3. Si exige un cambio real del acuerdo, explicar el conflicto y solicitar decisión antes de cambiar el comportamiento.
4. Si es detalle técnico, resolver con evidencia y pruebas dentro del alcance; preguntar solo si modifica semántica, cobertura, persistencia, entrega o costos operativos relevantes.
5. Documentar resultados de implementación aparte del acuerdo: aprobado no significa implementado, probado ni desplegado.
6. Mantener este registro consolidado ante nuevas decisiones; no acumular avisos contradictorios como especificación vigente.
