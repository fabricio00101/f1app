"""Tests del servicio de telemetría: sin red y con MEDIA_ROOT temporal."""

import os
import tempfile
from datetime import timedelta
from unittest.mock import MagicMock, patch

import matplotlib
matplotlib.use("Agg")  # backend headless: los tests no abren ventanas
import pandas as pd
from django.test import TestCase, override_settings
from django.utils import timezone

from f1hub import services
from f1hub.models import TelemetryCache
from f1hub.services import build_cache_key, get_or_generate_telemetry_plot

from .helpers import make_driver, make_event, make_season, make_session


class FakeTelemetry:
    """Telemetría mínima con la interfaz que usa el servicio."""

    def __init__(self):
        self.data = {
            "Distance": pd.Series([0.0, 100.0, 200.0]),
            "Speed": pd.Series([300.0, 310.0, 305.0]),
        }

    def add_distance(self):
        return self

    def __getitem__(self, key):
        return self.data[key]


class TelemetryServiceTests(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.media_root = self.tmpdir.name
        self.enterContext(self.settings(MEDIA_ROOT=self.media_root))

        self.fastf1_mock = self.enterContext(patch("f1hub.services.fastf1"))

        self.season = make_season(2026)
        self.event = make_event(self.season, round_number=1, name="Gran Premio de Prueba")
        self.session = make_session(self.event, name="Race")

        self.ver = make_driver("VER", "Max Verstappen", "Red Bull", "NED")
        self.col = make_driver("COL", "Franco Colapinto", "Alpine", "ARG")
        self.ant = make_driver("ANT", "Piloto 2026", "Equipo 2026", "ARG")

        self._stub_fastf1()

    def _stub_fastf1(self):
        """Hace que pick_driver devuelva vueltas/telemetría falsas por sigla."""
        laps_by_code = {}
        for code in ("VER", "COL", "ANT"):
            laps = MagicMock()
            laps.empty = False
            laps.pick_fastest.return_value.get_telemetry.return_value = FakeTelemetry()
            laps_by_code[code] = laps
        self.fastf1_mock.get_session.return_value.laps.pick_driver.side_effect = (
            lambda code: laps_by_code[code]
        )

    def _tmp_files(self):
        telemetry_dir = os.path.join(self.media_root, "telemetry")
        if not os.path.isdir(telemetry_dir):
            return []
        return os.listdir(telemetry_dir)

    # (a) La clave no depende del orden de los pilotos.
    def test_cache_key_is_order_insensitive(self):
        self.assertEqual(
            build_cache_key(self.session, self.ver, self.col),
            build_cache_key(self.session, self.col, self.ver),
        )

        first_path = get_or_generate_telemetry_plot(self.session, self.ver, self.col)
        second_path = get_or_generate_telemetry_plot(self.session, self.col, self.ver)

        self.assertEqual(first_path, second_path)
        self.assertEqual(TelemetryCache.objects.count(), 1)
        cached = TelemetryCache.objects.get()
        self.assertEqual((cached.driver1, cached.driver2), (self.col, self.ver))
        # Solo se generó una vez: la segunda llamada reutilizó la caché.
        self.assertEqual(self.fastf1_mock.get_session.call_count, 1)

    # (b) La clave incluye el año de la temporada.
    def test_cache_key_includes_season_year(self):
        key_2026 = build_cache_key(self.session, self.ver, self.col)
        self.assertIn("2026", key_2026)

        season_2025 = make_season(2025)
        event_2025 = make_event(season_2025, round_number=1, name="Gran Premio de Prueba")
        session_2025 = make_session(event_2025, name="Race")
        key_2025 = build_cache_key(session_2025, self.ver, self.col)

        self.assertIn("2025", key_2025)
        self.assertNotEqual(key_2025, key_2026)

        path_2026 = get_or_generate_telemetry_plot(self.session, self.ver, self.col)
        path_2025 = get_or_generate_telemetry_plot(session_2025, self.ver, self.col)
        self.assertNotEqual(path_2026, path_2025)
        self.assertIn("2025", path_2025)
        self.assertEqual(TelemetryCache.objects.count(), 2)
        self.assertEqual(
            set(TelemetryCache.objects.values_list("session_id", flat=True)),
            {self.session.pk, session_2025.pk},
        )

    # (c) Un fallo de FastF1 se propaga y no deja fila inválida.
    def test_fastf1_failure_propagates_without_empty_cache_row(self):
        TelemetryCache.objects.create(
            session=self.session,
            driver1=self.col,
            driver2=self.ver,
            file_path="",
        )
        self.fastf1_mock.get_session.side_effect = RuntimeError("fallo de red simulado")

        with self.assertLogs("f1hub.services", level="ERROR"):
            with self.assertRaisesRegex(RuntimeError, "fallo de red simulado"):
                get_or_generate_telemetry_plot(self.session, self.ver, self.col)

        self.assertEqual(TelemetryCache.objects.count(), 0)

    # (d) El PNG queda en la ruta definitiva y no quedan temporales.
    def test_plot_is_written_to_expected_path_without_temp_leftovers(self):
        path = get_or_generate_telemetry_plot(self.session, self.ver, self.col)
        key = build_cache_key(self.session, self.ver, self.col)

        self.assertEqual(path, f"telemetry/tel_{key}.png")
        final_path = os.path.join(self.media_root, path)
        self.assertTrue(os.path.isfile(final_path))
        self.assertGreater(os.path.getsize(final_path), 0)
        self.assertFalse([name for name in self._tmp_files() if name.startswith("tmp_tel_")])

    def test_savefig_failure_cleans_temp_file_and_cache(self):
        with patch("matplotlib.figure.Figure.savefig", side_effect=OSError("disco lleno")):
            with self.assertLogs("f1hub.services", level="ERROR"):
                with self.assertRaisesRegex(OSError, "disco lleno"):
                    get_or_generate_telemetry_plot(self.session, self.ver, self.col)

        self.assertEqual(TelemetryCache.objects.count(), 0)
        self.assertFalse([name for name in self._tmp_files() if name.startswith("tmp_tel_")])

    # Colores: siglas nuevas de 2026 no rompen si fastf1 no las conoce.
    def test_unknown_driver_acronym_uses_fallback_color(self):
        self.fastf1_mock.plotting.driver_color.side_effect = KeyError("ANT")
        self.fastf1_mock.plotting.get_driver_color.side_effect = KeyError("ANT")

        path = get_or_generate_telemetry_plot(self.session, self.ant, self.ver)

        self.assertTrue(os.path.isfile(os.path.join(self.media_root, path)))
        self.assertEqual(TelemetryCache.objects.count(), 1)

    # TTL: una entrada vencida se descarta (archivo incluido) y se regenera.
    def test_expired_cache_is_removed_and_regenerated(self):
        path = get_or_generate_telemetry_plot(self.session, self.ver, self.col)
        absolute = os.path.join(self.media_root, path)
        with open(absolute, "wb") as old_file:
            old_file.write(b"contenido anterior")
        TelemetryCache.objects.filter(file_path=path).update(
            created_at=timezone.now() - timedelta(days=8)
        )

        with patch(
            "f1hub.services._remove_plot_file", wraps=services._remove_plot_file
        ) as remove:
            new_path = get_or_generate_telemetry_plot(self.session, self.ver, self.col)

        self.assertEqual(new_path, path)
        remove.assert_any_call(path)
        self.assertEqual(self.fastf1_mock.get_session.call_count, 2)
        self.assertEqual(TelemetryCache.objects.count(), 1)
        with open(absolute, "rb") as regenerated:
            self.assertNotEqual(regenerated.read(), b"contenido anterior")

    @override_settings(TELEMETRY_CACHE_TTL_DAYS=0)
    def test_zero_ttl_disables_cache_reuse(self):
        get_or_generate_telemetry_plot(self.session, self.ver, self.col)
        get_or_generate_telemetry_plot(self.session, self.ver, self.col)

        self.assertEqual(self.fastf1_mock.get_session.call_count, 2)
        self.assertEqual(TelemetryCache.objects.count(), 1)

    def test_missing_file_is_cleaned_and_regenerated(self):
        path = get_or_generate_telemetry_plot(self.session, self.ver, self.col)
        os.remove(os.path.join(self.media_root, path))

        new_path = get_or_generate_telemetry_plot(self.session, self.ver, self.col)

        self.assertEqual(new_path, path)
        self.assertEqual(self.fastf1_mock.get_session.call_count, 2)
        self.assertEqual(TelemetryCache.objects.count(), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.media_root, new_path)))
