"""Sincroniza las posiciones del campeonato desde Ergast/Jolpica."""

from django.conf import settings
from django.core.management.base import BaseCommand

from f1hub.ergast_service import ErgastServiceError, fetch_standings
from f1hub.models import ConstructorStanding, DriverStanding


class Command(BaseCommand):
    help = "Sync driver and constructor standings from Ergast (Jolpica)"

    def add_arguments(self, parser):
        default_year = getattr(settings, "F1_SEASON_YEAR", 2026)
        parser.add_argument(
            "--year",
            type=int,
            default=default_year,
            help=f"Season to sync (default: {default_year})",
        )

    def handle(self, *args, **options):
        year = options["year"]
        self.stdout.write(f"Fetching {year} standings from Ergast/Jolpica...")

        try:
            driver_rows, constructor_rows = fetch_standings(year)
        except ErgastServiceError as exc:
            self.stdout.write(self.style.ERROR(str(exc)))
            return
        except Exception as exc:  # error inesperado: mensaje claro, sin traceback
            self.stdout.write(
                self.style.ERROR(f"No se pudieron sincronizar las posiciones: {exc}")
            )
            return

        for row in driver_rows:
            DriverStanding.objects.update_or_create(
                season_year=row["season_year"],
                driver_code=row["driver_code"],
                defaults=row,
            )

        for row in constructor_rows:
            ConstructorStanding.objects.update_or_create(
                season_year=row["season_year"],
                constructor_name=row["constructor_name"],
                defaults=row,
            )

        if not driver_rows and not constructor_rows:
            self.stdout.write(
                self.style.WARNING(
                    f"Ergast/Jolpica no publica standings para {year}. "
                    "No se modificaron filas."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Standings {year} sincronizados: "
                f"{len(driver_rows)} pilotos, {len(constructor_rows)} equipos."
            )
        )
        for row in driver_rows[:3]:
            self.stdout.write(
                f"  P{row['position']}: {row['driver_code']} "
                f"{row['driver_name']} - {row['points']} pts"
            )
