"""Capa de datos pública: standings y tiempos por vuelta vía ``fastf1.ergast``.

Sólo se usa el cliente de Ergast/Jolpica (sin F1TV, sin credenciales). Las
respuestas se normalizan a diccionarios simples y se cachean en la caché local
de Django para no golpear la red en cada petición.
"""

import logging
import math

import pandas as pd
from django.core.cache import cache

from fastf1 import ergast as fastf1_ergast

logger = logging.getLogger(__name__)

CACHE_TIMEOUT = 3600
_STANDINGS_CACHE_KEY = "f1hub:ergast:standings:{year}"
_LAPS_CACHE_KEY = "f1hub:ergast:laps:{year}:{round_number}:{code1}:{code2}"

# Límite por página del API (Ergast/Jolpica admite hasta 1000).
_API_LIMIT = 1000


class ErgastServiceError(Exception):
    """Fallo de red o de datos al consultar Ergast/Jolpica."""


def clear_cache():
    """Limpia la caché local (locmem). Útil para aislar tests."""
    cache.clear()


def _frames(response):
    """Devuelve una lista de DataFrames para respuestas simples o múltiples."""
    if response is None:
        return []
    content = getattr(response, "content", None)
    if content is None:
        # ErgastSimpleResponse es directamente un DataFrame.
        return [response] if hasattr(response, "columns") else []
    if isinstance(content, (list, tuple)):
        return [frame for frame in content if frame is not None and len(frame)]
    return [content] if len(content) else []


def _int(value, default=0):
    try:
        if value is None or pd.isna(value):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default=0.0):
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value):
    if value is None:
        return ""
    if not isinstance(value, (str, bytes)) and hasattr(value, "__len__"):
        # p. ej. constructorNames llega como una lista/array de un elemento.
        return _text(value[0]) if len(value) else ""
    text = str(value).strip()
    return "" if text in {"nan", "None", "<NA>", "NaT"} else text


def _seconds(value):
    """Convierte un tiempo de vuelta a segundos, o ``None`` si es inválido."""
    if value is None:
        return None
    if hasattr(value, "total_seconds"):
        return float(value.total_seconds())
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None if math.isnan(float(value)) else float(value)
    text = str(value).strip()
    if not text or text in {"nan", "NaT", "None", "<NA>"}:
        return None
    if "day" in text:
        try:
            return float(pd.Timedelta(text).total_seconds())
        except (TypeError, ValueError):
            return None
    parts = text.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
        if len(parts) == 2:
            minutes, seconds = parts
            return float(minutes) * 60 + float(seconds)
        return float(parts[0])
    except (TypeError, ValueError):
        return None


def _cached(key, producer):
    value = cache.get(key)
    if value is not None:
        return value
    value = producer()
    cache.set(key, value, CACHE_TIMEOUT)
    return value


def fetch_standings(year):
    """Devuelve ``(driver_rows, constructor_rows)`` para una temporada.

    Cada fila es un dict con las claves del contrato. Si el API no publica
    standings para ese año, devuelve ``([], [])``.
    """
    year = int(year)
    key = _STANDINGS_CACHE_KEY.format(year=year)

    def load():
        try:
            client = fastf1_ergast.Ergast()
            drivers_response = client.get_driver_standings(season=year, limit=_API_LIMIT)
            constructors_response = client.get_constructor_standings(
                season=year, limit=_API_LIMIT
            )
        except Exception as exc:
            logger.warning("Error al consultar standings de Ergast (%s): %s", year, exc)
            raise ErgastServiceError(
                f"No se pudieron obtener las posiciones de {year} desde Ergast/Jolpica."
            ) from exc

        driver_rows = []
        seen_codes = set()
        for frame in _frames(drivers_response):
            for _, row in frame.iterrows():
                code = _text(row.get("driverCode"))
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                driver_rows.append(
                    {
                        "season_year": year,
                        "position": _int(row.get("position")),
                        "points": _float(row.get("points")),
                        "wins": _int(row.get("wins")),
                        "driver_code": code,
                        "driver_name": " ".join(
                            part
                            for part in (
                                _text(row.get("givenName")),
                                _text(row.get("familyName")),
                            )
                            if part
                        ),
                        "constructor_name": _text(row.get("constructorNames")),
                    }
                )

        constructor_rows = []
        seen_teams = set()
        for frame in _frames(constructors_response):
            for _, row in frame.iterrows():
                team = _text(row.get("constructorName"))
                if not team or team in seen_teams:
                    continue
                seen_teams.add(team)
                constructor_rows.append(
                    {
                        "season_year": year,
                        "position": _int(row.get("position")),
                        "points": _float(row.get("points")),
                        "wins": _int(row.get("wins")),
                        "constructor_name": team,
                    }
                )

        driver_rows.sort(key=lambda row: row["position"])
        constructor_rows.sort(key=lambda row: row["position"])
        return driver_rows, constructor_rows

    return _cached(key, load)


def _column(frame, names):
    for name in names:
        if name in frame.columns:
            return name
    return None


def _driver_ids(client, year, codes):
    """Mapea códigos de piloto (NOR) a ``driverId`` del API (norris)."""
    mapping = {}
    try:
        response = client.get_driver_info(season=year, limit=_API_LIMIT)
    except Exception as exc:
        logger.warning("Error al consultar pilotos de Ergast (%s): %s", year, exc)
        return mapping
    for frame in _frames(response):
        for _, row in frame.iterrows():
            code = _text(row.get("driverCode")).upper()
            driver_id = _text(row.get("driverId"))
            if code and driver_id:
                mapping[code] = driver_id
    return mapping


def _lap_times_for(client, year, round_number, driver_id):
    """Devuelve ``{numero_de_vuelta: segundos}`` para un ``driverId``."""
    times = {}
    try:
        response = client.get_lap_times(
            season=year, round=round_number, driver=driver_id, limit=_API_LIMIT
        )
    except Exception as exc:
        logger.warning(
            "Error al consultar vueltas de Ergast (%s/%s, %s): %s",
            year,
            round_number,
            driver_id,
            exc,
        )
        raise ErgastServiceError(
            f"No se pudieron obtener las vueltas de {year}, ronda {round_number}."
        ) from exc

    for frame in _frames(response):
        lap_column = _column(frame, ("number", "lap", "lapNumber", "lap_number"))
        time_column = _column(frame, ("time", "lapTime", "lap_time"))
        if lap_column is None or time_column is None:
            continue
        for _, row in frame.iterrows():
            lap = _int(row.get(lap_column), default=0)
            seconds = _seconds(row.get(time_column))
            if lap > 0 and seconds is not None:
                times[lap] = seconds
    return times


def fetch_lap_comparison(year, round_number, code1, code2):
    """Vueltas en las que ambos pilotos registraron tiempo.

    Devuelve una lista de dicts ``{"lap", "code1_seconds", "code2_seconds"}``
    ordenada por vuelta. Sin datos comunes devuelve ``[]``.
    """
    year = int(year)
    round_number = int(round_number)
    code1 = str(code1).upper()
    code2 = str(code2).upper()
    key = _LAPS_CACHE_KEY.format(
        year=year, round_number=round_number, code1=code1, code2=code2
    )

    def load():
        try:
            client = fastf1_ergast.Ergast()
        except Exception as exc:
            logger.warning("Error al crear el cliente de Ergast: %s", exc)
            raise ErgastServiceError("No se pudo conectar con Ergast/Jolpica.") from exc

        if code1 == code2:
            times1 = _lap_times_for(client, year, round_number, code1.lower())
            times2 = times1
        else:
            mapping = _driver_ids(client, year, (code1, code2))
            times1 = _lap_times_for(
                client, year, round_number, mapping.get(code1, code1.lower())
            )
            times2 = _lap_times_for(
                client, year, round_number, mapping.get(code2, code2.lower())
            )

        return [
            {"lap": lap, "code1_seconds": times1[lap], "code2_seconds": times2[lap]}
            for lap in sorted(times1.keys() & times2.keys())
        ]

    return _cached(key, load)
