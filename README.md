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

## Arranque local

Python 3.10+ y entorno virtual (pandas/numpy de FastF1 son sensibles a las versiones). Clonar, activar `.venv`, instalar y arrancar — sin crear `.env` ni exportar variables:

```bash
git clone https://github.com/fabricio00101/f1app.git
cd f1app

python -m venv .venv            # sólo si aún no existe
.\.venv\Scripts\activate        # Windows
source .venv/bin/activate       # Linux/Mac

pip install -r requirements.txt
python manage.py runserver
```

La primera vez que se ejecuta `manage.py`, si no hay `DJANGO_SECRET_KEY` ni `DJANGO_DEBUG` en el entorno y todavía no existe `.env`, se genera automáticamente un `.env` en la raíz con `DJANGO_DEBUG=1` y un `DJANGO_SECRET_KEY` aleatorio (se avisa en una línea por consola). Con eso funcionan `check`, `test`, `migrate`, `runserver` y los comandos de sincronización sin pasos previos. Ese `.env` es **sólo de desarrollo** y está en `.gitignore`: **nunca subirlo**. Si ya exportaste alguna de esas variables o ya existe `.env`, el bootstrap no sobrescribe nada.

Entrá a `http://127.0.0.1:8000` para ver el Hub.

## Configuración y producción

La configuración sensible se lee de variables de entorno o de un `.env` local (las variables reales del proceso tienen prioridad). `.env.example` documenta las claves disponibles. En producción **no se autogenera nada**: definí explícitamente `DJANGO_DEBUG=0`, un `DJANGO_SECRET_KEY` real —por ejemplo con `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`— y `DJANGO_ALLOWED_HOSTS` con los dominios correspondientes. Con `DEBUG=False` y sin secret, el arranque falla con un error explícito en lugar de usar una clave insegura. Ver [DEPLOY.md](DEPLOY.md) para el despliegue.

`config/urls.py` sirve `static/` y `media/` únicamente cuando `DEBUG=True`. En producción esos archivos debe servirlos el servidor web (`python manage.py collectstatic` para los estáticos).

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

Con los datos cargados, recargá `http://127.0.0.1:8000` para ver el Hub con el calendario y la grilla de pilotos.
