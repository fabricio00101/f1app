# F1 2026 Season Hub

Una aplicación web moderna desarrollada con **Django** dedicada a la temporada 2026 de Fórmula 1.
Este proyecto utiliza la biblioteca **FastF1** para extraer datos, horarios, telemetría y listas de pilotos desde la API oficial de F1, presentándolos en un dashboard estilizado estilo "Datacenter AWS".

![F1 2026 Dashboard](f1hub/static/f1hub/img/colapinto.png)

## Características principales

- **Dashboard estilo "Dark Mode"**: Interfaz gráfica responsiva inspirada en los gráficos de telemetría de AWS, usando texturas de fibra de carbono, glassmorphism (paneles translúcidos) y detalles en colores neón (Electric Blue y Racing Red).
- **Sincronización del Calendario (Schedule)**: Módulo integrado para descargar el calendario completo de la temporada actual/próxima usando FastF1. Incluye las fechas, lugares y estados de todos los Grandes Premios.
- **Sincronización de Pilotos**: Actualización automática de la grilla de pilotos según las últimas sesiones oficiales. Cuenta con un script de respaldo (fallback) propio para asignar las nacionalidades cuando FastF1 no las provee.
- **Servicio de Telemetría Cacheable**: Arquitectura preparada para generar gráficos de comparación de telemetría en tiempo real entre las vueltas más rápidas de dos pilotos utilizando `matplotlib`. Los gráficos se almacenan en caché (`/media/telemetry/`) para optimizar el rendimiento y el consumo de ancho de banda.
- **Cuenta Regresiva en Vivo**: Temporizador integrado en la barra de navegación que calcula el tiempo restante exacto hasta la próxima carrera del calendario.
- **Diseño Móvil**: Menú hamburguesa lateral `(<aside>)` adaptativo e interfaz fluida diseñada específicamente para verse bien tanto en PC como en celulares.

## Estructura del Proyecto

- `f1app/`: Directorio raíz del repositorio.
- `config/`: Configuración global de Django (`settings.py`, rutas principales `urls.py`).
- `f1hub/`: Aplicación principal (App de Django).
  - `models.py`: Modelos de Base de Datos para Temporada, Evento, Sesión, Piloto y Caché de Telemetría.
  - `services.py`: Lógica de integración de graficados y caché de FastF1 con Matplotlib.
  - `management/commands/`: Scripts de inicialización y actualización de la base de datos (`sync_schedule.py`, `sync_drivers.py`).
  - `templates/f1hub/`: Plantillas HTML usando `base.html` como molde padre.
  - `static/f1hub/`: Archivos CSS (`style.css`), tipografías e imágenes estáticas del Frontend.
  - `urls.py` & `views.py`: Enrutamiento y renderizado de las vistas `dashboard`, `drivers`, `teams` y `insights`.

## Requisitos de Instalación

Asegúrate de tener instalado Python 3.10+ y crear un entorno virtual, ya que el procesamiento de datos científicos de pandas y numpy que requiere FastF1 es estricto con sus dependencias.

```bash
# 1. Clonar el repositorio
git clone https://github.com/fabricio00101/f1app.git
cd f1app

# 2. Crear y activar el entorno virtual
python -m venv venv
# En Windows:
.\venv\Scripts\activate
# En Linux/Mac:
source venv/bin/activate

# 3. Instalar las dependencias
pip install django fastf1 matplotlib pandas
```

## Uso de la Base de Datos y Comandos de Sincronización

La aplicación necesita estar poblada con los datos de las carreras y los pilotos. Ejecuta las migraciones y luego usa los comandos personalizados que creamos:

```bash
# Crear la base de datos local SQLite
python manage.py makemigrations
python manage.py migrate

# Sincronizar el calendario y eventos de la temporada 2026
python manage.py sync_schedule

# Sincronizar la lista actualizada de pilotos
python manage.py sync_drivers
```

Finalmente, levanta el servidor de desarrollo:

```bash
python manage.py runserver
```

Entra a `http://127.0.0.1:8000` en tu navegador para ver el Hub en acción.
