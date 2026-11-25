"""Estado persistente de los trabajos de generación de telemetría.

La generación de un PNG con FastF1 tarda (descarga y cálculo), así que la vista
lanza un hilo *daemon* y devuelve el control de inmediato. A diferencia de una
implementación anterior basada en un ``dict`` en memoria, el estado vive en la
tabla ``TelemetryJob``: el endpoint ``telemetry_job_status`` lo lee desde la BD,
por lo que funciona con varios workers y tras reinicios del servidor.

Un trabajo huérfano (proceso muerto a mitad de generación) se detecta por su
antigüedad: ``get_job`` lo marca como fallido y ``start_job`` lo reinicia. No se
añaden dependencias (ni Celery ni Redis).
"""

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections
from django.db.utils import OperationalError
from django.utils import timezone

from .models import (
    STATUS_ERROR,
    STATUS_GENERATING,
    STATUS_PENDING,
    STATUS_READY,
    Driver,
    Session,
    TelemetryJob as JobRow,
)
from .services import _plot_file_path, build_cache_key, get_or_generate_telemetry_plot

logger = logging.getLogger(__name__)

# Mensaje sin detalles técnicos: el traceback se guarda solo en los logs.
TELEMETRY_USER_ERROR = (
    "No se pudo generar la telemetría. Intentá nuevamente más tarde "
    "o probá con otra sesión."
)

# Un trabajo "generando" más viejo que esto se considera huérfano. El valor es
# generoso porque la primera descarga de FastF1 puede tardar varios minutos.
DEFAULT_STALE_SECONDS = 1800.0

# SQLite bloquea la tabla entera para escribir. Un hilo worker y el request
# pueden querer actualizar la misma fila a la vez; serializamos las escrituras
# dentro del proceso y reintentamos los bloqueos transitorios entre procesos.
_write_lock = threading.Lock()
_LOCK_RETRIES = 20
_LOCK_DELAY = 0.05


def _update_job(filters, **fields):
    """Actualiza filas de trabajos con reintento ante bloqueos de SQLite."""
    for attempt in range(_LOCK_RETRIES):
        with _write_lock:
            try:
                return JobRow.objects.filter(**filters).update(**fields)
            except OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == _LOCK_RETRIES - 1:
                    raise
        time.sleep(_LOCK_DELAY)


@dataclass
class TelemetryJob:
    """Copia del estado con la misma API que el registro en memoria anterior."""

    key: str
    status: str = STATUS_PENDING
    plot_path: str = ""
    error: str = ""
    started_at: object = None


def _stale_seconds():
    """Umbral de huérfanos, configurable sin tocar ``settings.py``."""
    try:
        return float(
            getattr(settings, "TELEMETRY_JOB_STALE_SECONDS", DEFAULT_STALE_SECONDS)
        )
    except (TypeError, ValueError):
        return DEFAULT_STALE_SECONDS


def _is_stale(row):
    reference = row.updated_at or row.created_at
    if reference is None:
        return True
    if timezone.is_naive(reference):
        reference = timezone.make_aware(reference, timezone.get_default_timezone())
    return timezone.now() - reference > timedelta(seconds=_stale_seconds())


def _snapshot(row):
    return TelemetryJob(
        key=row.key,
        status=row.status,
        plot_path=row.plot_path or "",
        error=row.error or "",
        started_at=row.started_at,
    )


def _plot_exists(plot_path):
    absolute = _plot_file_path(plot_path)
    return bool(absolute and os.path.isfile(absolute))


def clear_jobs():
    """Borra las filas de trabajos (útil en tests; no toca ``TelemetryCache``)."""
    with _write_lock:
        JobRow.objects.all().delete()


def get_job(key):
    """Devuelve una copia del estado desde la BD, o ``None`` si no existe.

    Un trabajo pendiente/generando huérfano (más viejo que el umbral) se marca
    como fallido para que el sondeo no espere eternamente al worker muerto.
    """
    if not key:
        return None
    row = JobRow.objects.filter(key=key).first()
    if row is None:
        return None
    if row.status in (STATUS_PENDING, STATUS_GENERATING) and _is_stale(row):
        now = timezone.now()
        changed = _update_job(
            {"pk": row.pk, "status": row.status, "updated_at": row.updated_at},
            status=STATUS_ERROR,
            error=TELEMETRY_USER_ERROR,
            finished_at=now,
            updated_at=now,
        )
        if changed:
            row.status = STATUS_ERROR
            row.error = TELEMETRY_USER_ERROR
            row.finished_at = now
    return _snapshot(row)


def start_job(session, driver1, driver2):
    """Obtiene o crea el trabajo persistente y lanza el worker si hace falta.

    La clave es la misma del servicio (temporada + sesión + pareja canónica),
    por lo que ``VER vs COL`` y ``COL vs VER`` comparten una única fila. El
    reinicio usa control optimista por ``updated_at``: si otro worker tocó la
    fila mientras tanto, este proceso no lanza un segundo hilo.
    """
    key = build_cache_key(session, driver1, driver2)
    with _write_lock:
        row, created = JobRow.objects.get_or_create(
            key=key,
            defaults={
                "session": session,
                "driver1": driver1,
                "driver2": driver2,
                "status": STATUS_PENDING,
            },
        )
    state = _snapshot(row)

    # Una fila recién creada siempre debe lanzar el worker: todavía no hay
    # nadie generando, aunque ya tenga el estado "pending" por defecto.
    reusable = not created and (
        (state.status in (STATUS_PENDING, STATUS_GENERATING) and not _is_stale(row))
        or (state.status == STATUS_READY and _plot_exists(state.plot_path))
    )
    if reusable:
        return state

    claimed = _update_job(
        {"pk": row.pk, "status": state.status, "updated_at": row.updated_at},
        status=STATUS_PENDING,
        plot_path="",
        error="",
        started_at=None,
        finished_at=None,
        updated_at=timezone.now(),
    )
    if not claimed:
        # Otro worker ganó la carrera: devolvemos su estado actual.
        current = JobRow.objects.filter(pk=row.pk).first()
        if current is None:
            return TelemetryJob(
                key=key, status=STATUS_ERROR, error=TELEMETRY_USER_ERROR
            )
        return _snapshot(current)

    _launch_worker(
        row.pk,
        session.pk,
        driver1.pk,
        driver2.pk,
        f"{key} ({driver1.acronym} vs {driver2.acronym}, sesión {session.pk})",
    )
    return TelemetryJob(key=key, status=STATUS_PENDING)


def _launch_worker(job_pk, session_pk, driver1_pk, driver2_pk, label):
    """Arranca el hilo daemon que actualizará la fila en la BD."""
    thread = threading.Thread(
        target=_run_job,
        args=(job_pk, session_pk, driver1_pk, driver2_pk, label),
        name=f"telemetry-{job_pk}",
        daemon=True,
    )
    thread.start()
    return thread


def _run_job(job_pk, session_pk, driver1_pk, driver2_pk, label):
    """Cuerpo del hilo: trabaja con PKs y nunca lanza al request."""
    close_old_connections()
    started = timezone.now()
    _update_job(
        {"pk": job_pk},
        status=STATUS_GENERATING,
        started_at=started,
        finished_at=None,
        error="",
        updated_at=started,
    )
    try:
        session = Session.objects.get(pk=session_pk)
        driver1 = Driver.objects.get(pk=driver1_pk)
        driver2 = Driver.objects.get(pk=driver2_pk)
        plot_path = get_or_generate_telemetry_plot(session, driver1, driver2)
        if not plot_path:
            raise RuntimeError("El servicio no devolvió una ruta de gráfico.")
    except Exception:
        logger.exception("Falló el trabajo de telemetría %s", label)
        finished = timezone.now()
        _update_job(
            {"pk": job_pk},
            status=STATUS_ERROR,
            error=TELEMETRY_USER_ERROR,
            finished_at=finished,
            updated_at=finished,
        )
    else:
        finished = timezone.now()
        _update_job(
            {"pk": job_pk},
            status=STATUS_READY,
            plot_path=plot_path,
            error="",
            finished_at=finished,
            updated_at=finished,
        )
    finally:
        close_old_connections()
