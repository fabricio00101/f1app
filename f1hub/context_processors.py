"""Contexto compartido por todas las plantillas del hub.

El calendario y la próxima carrera se calculan aquí (y no solo en ``dashboard``)
para que el layout base tenga siempre los mismos datos en cada vista.

La carrera se elige por el instante real de su sesión ``Race``:
``Event.date`` es solo el día del GP y no sirve como hora de salida.
"""

from datetime import timedelta

from django.conf import settings
from django.db.utils import DatabaseError
from django.utils import timezone

from . import insights as insights_module
from .models import Event, Session

# Etiqueta única para todas las vistas: los standings se sincronizan desde
# FastF1 (Ergast/Jolpica); las plantillas nunca consultan F1TV ni hacen red.
STANDINGS_SOURCE = "FastF1 (Ergast/Jolpica), sin F1TV"


def season_year():
    """Temporada activa, configurable desde settings (default: 2026)."""
    return getattr(settings, "F1_SEASON_YEAR", 2026)

# Ventana considerada «en curso» desde el inicio de la carrera. No hay un campo
# de fin en el modelo, así que se usa una duración razonable como referencia.
RACE_DURATION = timedelta(hours=2)

STATE_UPCOMING = "upcoming"
STATE_IN_PROGRESS = "in_progress"
STATE_FINISHED = "finished"
STATE_NO_RACES = "no_races"

STATE_LABELS = {
    STATE_UPCOMING: "PRÓXIMA CARRERA",
    STATE_IN_PROGRESS: "EN CURSO",
    STATE_FINISHED: "FINALIZADA",
    STATE_NO_RACES: "SIN PRÓXIMA CARRERA",
}


def get_next_race(now=None):
    """Devuelve ``(estado, evento, sesión)`` para la temporada activa.

    Solo se consideran carreras con sesión ``Race`` y fecha/hora conocida.
    Nunca se devuelve un evento pasado como si fuera el próximo: si ya no hay
    carreras futuras, el estado es ``finished`` y el evento es ``None``.
    """
    now = now or timezone.now()

    races = Session.objects.filter(
        event__season__year=season_year(),
        name="Race",
    ).select_related("event__season").order_by("date_time")

    season_races = list(races)
    if not season_races:
        return STATE_NO_RACES, None, None

    in_progress = [
        race for race in season_races
        if race.date_time <= now < race.date_time + RACE_DURATION
    ]
    if in_progress:
        race = in_progress[-1]
        return STATE_IN_PROGRESS, race.event, race

    upcoming = [race for race in season_races if race.date_time > now]
    if upcoming:
        race = upcoming[0]
        return STATE_UPCOMING, race.event, race

    return STATE_FINISHED, None, None


def _standings_models():
    """Importación diferida de los modelos de clasificación.

    La capa de datos (``ergast_service`` + modelos de standings) se integra en
    paralelo; mientras no esté presente las páginas siguen funcionando con el
    estado vacío de siempre, sin consultar la red.
    """
    try:
        from .models import ConstructorStanding, DriverStanding
    except ImportError:
        return None, None
    return DriverStanding, ConstructorStanding


def standings_context(year=None):
    """Clasificaciones persistidas para ``year``; solo consulta la BD.

    No se hace ninguna petición externa: el comando ``sync_standings`` es el
    único que puede escribir estas tablas. Si solo hay datos de otra temporada
    se exponen los años disponibles para que la UI lo diga con honestidad, sin
    presentar cifras ajenas como si fueran de la temporada activa.
    """
    year = season_year() if year is None else year
    result = {
        "driver_standings": [],
        "constructor_standings": [],
        "standings_year": year,
        "standings_other_years": [],
    }
    driver_model, constructor_model = _standings_models()
    if driver_model is None or constructor_model is None:
        return result

    try:
        result["driver_standings"] = list(
            driver_model.objects.filter(season_year=year).order_by("position")
        )
        result["constructor_standings"] = list(
            constructor_model.objects.filter(season_year=year).order_by("position")
        )
        result["standings_other_years"] = sorted(
            set(driver_model.objects.values_list("season_year", flat=True))
            | set(constructor_model.objects.values_list("season_year", flat=True))
        )
    except DatabaseError:
        # Tabla todavía no migrada durante la integración: estado vacío.
        return {
            "driver_standings": [],
            "constructor_standings": [],
            "standings_year": year,
            "standings_other_years": [],
        }
    return result


def race_context(request):
    """Inyecta calendario, fecha actual y estado del contador en todas las vistas."""
    now = timezone.now()
    year = season_year()
    state, event, race = get_next_race(now)
    starts_at = race.date_time if race else None

    countdown = {
        "status": state,
        "label": STATE_LABELS[state],
        "event": event,
        "event_name": event.name if event else "",
        "session_name": race.name if race else "",
        "starts_at": starts_at,
        "ends_at": starts_at + RACE_DURATION if starts_at else None,
        # ISO 8601 con offset: JS lo interpreta sin asumir las 15:00 UTC.
        "target": starts_at.isoformat() if starts_at else "",
        "end_target": (starts_at + RACE_DURATION).isoformat() if starts_at else "",
        "timezone": settings.TIME_ZONE,
    }

    return {
        "season_year": year,
        "calendar_events": Event.objects.filter(season__year=year).order_by("date"),
        "today": timezone.localdate(),
        "next_event": event,
        "countdown": countdown,
        # La página de análisis reutiliza los datos reales ya calculados aquí
        # (temporada y carrera del contador) para no repetir consultas.
        "insights": insights_module.build_insights(
            now=now, race=race, year=year
        ),
        # Clasificación real ya guardada en la BD (sin red en el request).
        "standings_source": STANDINGS_SOURCE,
        **standings_context(year),
    }
