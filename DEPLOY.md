# Despliegue en producción

La app se sirve con **gunicorn** (WSGI) y **WhiteNoise** para los archivos
estáticos: no hace falta un nginx dedicado para `static/`. WhiteNoise lee el
resultado de `collectstatic` desde `STATIC_ROOT` (`staticfiles/`), que está
ignorado por Git y debe generarse en cada deploy que cambie estáticos.

## Variables obligatorias

| Variable |Valor|
|---|---|
| `DJANGO_DEBUG` | `0` (producción; `1` **sólo** para desarrollo local) |
| `DJANGO_SECRET_KEY` | Secret real y estable, generado con el comando de abajo |
| `DJANGO_ALLOWED_HOSTS` | Dominios separados por comas, p. ej. `f1app.example.com,www.f1app.example.com` |

Opcionales (tienen default en `config/settings.py`): `F1_SEASON_YEAR`,
`TELEMETRY_CACHE_TTL_DAYS`, `TELEMETRY_SESSION_LIMIT`.

Generar el secret:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
# Windows:
.\.venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

> **No reutilices el secret generado en desarrollo.** Con `DJANGO_DEBUG=1` el
> proyecto crea una clave efímera en cada arranque (las sesiones se invalidan
> al reiniciar): sirve para no romper el entorno local, pero es insegura y
> cambia solo: en producción debe usarse un `DJANGO_SECRET_KEY` permanente y
> privado. Tampoco subas el `.env` al repositorio.

## Verificación local antes de desplegar

En PowerShell (Linux/Mac: `export VAR=valor`):

```powershell
$env:DJANGO_DEBUG='0'
$env:DJANGO_SECRET_KEY='<secret-real>'
$env:DJANGO_ALLOWED_HOSTS='f1app.example.com,www.f1app.example.com'

.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py check --deploy
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
.\.venv\Scripts\python.exe manage.py test
```

`check --deploy` puede avisar sobre `SECURE_HSTS_SECONDS`,
`SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE` y `CSRF_COOKIE_SECURE`. Son
advertencias esperadas si la terminación TLS se hace en un proxy/carga previo:
configura ahí HSTS y la redirección HTTPS, o activa esas opciones en Django
cuando la app reciba HTTPS de extremo a extremo.

Para desarrollo local, con `$env:DJANGO_DEBUG='1'` no hacen falta secret ni
hosts: `runserver` sigue sirviendo `static/` y `media/` como antes.

## Arranque con gunicorn (Procfile)

> **gunicorn no corre en Windows**: importa `fcntl`, disponible sólo en Unix.
> En Windows probá con `runserver` o con Docker/WSL; el despliegue real
> (`Procfile`/`Dockerfile`) apunta a Linux.

El `Procfile` usa `web: gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000}`:
respeta `PORT` si la plataforma lo define (Heroku, Render, etc.) y usa `8000`
como fallback para arranques locales. Antes de iniciar, ejecuta
`collectstatic --noinput` como paso de release y las migraciones:

```bash
python manage.py migrate
python manage.py sync_schedule
python manage.py sync_drivers
```

## Arranque con Docker

```powershell
docker build -t f1app .
docker run --rm -p 8000:8000 --env-file .env -v f1media:/app/media f1app
```

El `Dockerfile` instala `requirements.txt`, corre `collectstatic` durante el
build y ejecuta gunicorn en `0.0.0.0:8000` como usuario `appuser`. El `.env`,
`.venv`, la DB, `media/` y cachés se excluyen con `.dockerignore`: inyecta las
variables en runtime (`--env-file .env` o variables del orquestador), nunca en
la imagen. Si montas `/app/media`, asegurate de que el directorio del host sea
escribible por `appuser` (o usa `user: root` en el contenedor).

La DB es SQLite en `BASE_DIR / 'db.sqlite3'` (`/app/db.sqlite3` dentro del
contenedor) y **no** está en la imagen. Para no perderla, monta un archivo o
volumen en esa ruta (o cambia `DATABASES` a una base administrada antes de
desplegar) y ejecuta `migrate` + los comandos `sync_*` como paso de release.


## Archivos `media/` (telemetría)

WhiteNoise **no** sirve `MEDIA_ROOT`: `config/urls.py` sólo sirve `media/`
cuando `DEBUG=True`. En producción, los gráficos generados en
`media/telemetry/` deben exponerse por otro medio:

- montar `media/` como volumen persistente y servir `/media/` con un proxy
  inverso (nginx) delante de gunicorn, **o**
- subirlos a almacenamiento de objetos (S3-compatible) y servirlos por CDN.

La elección depende de la plataforma; en ningún caso se debe habilitar
`DEBUG=True` en producción para poder ver las imágenes.
