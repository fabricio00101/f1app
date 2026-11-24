"""Contexto compartido por todas las plantillas del hub.

El calendario y la próxima carrera se calculan aquí (y no solo en ``dashboard``)
para que el layout base tenga siempre los mismos datos en cada vista.

La carrera se elige por el instante real de su sesión ``Race``:
``Event.date`` es solo el día del GP y no sirve como hora de salida.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import Event, Session

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


def race_context(request):
    """Inyecta calendario, fecha actual y estado del contador en todas las vistas."""
    now = timezone.now()
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
        "season_year": season_year(),
        "calendar_events": Event.objects.filter(season__year=season_year()).order_by("date"),
        "today": timezone.localdate(),
        "next_event": event,
        "countdown": countdown,
    }
