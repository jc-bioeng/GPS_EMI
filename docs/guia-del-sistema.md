# Guía del sistema

Estado revisado el 11 de octubre de 2026: base histórica `03ee209`, fase 1
versionada en `eda2606`, fase 2 versionada en `24dae94` y fase 3 en `a171b37`. Fase 4 (`18d2661`) añade collector nacional y campañas
sin duplicación GPS. Fase 5 local incorpora continuidad de vigilancias; sin despliegue.
Ver [índice y estado](README.md) y [manual de operación](operacion.md).

## Propósito y componentes

GPS_EMI consulta posiciones reportadas de ambulancias, lista vehículos por sede,
vigila transiciones de llegada y conserva observaciones durante campañas de
recolección. La posición es la última reportada por el proveedor; no implica una
medición en tiempo real ni se calcula pertenencia por distancia o polígonos propios.

| Componente | Responsabilidad |
| --- | --- |
| `gpspace_loaddatalog.py`, `gps_emi.cli` | Consola, consultas y vigilancia individual |
| `acquisition_runtime.py`, `acquisition.py` | Autoridad exclusiva, planificación central y snapshot compartido |
| `providers/widetech.py`, `providers/load_data_log.py` | Transporte legado y Parameters dinámicos; fachada de lectura para consumidores |
| `catalog.py`, `database.py` | Identidad/presencia nacional persistente y conexión SQLite común |
| `queries.py`, `monitoring/observation.py` | Consultas y evaluación de observaciones |
| `monitoring` | Estado de llegada, vigilancias y distribución de snapshots |
| `selection` | Contextos temporales para selección explícita de candidatos |
| `whatsapp` | Webhook, comandos, conversación, presentación y envío a Meta |
| `collector.py`, `analysis` | CLI de sesiones, escritura SQLite y exportaciones |
| `clock.py`, `observability.py` | Tiempo y registros operativos |
| `providers/widetech_official.py` | Adaptador RenderExcel integrado por composición explícita con `--official` |

Los módulos se encuentran bajo `src/gps_emi`. El dominio no requiere WhatsApp
para decidir una llegada. La presentación limpia el HTML visible sin convertir
ese texto en una identidad técnica.

## Flujo operacional

```mermaid
flowchart TD
  W[Webhook firmado y remitente autorizado] --> I[Inbox y deduplicación]
  I --> M[MessageService]
  M --> Q[Consulta puntual]
  M --> P[FleetPolling compartido]
  C[CLI] --> R[AcquisitionRuntime]
  M --> R
  R --> K[Coordinator: única adquisición y planificación]
  K --> L[Adaptador elegido: RenderExcel o legado]
  L --> T[Catálogo: persistir antes de publicar]
  T --> S[Snapshot inmutable y vista de catálogo]
  S --> V[SnapshotSource: proyección operacional]
  V --> Q
  V --> C
  V --> P
  P --> A[WatchManager y ArrivalMonitor]
  A --> N[Notificación WhatsApp]
  P --> B[Cola del collector]
  B --> D[SQLite / sesión de recolección]
```

El webhook no consulta GPSpace. Inbox procesa comandos fuera de la petición HTTP.
Coordinator es el único planificador y propietario del transporte GPS.
FleetPolling distribuye publicaciones entre altas, vigilancias y collector;
consultas y WatchRunner leen SnapshotSource. AcquisitionRuntime reserva exclusión
local: CLI y servidor no operan simultáneamente con el mismo directorio de estado.
No hay IPC ni coordinación automática entre instalaciones o hosts.

Sin solicitudes pendientes, altas, vigilancias ni campaña activa, el coordinador
espera sin adquirir flota.
Una campaña activa permite adquirir aunque ningún usuario esté vigilando.

## Contrato de datos e identidad

En el flujo LoadDataLog, `Vehicle` conserva `vehid`, `plate`, `mobile_number`,
`gps_timestamp`, `location`, `speed`, `ignition`, `gps_fix`, `zones`, coordenadas
y campos originales `zones_raw`, `vehicle_name_raw`, `vehicle_license_raw`.

La correspondencia **observada y utilizada por EMI/GPSpace** es:

| Origen legado | Modelo |
| --- | --- |
| `VEHID` | `vehid` |
| `VEH_NAM` | `plate` |
| `VEH_LCNS` | `mobile_number` |

No es una garantía universal de WideTech. La flota operacional se restringe
exactamente a `Ambulancias Medellin;44986;0` en el legado.

En RenderExcel, `VEH_ID` es identidad y `Id` identifica el registro GPS.
El mapping `WIDETECH_PLATE_FIELD`/`WIDETECH_MOBILE_FIELD` debe asignar
explícitamente Movil y VEH_NAM, sin deducir placas por formato. Snapshot conserva
originales, diagnósticos y procedencia; una fila inválida no congela las válidas.
Las filas anteriores conservadas mantienen su versión y edad y no alimentan
nuevas observaciones de vigilancias/collector. Fase 4 separa observaciones recibidas
de estado operativo: un reporte fuera de orden se guarda históricamente, pero no
reemplaza la posición vigente ni avanza vigilancias. Cobertura siempre desconocida.
La proyección oficial de consultas acepta el prefijo Ambulancias a nivel nacional.
Vigilancias conservan Medellín/Medellin; en fase 4 el collector es nacional
por el mismo prefijo oficial Ambulancias. La vista de catálogo persiste antes de publicar y distingue presencia
de calidad GPS. No se confunde ausencia con reclasificación. Una flota distinta
confirmada termina la vigilancia con causa interna fleet_changed, sin mensaje
proactivo WhatsApp. Véase [fase 3](widetech-official-phase3.md).

La resolución acepta placa o número de móvil, elimina espacios exteriores e
ignora mayúsculas. El alias `amb20` permite encontrar `AMB-20`; no transforma
arbitrariamente cualquier placa o nombre. La ausencia se informa y la ambigüedad
no se resuelve por fecha, GPSFix o preferencia de nombres. La consola la rechaza;
WhatsApp ofrece candidatos numerados y continúa por VEHID exacto.

Los contextos de selección duran cinco minutos, pertenecen a un propietario y
se consumen una vez. Los números se interpretan en la lista vigente; no contienen
la identidad del mensaje que el usuario estaba mirando. Ver
[selección explícita](vehicle-selection.md).

El parser elimina markup HTML de las zonas antes del dominio. Después se comparan
exactamente `EMI Medellin_Poblado` y `EMI_Medellin_Taller`. No se hace búsqueda
aproximada. Location conserva su original y se limpia para mostrarla en WhatsApp.

## Llegadas y estado

La primera observación dentro de una sede establece el estado, **no genera una
llegada retroactiva**. Se informa que ya estaba dentro y se permite cancelar la
vigilancia. Para una llegada posterior debe observarse OUTSIDE → INSIDE. Cambiar
entre sedes sin observar exterior no equivale a esa transición; una pertenencia
ambigua a ambas sedes no fuerza una sede ganadora.

Timestamps duplicados, fuera de orden, ausentes o incompatibles se rechazan para
la evolución del monitor. GPS de más de 300 segundos no avanza el monitor,
no genera llegadas ni reinicia actividad (VIG-10). El umbral configurable de
advertencia no modifica esa barrera. GPSFix=0 sigue siendo diagnóstico independiente.

Tras 300 segundos sin GPS nuevo y fresco se entra en interrupción individual.
Tres GPS nuevos y frescos en la misma sede confirman presencia y finalizan con
un aviso distinto de llegada: su hora exacta se desconoce. Exterior fresco vuelve
al seguimiento normal; cambio de sede u otra interrupción reinicia la secuencia.
El vencimiento ocurre al superar doce horas configurables sin actividad, descontando
solo pausas de adquisición desde intento fallido hasta publicación válida, incluidos
fallos locales de persistencia con categoría propia. Repetir GPS no pausa ni renueva.
La adquisición recuperada no confirma presencia individual. Véase [fase 5](widetech-official-phase5.md).
Ausencia o duplicidad de identidad no constituye salida.

Las vigilancias son únicas por propietario + VEHID mientras están ACTIVE. Sus
estados terminales son COMPLETED (llegada o presencia), CANCELLED, FAILED y
EXPIRED (causa interna inactivity, sin aviso proactivo nuevo). El gestor protege estado
con locks y ejecuta notificaciones fuera del lock. Al detectar llegada reserva
un intento de envío: aceptación por Meta no confirma entrega y no hay reintento
durable automático. Las vigilancias y conversaciones se pierden al reiniciar.

## Recolección y tiempo

SQLite conserva sesiones, observaciones y, en modo oficial, catálogo nacional
con eventos confirmados. Tres adquisiciones nuevas aptas consecutivas sin una
identidad confirman ausencia observada, no baja. Errores/lotes no aptos rompen
la secuencia; reiniciar conserva eventos y reinicia contadores provisionales.
La política TEC-01 fue aprobada con el límite de no detectar recortes silenciosos.
No se restauran ubicaciones ni vigilancias desde ese catálogo.

SQLite conserva sesiones y observaciones. La migración desde el collector inicial
añade la relación de sesión sin atribuir las filas antiguas a una campaña:
`collection_session_id` permanece NULL para ellas.

Solo puede existir una sesión COLLECTING. Termina como COMPLETED al alcanzar su
fin planificado, o STOPPED por intervención. Reiniciar no prolonga la ventana:
se recupera el tiempo restante o se reconoce la expiración. Consultar `status`
puede inicializar/migrar el esquema y actualizar una expiración.

El collector recibe publicaciones nuevas por una cola limitada y escribe en su
propio hilo; no incorpora un cliente GPS adicional. La clave global persistente
por proveedor/VEH_ID/instante/contenido impide duplicados incluso tras reinicio;
heartbeat y renombrados no crean otra fila. Otra campaña recibe una asociación a
la observación conocida. Se preservan originales GPS, flota y procedencia recibidos,
sin sustituirlos por metadatos actuales del catálogo.

El inicio HTTP del snapshot excluye peticiones previas al inicio de campaña.
La admisión durable del escritor se serializa con stop/vencimiento; una escritura
admitida puede terminar después del cierre. La cola no admitida se revalida.
Los reinicios dejan ventanas de interrupción sin afirmar el instante exacto de
caída ni inventar observaciones. Esquema v3 aditivo, históricos previos intactos;
[la fase 4](widetech-official-phase4.md) detalla transacciones, reintentos y reversión.

SQLite usa WAL y transacciones cortas. La sesión y adquisición se registran en
UTC con zona; la presentación usa America/Bogota. El timestamp GPS heredado de
LoadDataLog puede carecer de zona: no debe reinterpretarse como UTC por comodidad.
Ver [sesiones](collection-sessions.md) y [collector](gps-collector.md).

## Fallos y observabilidad

Coordinator aplica intervalo, backoff progresivo, recuperación gradual y
Retry-After. Los consumidores no reintentan HTTP por su cuenta. En el oficial,
fallos globales conservan el último snapshot; errores individuales restringen
solo su fila. Autenticación/autorización del método bloquean nuevos intentos.
Un error local o del método no demuestra caída general de WideTech.
En el legado, una sesión GPSpace expirada es
terminal para las vigilancias y requiere intervención externa. El coordinador
bloquea la demanda de colección de esa sesión tras un fallo terminal para evitar
reintentos continuos; COLLECTING por sí solo no acredita adquisición exitosa.
Tras reparar autenticación, reiniciar permite recuperar una campaña aún vigente.

Los logs distinguen adquisición, diagnósticos y cambios de estado; resúmenes
periódicos agregan contadores del proceso. `/health` comprueba liveness local,
no autenticación, frescura GPS, entrega WhatsApp ni salud de SQLite.

## Camino hacia servicios oficiales

La fase 1 (`eda2606`) aportó el adaptador RenderExcel con parsing XML/SOAP,
errores tipados y pruebas sintéticas. Fase 2 lo conecta mediante `--official`
a la autoridad central existente, conservando consultas, resolución, selector,
vigilancias y collector. No hay fallback a LoadDataLog ni activación implícita.

Identidad VEH_ID, cobertura nacional por fases, geocercas EMI y zona inicial
America/Bogota ya están decididas. Falta verificar detalles técnicos de etiquetas
y variantes reales (TEC-02), además de
límites externos: cuota efectiva y envoltura de errores RenderExcel. El intervalo
aprobado es 30 segundos configurable; no certifica la cuota del proveedor.

La evidencia CLI reportada por el usuario el 9 de octubre es distinta de las
pruebas offline. No acredita llegada real, entrega WhatsApp, cobertura nacional,
Docker ni Ubuntu. La restauración de vigilancias sigue aplazada deliberadamente.
Ver [fase 2](widetech-official-phase2-spec.md) y el
[registro aprobado](decisiones-arquitectonicas-renderexcel.md).
