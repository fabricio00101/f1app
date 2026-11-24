"""Registro en memoria de trabajos de generación de telemetría.

La generación de un PNG con FastF1 tarda (descarga y cálculo), así que la vista
lanza un hilo *daemon* y devuelve el control de inmediato. El estado se consulta
por el endpoint ``telemetry_job_status`` con la clave del trabajo.

No hay dependencias externas (ni Celery ni Redis): el registro es por proceso,
por lo que al reiniciar el servidor los trabajos se pierden. Es aceptable para
una caché regenerable: la vista vuelve a lanzar la generación en la siguiente
petición si no hay PNG válido en ``TelemetryCache``.
"""

import logging
import os
import threading
from dataclasses import dataclass, field

from django.db import close_old_connections
from django.utils import timezone

from .services import _plot_file_path, build_cache_key, get_or_generate_telemetry_plot

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_GENERATING = "generating"
STATUS_READY = "ready"
STATUS_ERROR = "error"

# Mensaje sin detalles técnicos: el traceback se guarda solo en los logs.
TELEMETRY_USER_ERROR = (
    "No se pudo generar la telemetría. Intentá nuevamente más tarde "
    "o probá con otra sesión."
)

_lock = threading.Lock()
_jobs = {}


@dataclass
class TelemetryJob:
    key: str
    status: str = STATUS_PENDING
    plot_path: str = ""
    error: str = ""
    started_at: object = field(default_factory=timezone.now)


def clear_jobs():
    """Vacía el registro (útil en tests y al cambiar la configuración)."""
    with _lock:
        _jobs.clear()


def get_job(key):
    """Devuelve una copia del estado, o ``None`` si la clave no existe."""
    with _lock:
        job = _jobs.get(key)
        if job is None:
            return None
        return TelemetryJob(
            key=job.key,
            status=job.status,
            plot_path=job.plot_path,
            error=job.error,
            started_at=job.started_at,
        )


def start_job(session, driver1, driver2):
    """Registra y lanza la generación; reutiliza trabajos ya en curso.

    La clave es la misma del servicio (temporada + sesión + pareja canónica),
    por lo que ``VER vs COL`` y ``COL vs VER`` comparten un único trabajo.
    """
    key = build_cache_key(session, driver1, driver2)

    with _lock:
        existing = _jobs.get(key)
        if existing and existing.status in (STATUS_PENDING, STATUS_GENERATING):
            return TelemetryJob(
                key=existing.key, status=existing.status,
                plot_path=existing.plot_path, error=existing.error,
                started_at=existing.started_at,
            )
        if existing and existing.status == STATUS_READY:
            absolute = _plot_file_path(existing.plot_path)
            if absolute and os.path.isfile(absolute):
                return TelemetryJob(
                    key=existing.key, status=existing.status,
                    plot_path=existing.plot_path, error=existing.error,
                    started_at=existing.started_at,
                )
            _jobs.pop(key, None)  # el PNG desapareció: se regenera.

        job = TelemetryJob(key=key, status=STATUS_PENDING)
        _jobs[key] = job

    thread = threading.Thread(
        target=_run_job,
        args=(job, session, driver1, driver2),
        name=f"telemetry-{key}",
        daemon=True,
    )
    thread.start()
    return TelemetryJob(key=job.key, status=job.status, started_at=job.started_at)


def _run_job(job, session, driver1, driver2):
    """Cuerpo del hilo: nunca lanza excepciones hacia el request."""
    close_old_connections()
    try:
        with _lock:
            job.status = STATUS_GENERATING
        plot_path = get_or_generate_telemetry_plot(session, driver1, driver2)
        if not plot_path:
            raise RuntimeError("El servicio no devolvió una ruta de gráfico.")
    except Exception:
        logger.exception(
            "Falló el trabajo de telemetría %s (%s vs %s, sesión %s)",
            job.key, driver1.acronym, driver2.acronym, session.pk,
        )
        with _lock:
            job.status = STATUS_ERROR
            job.error = TELEMETRY_USER_ERROR
    else:
        with _lock:
            job.status = STATUS_READY
            job.plot_path = plot_path
            job.error = ""
    finally:
        close_old_connections()
