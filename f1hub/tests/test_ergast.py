"""Tests SIN RED de la capa Ergast/Jolpica (mockeamos fastf1.ergast.Ergast)."""

from io import StringIO

import pandas as pd
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from unittest.mock import MagicMock, patch

from f1hub.ergast_service import (
    ErgastServiceError,
    clear_cache,
    fetch_lap_comparison,
    fetch_standings,
)
from f1hub.models import ConstructorStanding, DriverStanding


class FakeMultiResponse:
    """Sustituye a ErgastMultiResponse: expone ``.content``."""

    def __init__(self, frames):
        self.content = frames


class ErgastServiceTests(TestCase):
    def setUp(self):
        clear_cache()
        self.client = MagicMock()
        self.client_patch = patch("fastf1.ergast.Ergast", return_value=self.client)
        self.ergast_cls = self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.addCleanup(clear_cache)

    def _standings_response(self):
        drivers = pd.DataFrame(
            [
                {
                    "position": 2,
                    "points": 421.0,
                    "wins": 8,
                    "driverCode": "VER",
                    "givenName": "Max",
                    "familyName": "Verstappen",
                    "constructorNames": ["Red Bull"],
                },
                {
                    "position": 1,
                    "points": "423.0",
                    "wins": "7",
                    "driverCode": "NOR",
                    "givenName": "Lando",
                    "familyName": "Norris",
                    "constructorNames": ["McLaren"],
                },
            ]
        )
        constructors = pd.DataFrame(
            [
                {
                    "position": 2,
                    "points": 469.0,
                    "wins": 2,
                    "constructorName": "Mercedes",
                },
                {
                    "position": 1,
                    "points": "833.0",
                    "wins": "14",
                    "constructorName": "McLaren",
                },
            ]
        )
        self.client.get_driver_standings.return_value = FakeMultiResponse([drivers])
        self.client.get_constructor_standings.return_value = FakeMultiResponse(
            [constructors]
        )

    def test_fetch_standings_normalizes_rows_and_sorts_by_position(self):
        self._standings_response()

        driver_rows, constructor_rows = fetch_standings(2025)

        self.assertEqual(self.ergast_cls.call_count, 1)
        self.assertEqual(
            driver_rows,
            [
                {
                    "season_year": 2025,
                    "position": 1,
                    "points": 423.0,
                    "wins": 7,
                    "driver_code": "NOR",
                    "driver_name": "Lando Norris",
                    "constructor_name": "McLaren",
                },
                {
                    "season_year": 2025,
                    "position": 2,
                    "points": 421.0,
                    "wins": 8,
                    "driver_code": "VER",
                    "driver_name": "Max Verstappen",
                    "constructor_name": "Red Bull",
                },
            ],
        )
        self.assertEqual(
            constructor_rows,
            [
                {
                    "season_year": 2025,
                    "position": 1,
                    "points": 833.0,
                    "wins": 14,
                    "constructor_name": "McLaren",
                },
                {
                    "season_year": 2025,
                    "position": 2,
                    "points": 469.0,
                    "wins": 2,
                    "constructor_name": "Mercedes",
                },
            ],
        )

    def test_fetch_standings_uses_cache(self):
        self._standings_response()

        first = fetch_standings(2041)
        second = fetch_standings(2041)

        self.assertEqual(first, second)
        self.assertEqual(self.ergast_cls.call_count, 1)

    def test_clear_cache_forces_a_new_request(self):
        self._standings_response()

        fetch_standings(2042)
        clear_cache()
        fetch_standings(2042)

        self.assertEqual(self.ergast_cls.call_count, 2)

    def test_fetch_standings_empty_response(self):
        self.client.get_driver_standings.return_value = FakeMultiResponse([])
        self.client.get_constructor_standings.return_value = FakeMultiResponse([])
        self.assertEqual(fetch_standings(2043), ([], []))

    def test_fetch_standings_network_error_is_clear(self):
        self.client.get_driver_standings.side_effect = ConnectionError("sin red")

        with self.assertRaises(ErgastServiceError) as ctx:
            fetch_standings(2044)

        self.assertIn("No se pudieron obtener", str(ctx.exception))

    def _lap_responses(self):
        # get_driver_info devuelve un DataFrame simple (sin .content).
        self.client.get_driver_info.return_value = pd.DataFrame(
            [
                {"driverId": "norris", "driverCode": "NOR"},
                {"driverId": "max_verstappen", "driverCode": "VER"},
            ]
        )
        norris = pd.DataFrame(
            [
                {"number": 1, "time": pd.Timedelta(seconds=93.952)},
                {"number": 2, "time": "1:29.893"},
                {"number": 3, "time": None},  # vuelta inválida: se descarta
            ]
        )
        verstappen = pd.DataFrame(
            [
                {"number": 1, "time": "1:34.100"},
                {"number": 2, "time": pd.Timedelta(seconds=90.100)},
                {"number": 4, "time": "1:30.000"},  # sin par: se descarta
            ]
        )
        self.client.get_lap_times.side_effect = [
            FakeMultiResponse([norris]),
            FakeMultiResponse([verstappen]),
        ]

    def test_fetch_lap_comparison_converts_times_and_keeps_shared_laps(self):
        self._lap_responses()

        rows = fetch_lap_comparison(2025, 24, "nor", "VER")

        self.assertEqual(
            rows,
            [
                {"lap": 1, "code1_seconds": 93.952, "code2_seconds": 94.1},
                {"lap": 2, "code1_seconds": 89.893, "code2_seconds": 90.1},
            ],
        )
        self.assertEqual(self.client.get_lap_times.call_args_list[0].kwargs["driver"], "norris")
        self.assertEqual(
            self.client.get_lap_times.call_args_list[1].kwargs["driver"],
            "max_verstappen",
        )

    def test_fetch_lap_comparison_no_data(self):
        self.client.get_driver_info.return_value = pd.DataFrame(
            [{"driverId": "norris", "driverCode": "NOR"}]
        )
        self.client.get_lap_times.side_effect = [
            FakeMultiResponse([pd.DataFrame(columns=["number", "time"])]),
            FakeMultiResponse([pd.DataFrame(columns=["number", "time"])]),
        ]
        self.assertEqual(fetch_lap_comparison(2025, 24, "NOR", "VER"), [])

    def test_fetch_lap_comparison_network_error_is_clear(self):
        self.client.get_driver_info.return_value = pd.DataFrame(
            [{"driverId": "norris", "driverCode": "NOR"}]
        )
        self.client.get_lap_times.side_effect = ConnectionError("sin red")

        with self.assertRaises(ErgastServiceError) as ctx:
            fetch_lap_comparison(2025, 24, "NOR", "VER")

        self.assertIn("No se pudieron obtener las vueltas", str(ctx.exception))


class SyncStandingsCommandTests(TestCase):
    def test_command_is_idempotent_and_prints_summary(self):
        rows = (
            [
                {
                    "season_year": 2051,
                    "position": 1,
                    "points": 100.0,
                    "wins": 5,
                    "driver_code": "AAA",
                    "driver_name": "Piloto Uno",
                    "constructor_name": "Equipo A",
                }
            ],
            [
                {
                    "season_year": 2051,
                    "position": 1,
                    "points": 200.0,
                    "wins": 6,
                    "constructor_name": "Equipo A",
                }
            ],
        )
        out = StringIO()
        with patch(
            "f1hub.management.commands.sync_standings.fetch_standings",
            return_value=rows,
        ) as fetch:
            call_command("sync_standings", year=2051, stdout=out)
            call_command("sync_standings", year=2051, stdout=out)

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(DriverStanding.objects.filter(season_year=2051).count(), 1)
        self.assertEqual(
            ConstructorStanding.objects.filter(season_year=2051).count(), 1
        )
        self.assertIn("1 pilotos, 1 equipos", out.getvalue())

    def test_command_reports_network_error_without_traceback(self):
        out = StringIO()
        with patch(
            "f1hub.management.commands.sync_standings.fetch_standings",
            side_effect=ErgastServiceError("sin red"),
        ):
            call_command("sync_standings", year=2052, stdout=out)

        self.assertIn("sin red", out.getvalue())
        self.assertEqual(DriverStanding.objects.count(), 0)


class StandingModelTests(TestCase):
    def test_str_and_ordering(self):
        DriverStanding.objects.create(
            season_year=2053,
            position=2,
            points=1.0,
            wins=0,
            driver_code="BBB",
            driver_name="Piloto Dos",
            constructor_name="Equipo B",
        )
        first = DriverStanding.objects.create(
            season_year=2053,
            position=1,
            points=9.0,
            wins=1,
            driver_code="AAA",
            driver_name="Piloto Uno",
            constructor_name="Equipo A",
        )
        ConstructorStanding.objects.create(
            season_year=2053,
            position=1,
            points=9.0,
            wins=1,
            constructor_name="Equipo A",
        )

        self.assertEqual(list(DriverStanding.objects.all()), [first, DriverStanding.objects.get(driver_code="BBB")])
        self.assertEqual(str(first), "1. Piloto Uno (AAA) - 2053")
        self.assertEqual(
            str(ConstructorStanding.objects.get(constructor_name="Equipo A")),
            "1. Equipo A - 2053",
        )

    def test_unique_together(self):
        values = {
            "season_year": 2054,
            "position": 1,
            "points": 1.0,
            "wins": 0,
            "driver_code": "AAA",
            "driver_name": "Piloto Uno",
            "constructor_name": "Equipo A",
        }
        DriverStanding.objects.create(**values)
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                DriverStanding.objects.create(**values)
