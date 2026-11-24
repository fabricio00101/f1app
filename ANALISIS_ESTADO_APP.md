# Análisis del estado actual de F1 2026 Season Hub

**Fecha del análisis:** 24 de noviembre de 2026  
**Propósito:** dejar contexto verificable para que otro agente pueda priorizar mejoras de interfaz y funcionalidad.  
**Alcance:** revisión estática del repositorio (Django, vistas, modelos, templates, CSS, sincronizadores, configuración y documentación). No se ejecutó la aplicación ni se validó el sitio en navegador; tampoco se ejecutaron pruebas.

## Resumen ejecutivo

El repositorio contiene una base funcional de Django con cuatro pantallas: datacenter, pilotos, equipos y análisis. Hay un diseño visual consistente de tema oscuro, una lista de calendario y una integración de FastF1 para importar eventos/pilotos y generar una imagen comparativa de velocidad. Sin embargo, buena parte de la experiencia presentada como datos reales hoy es estática o simulada: la tabla de constructores está fijada en la vista, las estadísticas de Colapinto y el gráfico del dashboard están escritos en HTML, y el servicio de telemetría no tiene una ruta ni formulario que lo exponga al usuario. La pantalla de equipos solo lista nombres deducidos de pilotos y la de análisis es un placeholder.

La prioridad general debería ser **integridad de datos y claridad de estado** antes de ampliar gráficos: corregir el estado/fecha del próximo evento, eliminar o marcar datos de ejemplo, completar la sincronización idempotente y conectar una comparación de sesiones/pilotos real. Después, mejorar accesibilidad móvil, navegación del calendario, tablas y filtros.

## Estado observado

| Área | Implementado | Estado práctico |
|---|---|---|
| Dashboard | Hero de Colapinto, tabla de constructores, módulo gráfico, calendario lateral y cuenta regresiva | Mezcla datos de BD con datos hardcodeados y un gráfico CSS ficticio. El badge dice «EN VIVO» aunque no existe streaming/actualización en vivo. |
| Pilotos | Tabla con nombre, acrónimo, equipo y nacionalidad | Se alimenta de todos los `Driver` disponibles, sin temporada asociada ni orden explícito por equipo. El sincronizador por defecto usa 2025, mientras la página se rotula 2026. |
| Equipos | Tarjetas con los nombres distintos derivados de `Driver.team` | Sin clasificación, pilotos asociados, colores ni enlaces; texto genérico «En desarrollo para 2026». |
| Análisis | Página informativa de placeholder | No hay controles ni visualización analítica. El texto promete datos en vivo que FastF1 no entrega en vivo en esta implementación. |
| Calendario | Eventos de temporada 2026 en un aside | Solo muestra sede y fecha; no ofrece detalle, sesiones ni navegación. El contexto del calendario solo se carga en `dashboard`, así que en las otras vistas el sidebar no tiene calendario. |
| Ingesta | Comandos `sync_schedule` y `sync_drivers` con FastF1 | Hay valores desactualizados/estáticos, errores ocultos y campos existentes que no se actualizan al re-sincronizar. |
| Telemetría | Función que carga FastF1, obtiene vueltas rápidas, grafica velocidad y guarda PNG/caché | No está conectada desde `views.py`, `urls.py` ni los templates. Maneja solo velocidad pese a promesas de acelerador/frenado. |

## Hallazgos prioritarios

### P0 — Evitar que datos simulados se presenten como oficiales

- `f1hub/views.py` define la tabla de constructores con puntos y posiciones estáticos; el comentario reconoce que son datos de prueba. Los valores también se muestran como clasificación actual sin aviso.
- `f1hub/templates/f1hub/dashboard.html` fija para Colapinto `Williams Racing`, P8, P5 y 62 puntos. El único dato dinámico relacionado (`colapinto`) se consulta en la vista pero no se usa en el template.
- El gráfico de `dashboard.html` está dibujado con formas CSS (`.mock-chart`, `.glow-line`) y el encabezado lo etiqueta «EN VIVO». Métricas 78% y 342 km/h son constantes y carecen de sesión, fecha o fuente.
- En la vista pública no se distingue «dato real», «estimación», «demo» y «sin datos». Eso erosiona confianza y puede mostrar información falsa, especialmente fuera del contexto de una maqueta.

**Siguiente paso recomendado:** retirar cifras simuladas del flujo normal o etiquetarlas visiblemente como demostración; mostrar vacíos útiles y fecha/fuente de actualización. Crear una fuente persistida para resultados y standings antes de renderizarlos como oficiales.

### P0 — Resolver el próximo evento y la cuenta regresiva

- `dashboard()` busca el primer `Event` con `date >= hoy`, pero si no encuentra ninguno selecciona el primer evento de 2026. Después de terminar la temporada, ese evento es pasado.
- El countdown en `base.html` solo recibe una fecha, fija la hora objetivo a las 15:00 UTC para todos los Grandes Premios y deja el contador en cero cuando vence. No hay tratamiento de «evento en curso», «próxima sesión» o «temporada finalizada».
- La fecha del evento no es equivalente a la hora de inicio de carrera: `Event` almacena solo un `DateField`; las sesiones sí tienen `date_time`, pero el dashboard ignora esas horas.
- Existe un contador móvil separado sin `data-date`; el JavaScript copia el contenido del contador de escritorio, pero si no existe `#countdown-timer` retorna sin inicializar.
- Al no haber eventos, el HTML cae a una fecha/nombre de fallback de Australia 2026, independientemente del calendario real.

**Siguiente paso recomendado:** determinar el próximo `Session` futuro de la temporada y usar su `date_time`; definir un estado vacío/final de temporada; compartir la fecha mediante un único nodo de datos para desktop y mobile y mostrar el huso horario.

### P1 — Completar la sincronización de datos

- `sync_schedule` crea temporada/eventos/sesiones con `get_or_create`, por lo que cambios de fecha, sede, nombre u horario en FastF1 no se reflejan si el registro ya existía. Solo informa cuántos eventos nuevos creó.
- El comando atrapa cualquier excepción y solo la imprime en salida normal. Un fallo puede dejar una sincronización parcial sin hacer fallar el proceso de forma clara.
- El mapeo de nombres de sesión no cubre todos los nombres/eventos posibles y se apoya en `hasattr(row, ...)` sobre Series de pandas; conviene validar columnas y formatos explícitamente. No se actualiza el status de `Session` a `Completed`.
- `sync_drivers` por defecto consulta 2025, pero la UI se titula «Pilotos de la temporada 2026». El mapa de nacionalidades es manual y una lista fija; para cambios de grilla o códigos no contemplados usa `Unknown`.
- `Driver` no tiene temporada, equipo como entidad ni historial. Un mismo acrónimo actualizado reemplaza su equipo anterior, y la página no puede representar correctamente cambios de alineación por temporada.
- `sync_schedule` crea temporada 2026 pero no sincroniza `Driver`; el README requiere ejecutar comandos aparte, sin indicar que los drivers usan 2025 por defecto.

**Siguiente paso recomendado:** hacer upsert de eventos/sesiones, informar fallos con código de salida no exitoso, parametrizar temporada en ambos comandos, identificar la fuente y hora de sincronización, y modelar temporada/constructor de forma explícita si se necesita historial.

### P1 — Conectar la telemetría a un flujo utilizable

- `f1hub/services.py` contiene `get_or_generate_telemetry_plot()`, pero no existe view/URL para invocarla ni controles para elegir sesión y pilotos.
- La búsqueda de la caché considera el orden de pilotos, así que VER-vs-COL y COL-vs-VER generan entradas distintas. La clave del archivo tampoco incluye temporada ni valida coherencia con la sesión.
- Si ocurre una excepción durante carga, extracción o guardado, puede quedar una fila vacía de `TelemetryCache`; la siguiente petición no limpia ni reconstruye explícitamente ese estado.
- El archivo se escribe directamente en disco; no hay manejo de concurrencia, expiración/invalidez ni feedback de carga. La ruta se construye a partir de acrónimos y el código confía en que los objetos corresponden a la sesión seleccionada.
- Se configura Matplotlib/FastF1 en el proceso web, pudiendo bloquear una petición por descargas/procesamiento pesado. No se muestran límites ni estados para sesiones sin telemetría.
- El gráfico real usa `Distance` y `Speed`; no genera acelerador/freno pese a la descripción del módulo de análisis.

**Siguiente paso recomendado:** agregar una vista GET/POST validada con selectores de evento/sesión/pilotos, estados de carga/error/sin datos y un enlace a la imagen; normalizar la pareja de pilotos en la clave de caché; validar selección y controlar fallos. Si el volumen crece, mover generación lenta a una cola de trabajos.

## Mejoras de interfaz y experiencia

### Navegación y composición

- El calendario aparece solo en el contexto de `dashboard`. `drivers`, `teams` e `insights` no proporcionan `calendar_events`, `today` ni `next_event`; por eso el layout compartido tiene menos contexto y el contador termina usando el fallback.
- Los elementos del calendario parecen interactivos (`cursor: pointer`, hover) pero son `div` sin enlace ni acción. Cada evento debería llevar a una ficha de GP con sesiones y resultados.
- En escritorio, el aside del calendario no tiene `position: sticky` ni altura/overflow definido; la página puede desplazar toda la navegación y dejar el calendario fuera de vista.
- El menú móvil usa un botón sin `aria-label`, `aria-expanded` ni `aria-controls`; no hay cierre con Escape ni gestión del foco. El overlay cierra por clic, pero no se aprecia una acción de cierre en el propio panel.

**Mejoras sugeridas:** extraer contexto común a un context processor o helper; convertir eventos en enlaces; fijar/limitar la altura del aside; añadir accesibilidad al menú y al calendario.

### Jerarquía visual, contenido y confianza

- El look oscuro y los acentos azul/rojo crean una identidad clara, pero el dashboard concentra la atención en un héroe estático y un ranking de datos ficticios. Dar prioridad a próximo evento, última sesión y clasificación respaldada por datos haría la portada más útil.
- «DATACENTER», «AWS Insights» y «EN VIVO» sugieren funcionalidades externas o en tiempo real que la app no integra. Renombrar o etiquetar con precisión.
- Equipos ofrece tarjetas casi vacías; puede mostrar pilotos, nacionalidad, color, puntos y posición o dejar una pantalla vacía explícita hasta tener esos datos.
- Análisis necesita un estado inicial accionable, por ejemplo selección de GP/sesión y dos pilotos, y una explicación concisa de qué dato se compara y cuándo está disponible.
- En pilotos falta búsqueda, filtro por equipo, orden, nacionalidad traducida o bandera accesible, e indicación de temporada/fecha de actualización.
- Faltan formatos locales consistentes para fechas, horas, puntos y nombres oficiales. `date:"d M"` depende de locale de Django y puede resultar en abreviaturas no esperadas.

### Responsive, legibilidad y accesibilidad

- En pantallas menores de 1200 px se pasa a una columna, aunque todavía pueden caber dos columnas en tablets anchas; sería mejor un breakpoint ajustado al contenido.
- En móvil las tablas recurren al scroll horizontal, pero no hay indicación de desbordamiento ni encabezado fijo. La tabla de equipos sí utiliza estilos inline y markup flexible con nombre de clase `driver-card`, lo que dificulta un sistema responsive consistente.
- Varias reglas globales fijan tipografías pequeñas y bajo contraste (`--text-muted: #888`; labels de 11–12 px). Revisar contraste y tamaños, sobre todo en tablas y countdown.
- Los elementos puramente decorativos (líneas, fondos) no aportan alternativa textual; cuando haya gráficos reales deben incluir título, leyenda, ejes, unidad y resumen accesible.
- El botón móvil usa un `<i>` de Font Awesome sin texto accesible. Las fuentes y Font Awesome dependen de CDNs externos y no hay fallback visual de icono claramente definido.

**Mejoras sugeridas:** probar anchos de móvil/tablet, usar estados de foco visibles, etiquetas accesibles, tablas legibles y gráficos con resumen textual; revisar contraste y tolerar que CDN no cargue.

## Riesgos de configuración y mantenimiento

- `config/settings.py` tiene `DEBUG = True`, `ALLOWED_HOSTS = []` y una `SECRET_KEY` de desarrollo fija en el archivo. El propio archivo indica que no sirve para producción. Separar configuración por entorno y usar variables de entorno antes de publicar.
- La versión de Django en `requirements.txt` está como `Django>=5.0`, mientras la migración indica haber sido generada con Django 6.0.2; las dependencias no están fijadas y pueden producir entornos distintos.
- El README documenta instalación explícita de `django fastf1 matplotlib pandas`, pero no describe cómo activar entorno/configurar secretos en despliegue, los límites de FastF1 ni la política de datos de ejemplo.
- `f1hub/tests.py` solo contiene el esqueleto de TestCase; los archivos `test_f1.py`, `test_driver_keys.py` y `test_telemetry.py` son scripts manuales que consultan red/datos y base local, no pruebas aisladas/reproducibles. No se ejecutaron durante este análisis.
- No se encontró una estrategia de logging, reintentos, actualización programada ni indicador de última sincronización.

## Plan de trabajo sugerido para el siguiente agente

1. **Aclarar qué es dato real:** etiquetar/eliminar standings, estadísticas y telemetría de muestra; agregar estados vacíos y fuente/fecha para datos reales.
2. **Arreglar navegación compartida y tiempo:** hacer que cada página tenga el mismo contexto global; seleccionar sesión futura y resolver postemporada/fallback.
3. **Hacer confiable la ingesta:** parametrizar el año, actualizar registros existentes, reflejar errores correctamente y presentar fecha de sincronización.
4. **Completar una funcionalidad vertical:** pantalla de análisis que permita elegir evento/sesión/pilotos, invoque servicio, y presente gráfico/error/cache de manera clara.
5. **Construir equipos y clasificación a partir de modelos:** evitar strings/puntos hardcodeados y representar la temporada explícitamente.
6. **Pulir UI y accesibilidad:** móvil, foco, etiquetas ARIA, tablas/filtros y contraste.
7. **Preparar producción y mantenimiento:** configuración por entorno, dependencias reproducibles, logging y pruebas automatizadas aisladas (el usuario/agente que implemente deberá ejecutarlas como parte del trabajo).

## Archivos clave

- `f1hub/views.py`: próximos eventos, contexto de pantallas y standings estáticos.
- `f1hub/models.py`: esquema actual (sin standings ni entidad de equipo/temporada para pilotos).
- `f1hub/services.py`: generación y caché de telemetría no expuesta por una vista.
- `f1hub/management/commands/sync_schedule.py`: importación de calendario/sesiones.
- `f1hub/management/commands/sync_drivers.py`: importación de pilotos, con año por defecto 2025.
- `f1hub/templates/f1hub/base.html`: navegación, calendario y cuenta regresiva compartidos.
- `f1hub/templates/f1hub/dashboard.html`: estadísticas fijas y gráfico simulado.
- `f1hub/templates/f1hub/drivers.html`, `teams.html`, `insights.html`: vistas funcionales parciales/placeholders.
- `f1hub/static/f1hub/css/style.css`: sistema visual y responsive.
- `config/settings.py`, `requirements.txt`, `README.md`: configuración y puesta en marcha.

## Nota de interpretación

Este documento describe lo que se puede confirmar en el código. No afirma que la base local esté poblada ni que el sitio se vea exactamente igual en cada navegador; no se encontró una base de datos local versionada (`db.sqlite3` está ignorada) y no se hizo una revisión visual ejecutando el servidor.
