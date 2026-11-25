"""Datos reales para la vista de análisis, calculados solo desde la BD local.

Todas las funciones son deterministas y no hacen peticiones de red. FastF1
incluye ``fastf1.ergast.Ergast.get_driver_standings`` y
``get_constructor_standings`` (sin credenciales), pero ambas consultan la API
HTTP de Jolpica: usarlas aquí haría que cada página dependiera de red y de que
la temporada en curso ya tenga datos publicados. Por eso no se consultan y la
interfaz indica explícitamente que no hay clasificación oficial cargada.
"""

from django.conf import settings
from django.db.models import Count, Max, Q
from django.utils import timezone

from .models import Driver, Session, TelemetryCache

RECENT_GP_LIMIT = 5


def season_year():
    """Temporada activa (la misma regla que usa el contexto compartido)."""
    return getattr(settings, "F1_SEASON_YEAR", 2026)


def _race_duration():
    """Ventana que usa el contador del layout para dar por terminada una carrera."""
    # Import diferido: el context processor importa este módulo, así que un
    # import a nivel de módulo crearía un ciclo.
    from .context_processors import RACE_DURATION

    return RACE_DURATION


def next_gp(race=None, now=None):
    """Próxima carrera y días naturales que faltan para su sesión ``Race``.

    ``race`` puede ser la sesión que ya calculó el context processor para el
    contador del layout; así se evita repetir la consulta. Si no se pasa, se
    busca la primera sesión ``Race`` futura de la temporada activa.
    """
    now = now or timezone.now()
    if race is None:
        race = (
            Session.objects.filter(
                event__season__year=season_year(),
                name="Race",
                date_time__gt=now,
            )
            .select_related("event")
            .order_by("date_time")
            .first()
        )

    if race is None:
        return {
            "event": None,
            "name": "",
            "location": "",
            "date": None,
            "starts_at": None,
            "days": None,
            "has_race": False,
        }

    event = race.event
    # Días naturales en la zona horaria del proyecto; 0 si ya comenzó.
    days = max(
        0,
        (timezone.localdate(race.date_time) - timezone.localdate(now)).days,
    )
    return {
        "event": event,
        "name": event.name,
        "location": event.location,
        "date": event.date,
        "starts_at": race.date_time,
        "days": days,
        "has_race": True,
    }


def recent_gps(limit=RECENT_GP_LIMIT, now=None, year=None):
    """Últimas carreras finalizadas, con la fecha y la sede reales."""
    now = now or timezone.now()
    year = year or season_year()
    if limit <= 0:
        return []

    finished_before = now - _race_duration()
    races = (
        Session.objects.filter(
            event__season__year=year,
            name="Race",
            date_time__lte=finished_before,
        )
        .select_related("event")
        .order_by("-date_time")[:limit]
    )
    return [
        {
            "name": row.event.name,
            "location": row.event.location,
            "date": row.event.date,
            "starts_at": row.date_time,
            "round": row.event.round_number,
        }
        for row in races
    ]


def season_summary(now=None, year=None):
    """Totales reales de sesiones, pilotos y equipos de la temporada."""
    now = now or timezone.now()
    year = year or season_year()

    totals = Session.objects.filter(event__season__year=year).aggregate(
        sessions=Count("pk"),
        past=Count("pk", filter=Q(date_time__lte=now)),
    )
    drivers = Driver.objects.filter(season__year=year)
    teams = list(
        drivers.exclude(team="")
        .order_by("team")
        .values_list("team", flat=True)
        .distinct()
    )
    return {
        "sessions": totals["sessions"],
        "past_sessions": totals["past"],
        "future_sessions": totals["sessions"] - totals["past"],
        "drivers": drivers.count(),
        "team_count": len(teams),
        "teams": teams,
    }


def telemetry_status(year=None):
    """Estado de la caché de telemetría de la temporada."""
    year = year or season_year()
    stats = TelemetryCache.objects.filter(
        session__event__season__year=year
    ).aggregate(
        comparisons=Count("pk"),
        sessions=Count("session", distinct=True),
        last_created_at=Max("created_at"),
    )
    return {
        "comparisons": stats["comparisons"],
        "sessions": stats["sessions"],
        "last_created_at": stats["last_created_at"],
        "available": bool(stats["comparisons"]),
    }


def build_insights(now=None, race=None, year=None, recent_limit=RECENT_GP_LIMIT):
    """Conjunto completo de datos reales que consume la plantilla de análisis."""
    now = now or timezone.now()
    year = year or season_year()
    return {
        "next_gp": next_gp(race=race, now=now),
        "recent_gps": recent_gps(limit=recent_limit, now=now, year=year),
        "season": season_summary(now=now, year=year),
        "telemetry": telemetry_status(year=year),
    }
