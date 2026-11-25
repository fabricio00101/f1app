"""Servicio de generación y caché del gráfico de telemetría (Distance vs Speed).

La API pública es ``get_or_generate_telemetry_plot(session, driver1, driver2)``
y ``get_cached_telemetry_plot(session, driver1, driver2)`` (solo lectura).

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

import fastf1
import fastf1.plotting
import matplotlib.pyplot as plt
from django.conf import settings
from django.utils import timezone

from .models import TelemetryCache

logger = logging.getLogger(__name__)

# Error de dominio: el mensaje es seguro para mostrarlo en la UI (sin tracebacks
# ni detalles técnicos) y el worker lo persiste en la fila del trabajo.
TELEMETRY_UNAVAILABLE_MESSAGE = (
    "No hay vueltas ni telemetría disponibles para estos pilotos en la sesión "
    "seleccionada. Probá con otra sesión o intentá nuevamente más tarde."
)


class TelemetryUnavailable(Exception):
    """No hay datos de telemetría utilizables para la sesión o la pareja."""


# Colores fijos para siglas que fastf1 no reconoce (p. ej. pilotos nuevos de 2026).
_FALLBACK_COLORS = ("#E10600", "#3671C6", "#FF8000", "#27F4D2", "#009688", "#C800FF")

_SESSION_MAPPING = {
    'FP1': 'FP1', 'FP2': 'FP2', 'FP3': 'FP3',
    'Qualifying': 'Q', 'Sprint Shootout': 'SQ',
    'Sprint': 'S', 'Race': 'R',
}


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


def _resolve_driver_color(acronym, season, index=0, f1_session=None):
    """Color del piloto con la API nueva, la legacy o la paleta fija.

    En fastf1 3.9.2 la firma es ``get_driver_color(identifier, session)`` y
    recibe el objeto ``Session`` ya cargado (se pasa como ``f1_session``).
    Las versiones 3.6-3.8 usaban el año en su lugar y 3.5.3 exportaba
    ``driver_color``. Se prueban todas; cualquier ``KeyError`` / ``TypeError``
    con siglas nuevas (p. ej. ANT en 2026) cae a la paleta fija sin romper el
    gráfico. ``f1_session`` es opcional para mantener la API del shim en tests.
    """
    candidates = []
    getter = getattr(fastf1.plotting, "get_driver_color", None)
    if callable(getter):
        if f1_session is not None:
            candidates.append(lambda: getter(acronym, f1_session))  # API >= 3.9
        candidates.append(lambda: getter(acronym, season))          # API 3.6-3.8
        candidates.append(lambda: getter(acronym))                  # API intermedia
    legacy = getattr(fastf1.plotting, "driver_color", None)
    if callable(legacy):
        candidates.append(lambda: legacy(acronym))           # API <= 3.5.3

    for candidate in candidates:
        try:
            color = candidate()
        except Exception:
            continue
        if isinstance(color, str) and color.strip():
            return color
        if isinstance(color, (tuple, list)) and len(color) >= 3:
            return tuple(color[:3])
    return _FALLBACK_COLORS[index % len(_FALLBACK_COLORS)]


def _generate_plot(session_obj, first, second, key):
    """Genera el PNG de forma atómica y devuelve su ruta relativa a MEDIA_ROOT."""
    rel_path = f"telemetry/tel_{key}.png"
    media_dir = os.path.join(str(settings.MEDIA_ROOT), "telemetry")
    os.makedirs(media_dir, exist_ok=True)
    filepath = os.path.join(media_dir, os.path.basename(rel_path))

    # Configuración de FastF1 / matplotlib (API de fastf1 3.9.2).
    # ``configure`` exige que el directorio exista, incluso en un deploy nuevo.
    cache_dir = os.path.join(str(settings.BASE_DIR), 'fastf1_cache')
    os.makedirs(cache_dir, exist_ok=True)
    fastf1.Cache.configure(cache_dir=str(cache_dir))
    fastf1.plotting.setup_mpl()

    session_identifier = _SESSION_MAPPING.get(
        session_obj.name, session_obj.name
    )
    f1_session = fastf1.get_session(
        session_obj.event.season.year,
        session_obj.event.round_number,
        session_identifier,
    )
    # Sin esta llamada, ``Session.laps`` lanza DataNotLoadedError en fastf1 3.x.
    # Solo se cargan las vueltas y la telemetría que usa este gráfico.
    try:
        f1_session.load(laps=True, telemetry=True, weather=False, messages=False)
    except Exception as exc:
        logger.warning("No se pudo cargar la sesión de FastF1: %s", exc)
        raise TelemetryUnavailable(TELEMETRY_UNAVAILABLE_MESSAGE) from exc

    try:
        laps_first = f1_session.laps.pick_driver(first.acronym)
        laps_second = f1_session.laps.pick_driver(second.acronym)
        if laps_first.empty or laps_second.empty:
            raise TelemetryUnavailable(TELEMETRY_UNAVAILABLE_MESSAGE)

        tel_first = laps_first.pick_fastest().get_telemetry().add_distance()
        tel_second = laps_second.pick_fastest().get_telemetry().add_distance()
        if getattr(tel_first, "empty", False) or getattr(tel_second, "empty", False):
            raise TelemetryUnavailable(TELEMETRY_UNAVAILABLE_MESSAGE)
    except TelemetryUnavailable:
        raise
    except Exception as exc:
        logger.warning("Telemetría no disponible para la sesión %s: %s", session_obj.pk, exc)
        raise TelemetryUnavailable(TELEMETRY_UNAVAILABLE_MESSAGE) from exc

    season = session_obj.event.season.year
    color_first = _resolve_driver_color(first.acronym, season, 0, f1_session)
    color_second = _resolve_driver_color(second.acronym, season, 1, f1_session)

    fig, ax = plt.subplots(figsize=(10, 5))
    tmp_path = None
    try:
        ax.plot(tel_first['Distance'], tel_first['Speed'],
                color=color_first, label=f"{first.acronym}")
        ax.plot(tel_second['Distance'], tel_second['Speed'],
                color=color_second, label=f"{second.acronym}")
        ax.set_xlabel('Distance in m')
        ax.set_ylabel('Speed in km/h')
        ax.legend()
        ax.set_title(
            f"Fastest Lap Telemetry: {first.acronym} vs {second.acronym}\n"
            f"{session_obj.event.name} {season}"
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
    """Devuelve la ruta del gráfico de telemetría, generándolo si hace falta.

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
            "No se pudo generar la telemetría para %s/%s en la sesión %s",
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
