"""Constructores mínimos para los tests (sin red, sin depender de la BD de desarrollo)."""

from datetime import date as date_cls, datetime, time, timezone as dt_timezone

from f1hub.models import Driver, Event, Season, Session


def make_season(year=2026):
    return Season.objects.create(year=year, regulations="Reglamento de prueba")


def make_event(season, round_number=1, event_date=None, name=None, location=None):
    return Event.objects.create(
        season=season,
        round_number=round_number,
        date=event_date or date_cls(2026, 3, 1),
        name=name or f"Gran Premio de Prueba {round_number}",
        location=location or "Sede de prueba",
    )


def make_session(event, name="Race", date_time=None):
    dt = date_time or datetime.combine(event.date, time(12), tzinfo=dt_timezone.utc)
    return Session.objects.create(event=event, name=name, date_time=dt)


def make_driver(acronym="VER", name=None, team=None, nationality=None):
    return Driver.objects.create(
        acronym=acronym,
        name=name or "Driver de Prueba",
        team=team or "Equipo de Prueba",
        nationality=nationality or "ARG",
    )
