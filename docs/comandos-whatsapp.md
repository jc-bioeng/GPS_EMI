# Comandos WhatsApp y confirmación de vigilancia

Actualización del 13 de octubre de 2026. Lista para mantenimiento y administración;
el menú del usuario sigue siendo breve. Todas las variantes usan el parser y los
casos de uso existentes, con la misma autorización, selección y adquisición central.

## Variantes admitidas

| Operación | Formas admitidas |
|---|---|
| Menú principal | `menu`, `menú`, `inicio`, `principal`, `menu principal` |
| Ayuda | `ayuda`, `help` |
| Iniciar vigilancia | `vigilar`, `vigilancia`, `vigila`, `iniciar vigilancia`, `nueva vigilancia` |
| Consultar ubicación | `ubicacion`, `ubicación`, `ubica`, `ubicar`, `localizar`, `localiza`, `consultar ubicacion` |
| Menú de vigilancias | `vigilancias`, `gestionar vigilancias` |
| Listar las propias | `misvigilancias`, `mis vigilancias`, `ver vigilancias`, `listar vigilancias` |
| Elegir vigilancia para detener | `detener`, `detener vigilancia`, `detener vigilancias`, `parar vigilancia`, `parar vigilancias` |
| Cancelar operación pendiente | `cancelar`, `cancela` |
| Consultar sede | `sede`, `ver sede`, `consultar sede` |

Se ignoran mayúsculas, tildes y espacios adicionales entre palabras del comando.
El identificador conserva su contenido y pasa por el resolver existente. Se
reconocen palabras completas, no prefijos arbitrarios. Por ejemplo `ubicarme` no
equivale a `ubicar`. La palabra singular `vigilancia` inicia una solicitud;
`vigilancias` abre el menú de gestión.

Vigilancia y ubicación aceptan placa o móvil después del comando; sin identificador
lo solicitan. Ejemplos sintéticos: `vigila TEST-MOBILE`, `Ubicar TEST-PLATE`.
Sede acepta `POBLADO`, `TALLER`, `1` o `2`, o solicita selección si falta argumento.
Se conservan las opciones numéricas y los comandos de las respuestas interactivas.

`detener vigilancias` **no detiene todas**: presenta las vigilancias propias para
elegir una. `cancelar` sin argumento cancela la operación pendiente, no vigilancias
activas. La cancelación por identificador interno de vigilancia sigue comprobando
propiedad y estado; usar normalmente el menú DETENER.

## Ambulancia reportada dentro al iniciar

Si la última posición utilizable indica Poblado, Taller o ambas, primero se muestra
la sede y hora GPS, aclarando que no garantiza ubicación actual. Se pregunta si
quiere vigilar para que salga y vuelva a entrar:

1. Sí, vigilar salida y regreso.
2. No, cancelar.

No existe vigilancia activa antes de aceptar. Se reutiliza PendingSelections con
un contexto CONFIRM_WATCH de un solo VEH_ID, propietario, token consumible y TTL
de cinco minutos. MENU, CANCELAR u otra operación invalidan la confirmación.
Si primero había varios candidatos, se elige uno y luego se pide confirmación.
Aceptar vuelve a validar esa identidad en el snapshot disponible: no se sustituye
por otro vehículo con igual etiqueta. Una vigilancia ya activa responde como
duplicada, sin crear otra ni volver a pedir permiso.

Después de aceptar se exige observar GPS nuevo y fresco fuera de ambas sedes.
Mientras no se observe esa salida, ni tres GPS interiores tras interrupción ni un
cambio entre sedes generan aviso. Después de observar exterior se aplica la
continuidad normal de fase 5. Datos antiguos, duplicados o ambiguos no prueban salida.
La CLI también pregunta; acepta `s`, `si` o `sí`, y cualquier otra respuesta cancela.
En consola el TTL se comprueba al responder; no hay temporizador que interrumpa input.

## Diagnóstico de UBICACION nacional

El código oficial ya permite consultar por placa y móvil en flotas `Ambulancias`
de otras ciudades; la vigilancia permanece limitada a Medellín. El legado sí está
limitado a Medellín. No se cambió el proveedor por defecto ni se relajaron validaciones
para hacer aparecer datos incompletos. La nueva línea de arranque informa únicamente
modo y alcance, sin credenciales:

```text
acquisition mode=official query_scope=national_ambulances watch_scope=medellin
```

Si no se encuentra una ubicación, WhatsApp distingue modo legado de ausencia de
posición utilizable en el snapshot oficial. Ausencia en consultas no demuestra que
el vehículo no exista: revisar mapping, identidad, flota, calidad de fila y cobertura.

Para un contenedor estándar de este proyecto, el operador puede comprobar solo el
modo del proceso principal sin imprimir su entorno ni argumentos completos:

```bash
docker compose exec -T gps-emi python -c "from pathlib import Path; args=Path('/proc/1/cmdline').read_bytes().split(b'\0'); print('official' if b'--official' in args else 'legacy')"
```

Usar los mismos archivos/proyecto Compose de la instalación. El comando es para
Linux con el servidor Python como PID 1; con otro supervisor, verificar la
configuración de arranque por separado sin compartir secretos. No ejecuta GPS.
La activación oficial requiere configuración válida y reinicio controlado de una
sola autoridad; seguir [operación](operacion.md), no iniciar una CLI simultánea.

El modo del servidor donde se reportó el problema no se conoce. Las pruebas offline
confirman alcance nacional del código, no explican por sí solas ese incidente real.

## Verificación local

El 13 de octubre de 2026 se ejecutó la regresión completa: **1.105 pruebas aprobadas
en 32,41 segundos**, sin red y con bases temporales. Incluye variantes del parser,
autorización y selección propia; confirmación, vencimiento, replay, identidad
desaparecida/duplicada, cancelación y salida/regreso; CLI; consultas oficiales por
placa y móvil de Cali, Bogotá, Barranquilla y Bucaramanga; y diagnóstico legado.
Los nombres de ciudades en pruebas acompañan registros sintéticos, no flota real.
No se ejecutaron llamadas WideTech/Meta, despliegue, commit ni push.
