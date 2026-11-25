"""Servicio de generación y caché del gráfico de TIEMPOS POR VUELTA.

La API pública es ``get_or_generate_telemetry_plot(session, driver1, driver2)``
y ``get_cached_telemetry_plot(session, driver1, driver2)`` (solo lectura).

Los datos vienen de ``ergast_service.fetch_lap_comparison`` (FastF1/Ergast o
Jolpica), sin F1TV, sin live timing y sin credenciales. El eje X es la vuelta y
el eje Y el tiempo en segundos; nunca se genera un gráfico de velocidad.

Clave de caché
--------------
La pareja de pilotos se normaliza ordenando por ``acronym``, por lo que
``VER vs COL`` y ``COL vs VER`` son la misma entrada. La fila de ``TelemetryCache``
se identifica por ``(session, piloto_1_ordenado, piloto_2_ordenado)``; como la
``Session`` pertenece a un ``Event`` de una ``Season``, el año de la temporada
queda incluido en la clave de la BD. El nombre de archivo además incorpora el
año de forma explícita para no mezclar 2025 con 2026.

La generación puede tardar: las vistas delegan en ``f1hub.jobs`` (hilo daemon)
y usan esta API desde el worker. La caché expira según
``settings.TELEMETRY_CACHE_TTL_DAYS`` (default 7).
"""

import logging
import os
import re
import tempfile
from datetime import timedelta

import matplotlib.pyplot as plt
from django.conf import settings
from django.utils import timezone

from .models import TelemetryCache

logger = logging.getLogger(__name__)

# Error de dominio: el mensaje es seguro para mostrarlo en la UI (sin tracebacks
# ni detalles técnicos) y el worker lo persiste en la fila del trabajo.
TELEMETRY_UNAVAILABLE_MESSAGE = (
    "Sin tiempos por vuelta disponibles para esta sesión. "
    "Probá con otra sesión o intentá nuevamente más tarde."
)


class TelemetryUnavailable(Exception):
    """No hay tiempos por vuelta utilizables para la sesión o la pareja."""


# Colores fijos de las dos líneas (independientes de la paleta de pilotos).
_LINE_COLORS = ("#E10600", "#3671C6")

try:
    # Capa de datos del otro agente: usa fastf1.ergast (sin login/F1TV).
    from .ergast_service import fetch_lap_comparison
except ImportError:
    # Integración en paralelo: mientras el módulo no exista, el servicio sigue
    # importable y falla con el error de dominio, nunca con ruido de import.
    def fetch_lap_comparison(year, round_number, code1, code2):
        raise TelemetryUnavailable(TELEMETRY_UNAVAILABLE_MESSAGE)


def _canonical_pair(driver1, driver2):
    """Devuelve los dos pilotos ordenados por ``acronym`` (clave sin orden)."""
    return tuple(sorted((driver1, driver2), key=lambda driver: driver.acronym))


def _safe_key_part(value):
    """Componente de nombre de archivo seguro: solo [A-Za-z0-9_-]."""
    return re.sub(r"[^A-Za-z0-9_-]", "", str(value)) or "x"


def build_cache_key(session_obj, driver1, driver2):
    """Clave canónica e independiente del orden: temporada + sesión + pareja.

    Incluye el año de la temporada explícitamente para que el archivo generado
    nunca mezcle datos de distintas temporadas.
    """
    first, second = _canonical_pair(driver1, driver2)
    parts = (
        _safe_key_part(session_obj.event.season.year),
        _safe_key_part(session_obj.id),
        _safe_key_part(first.acronym),
        _safe_key_part(second.acronym),
    )
    return "_".join(parts)


def _ttl_days():
    """Días de validez de la caché, configurables sin romper si falta el setting."""
    try:
        return float(getattr(settings, "TELEMETRY_CACHE_TTL_DAYS", 7))
    except (TypeError, ValueError):
        return 7.0


def _is_fresh(cached, now=None):
    now = now or timezone.now()
    created = cached.created_at
    if created is None:
        return False
    if timezone.is_naive(created):
        created = timezone.make_aware(created, timezone.get_default_timezone())
    return now - created < timedelta(days=_ttl_days())


def _plot_file_path(file_path):
    """Ruta absoluta de un PNG bajo MEDIA_ROOT, o ``None`` si no es segura."""
    if not file_path:
        return None
    value = str(file_path)
    media_root = os.path.abspath(str(settings.MEDIA_ROOT))
    if os.path.isabs(value):
        absolute = os.path.abspath(value)
        try:
            if os.path.commonpath([media_root, absolute]) != media_root:
                return None
        except ValueError:  # unidades distintas en Windows
            return None
        return absolute
    relative = value.replace("\\", "/").lstrip("/")
    if not relative.startswith("telemetry/"):
        return None
    return os.path.join(media_root, *relative.split("/"))


def _remove_plot_file(file_path):
    """Borra un PNG anterior si existe; nunca toca rutas fuera de MEDIA_ROOT."""
    absolute = _plot_file_path(file_path)
    if not absolute or not os.path.isfile(absolute):
        return
    try:
        os.remove(absolute)
    except OSError:
        logger.warning("No se pudo borrar el PNG de telemetría anterior: %s", absolute)


def _lap_times(session_obj, first, second):
    """Devuelve ``(vueltas, segundos_piloto_1, segundos_piloto_2)`` desde Ergast.

    ``first``/``second`` son la pareja canónica (ordenada por ``acronym``), así
    que ``code1_seconds`` siempre corresponde a ``first`` aunque el usuario
    haya elegido los pilotos en orden inverso.
    """
    year = session_obj.event.season.year
    round_number = session_obj.event.round_number
    try:
        rows = fetch_lap_comparison(
            year, round_number, first.acronym, second.acronym
        )
    except TelemetryUnavailable:
        raise
    except Exception as exc:
        logger.warning(
            "No se pudieron obtener tiempos por vuelta para %s/%s en R%s %s: %s",
            first.acronym, second.acronym, round_number, year, exc,
        )
        raise TelemetryUnavailable(TELEMETRY_UNAVAILABLE_MESSAGE) from exc

    points = []
    for row in rows or []:
        try:
            lap = int(row.get("lap"))
            seconds1 = float(row.get("code1_seconds"))
            seconds2 = float(row.get("code2_seconds"))
        except (AttributeError, TypeError, ValueError):
            continue
        points.append((lap, seconds1, seconds2))

    if not points:
        raise TelemetryUnavailable(TELEMETRY_UNAVAILABLE_MESSAGE)

    points.sort(key=lambda item: item[0])
    return (
        [item[0] for item in points],
        [item[1] for item in points],
        [item[2] for item in points],
    )


def _generate_plot(session_obj, first, second, key):
    """Genera el PNG de tiempos por vuelta de forma atómica.

    Devuelve la ruta relativa a MEDIA_ROOT. No hay ``get_session().load()`` ni
    ninguna llamada a live timing: la única fuente es ``fetch_lap_comparison``.
    """
    rel_path = f"telemetry/tel_{key}.png"
    media_dir = os.path.join(str(settings.MEDIA_ROOT), "telemetry")
    os.makedirs(media_dir, exist_ok=True)
    filepath = os.path.join(media_dir, os.path.basename(rel_path))

    laps, seconds_first, seconds_second = _lap_times(session_obj, first, second)
    year = session_obj.event.season.year
    round_number = session_obj.event.round_number

    fig, ax = plt.subplots(figsize=(10, 5))
    tmp_path = None
    try:
        ax.plot(laps, seconds_first, marker="o", color=_LINE_COLORS[0],
                label=first.acronym)
        ax.plot(laps, seconds_second, marker="o", color=_LINE_COLORS[1],
                label=second.acronym)
        ax.set_xlabel("Vuelta")
        ax.set_ylabel("Tiempo por vuelta (s)")
        ax.grid(True, alpha=0.3)
        ax.legend()
        ax.set_title(
            f"TIEMPOS POR VUELTA · {first.acronym} vs {second.acronym}\n"
            f"{session_obj.event.name} · R{round_number} · {year}"
        )
        fig.tight_layout()

        # Escritura atómica: temporal en el MISMO directorio y os.replace.
        fd, tmp_path = tempfile.mkstemp(
            prefix=f"tmp_tel_{key}_", suffix=".png", dir=media_dir
        )
        os.close(fd)
        fig.savefig(tmp_path, format="png")
        os.replace(tmp_path, filepath)
        tmp_path = None
    finally:
        plt.close(fig)
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    return rel_path


def get_cached_telemetry_plot(session_obj, driver1, driver2):
    """Devuelve la ruta en caché si es válida y fresca; si no, la descarta.

    Se usa en la vista como camino rápido (sin lanzar hilos) y dentro de
    ``get_or_generate_telemetry_plot``. Una entrada vencida o sin archivo se
    elimina junto con su PNG para que nunca se sirva telemetría obsoleta.
    """
    first, second = _canonical_pair(driver1, driver2)
    cached = TelemetryCache.objects.filter(
        session=session_obj, driver1=first, driver2=second
    ).first()
    if not cached:
        return ""

    absolute = _plot_file_path(cached.file_path)
    if absolute and os.path.isfile(absolute) and _is_fresh(cached):
        return cached.file_path

    logger.info(
        "Descartando caché de telemetría %s (expirada o sin archivo)", cached.pk
    )
    _remove_plot_file(cached.file_path)
    cached.delete()
    return ""


def get_or_generate_telemetry_plot(session_obj, driver1, driver2):
    """Devuelve la ruta del gráfico de tiempos por vuelta, generándolo si hace falta.

    Si la generación falla, se propaga la excepción original y no queda ninguna
    fila inválida de ``TelemetryCache``: la fila solo se escribe tras éxito y
    cualquier entrada previa vacía/obsoleta se descarta antes de empezar.
    """
    first, second = _canonical_pair(driver1, driver2)
    key = build_cache_key(session_obj, first, second)

    cached_path = get_cached_telemetry_plot(session_obj, first, second)
    if cached_path:
        return cached_path

    # Si quedó un PNG huérfano (BD sin fila, caché vencida, generación previa
    # fallida), se borra antes de regenerar.
    _remove_plot_file(f"telemetry/tel_{key}.png")

    try:
        generated_path = _generate_plot(session_obj, first, second, key)
    except Exception:
        logger.exception(
            "No se pudieron generar los tiempos por vuelta para %s/%s en la sesión %s",
            first.acronym, second.acronym, session_obj.pk,
        )
        raise

    cache, _ = TelemetryCache.objects.update_or_create(
        session=session_obj,
        driver1=first,
        driver2=second,
        defaults={'file_path': generated_path},
    )
    return cache.file_path
