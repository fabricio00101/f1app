"""Tests de modelos: representación, orden, unicidad y valores por defecto."""

from datetime import datetime, time, timedelta, timezone as dt_timezone

from django.db import IntegrityError, transaction
from django.test import TestCase

from f1hub.models import Event, Session, TelemetryCache
from .helpers import make_driver, make_event, make_season, make_session


class SeasonModelTests(TestCase):
    def test_str(self):
        self.assertEqual(str(make_season(2026)), "2026 Season")


class EventModelTests(TestCase):
    def test_str_includes_round_name_and_year(self):
        season = make_season(2026)
        event = make_event(season, round_number=3, name="Australian Grand Prix")
        self.assertEqual(str(event), "Round 3: Australian Grand Prix (2026)")

    def test_events_are_ordered_by_date(self):
        season = make_season()
        later = make_event(season, round_number=2, event_date=datetime(2026, 3, 8).date())
        earlier = make_event(season, round_number=1, event_date=datetime(2026, 3, 1).date())
        self.assertEqual(list(Event.objects.all()), [earlier, later])

    def test_round_number_is_unique_per_season(self):
        season = make_season()
        make_event(season, round_number=1)
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                make_event(season, round_number=1)


class SessionModelTests(TestCase):
    def test_str(self):
        season = make_season()
        event = make_event(season, name="Monza GP")
        session = make_session(event, name="Qualifying")
        self.assertEqual(str(session), "Monza GP - Qualifying")

    def test_status_defaults_to_pending(self):
        session = make_session(make_event(make_season()))
        self.assertEqual(session.status, "Pending")

    def test_datetime_remains_timezone_aware_after_roundtrip(self):
        event = make_event(make_season())
        aware_dt = datetime(2026, 3, 1, 15, 0, tzinfo=dt_timezone.utc)
        session = make_session(event, date_time=aware_dt)
        session.refresh_from_db()
        self.assertIsNotNone(session.date_time.tzinfo)
        self.assertEqual(session.date_time.utcoffset(), timedelta(0))


class DriverModelTests(TestCase):
    def test_str(self):
        driver = make_driver(acronym="VER", name="Max Verstappen")
        self.assertEqual(str(driver), "Max Verstappen (VER)")

    def test_acronym_is_unique(self):
        make_driver(acronym="VER")
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                make_driver(acronym="VER", name="Otro piloto")


class TelemetryCacheModelTests(TestCase):
    def test_str(self):
        event = make_event(make_season())
        session = make_session(event)
        driver1 = make_driver("VER", name="Max Verstappen")
        driver2 = make_driver("NOR", name="Lando Norris")
        cache = TelemetryCache.objects.create(
            session=session,
            driver1=driver1,
            driver2=driver2,
            file_path="/media/telemetry/VER_NOR.png",
        )
        self.assertEqual(
            str(cache),
            "Telemetry: VER vs NOR - Gran Premio de Prueba 1 - Race",
        )

    def test_same_session_and_pair_cannot_be_cached_twice(self):
        session = make_session(make_event(make_season()))
        driver1 = make_driver("VER")
        driver2 = make_driver("NOR")
        TelemetryCache.objects.create(
            session=session, driver1=driver1, driver2=driver2, file_path="a.png"
        )

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                TelemetryCache.objects.create(
                    session=session, driver1=driver1, driver2=driver2, file_path="b.png"
                )


class DriverSeasonTests(TestCase):
    def test_driver_can_be_assigned_to_a_season(self):
        season = make_season(2027)
        driver = make_driver("ANT")
        driver.season = season
        driver.save(update_fields=["season"])

        driver.refresh_from_db()
        self.assertEqual(driver.season, season)
        self.assertEqual(list(season.drivers.all()), [driver])
