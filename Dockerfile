FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# El secret de producción NO se hornea en la imagen: con DEBUG=1 Django usa
# una clave efímera sólo durante el build. collectstatic genera staticfiles/
# con los hashes que luego sirve WhiteNoise.
RUN DJANGO_DEBUG=1 python manage.py collectstatic --noinput

# Ejecutar como usuario sin privilegios. Si se monta un volumen en /app/media,
# éste debe ser escribible por este usuario (ver DEPLOY.md).
RUN adduser --disabled-password --gecos "" appuser \
    && mkdir -p media fastf1_cache \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
