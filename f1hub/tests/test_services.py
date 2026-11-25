"""Tests del servicio de TIEMPOS POR VUELTA: sin red y con MEDIA_ROOT temporal.

``fetch_lap_comparison`` se mockea: ningún test consulta Ergast/Jolpica ni
F1TV. Se verifican el gráfico, la caché, el TTL y la escritura atómica.
"""

import os
import tempfile
from datetime import timedelta
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")  # backend headless: los tests no abren ventanas
import matplotlib.axes
from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from f1hub import services
from f1hub.models import TelemetryCache
from f1hub.services import (
    TELEMETRY_UNAVAILABLE_MESSAGE,
    TelemetryUnavailable,
    build_cache_key,
    get_or_generate_telemetry_plot,
)

from .helpers import make_driver, make_event, make_season, make_session

# Fila tal como la devuelve el contrato de ergast_service.fetch_lap_comparison.
LAP_ROWS = [
    {"lap": 1, "code1_seconds": 95.2, "code2_seconds": 95.8},
    {"lap": 3, "code1_seconds": 91.7, "code2_seconds": 91.5},
    {"lap": 2, "code1_seconds": 92.1, "code2_seconds": 92.4},
]


class LapTimesServiceTests(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.media_root = self.tmpdir.name
        self.enterContext(self.settings(MEDIA_ROOT=self.media_root))

        self.fetch = self.enterContext(
            patch("f1hub.services.fetch_lap_comparison")
        )
        self.fetch.return_value = [dict(row) for row in LAP_ROWS]

        self.season = make_season(2026)
        self.event = make_event(self.season, round_number=1, name="Gran Premio de Prueba")
        self.session = make_session(self.event, name="Race")

        self.ver = make_driver("VER", "Max Verstappen", "Red Bull", "NED")
        self.col = make_driver("COL", "Franco Colapinto", "Alpine", "ARG")

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
        # Una sola consulta de datos: la segunda llamada reutilizó la caché.
        self.assertEqual(self.fetch.call_count, 1)
        # La pareja canónica fija el orden de code1/code2 en el gráfico.
        self.fetch.assert_called_once_with(2026, 1, "COL", "VER")

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

    # (c) Un fallo de la fuente se convierte en error de dominio sin fila inválida.
    def test_fetch_failure_raises_domain_error_without_empty_cache_row(self):
        TelemetryCache.objects.create(
            session=self.session,
            driver1=self.col,
            driver2=self.ver,
            file_path="",
        )
        self.fetch.side_effect = RuntimeError("detalle tecnico secreto")

        with self.assertLogs("f1hub.services", level="ERROR") as logs:
            with self.assertRaises(TelemetryUnavailable) as error:
                get_or_generate_telemetry_plot(self.session, self.ver, self.col)

        self.assertEqual(str(error.exception), TELEMETRY_UNAVAILABLE_MESSAGE)
        self.assertNotIn("detalle tecnico secreto", str(error.exception))
        self.assertIn("detalle tecnico secreto", "\n".join(logs.output))
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

    # (e) Sin vueltas: error de dominio claro y sin caché.
    def test_empty_lap_times_raise_friendly_domain_error(self):
        self.fetch.return_value = []

        with self.assertLogs("f1hub.services", level="ERROR"):
            with self.assertRaises(TelemetryUnavailable) as error:
                get_or_generate_telemetry_plot(self.session, self.ver, self.col)

        self.assertIn("tiempos por vuelta", str(error.exception).lower())
        self.assertEqual(str(error.exception), TELEMETRY_UNAVAILABLE_MESSAGE)
        self.assertEqual(TelemetryCache.objects.count(), 0)
        self.assertEqual(self._tmp_files(), [])

    def test_rows_without_lap_or_seconds_raise_domain_error(self):
        self.fetch.return_value = [{"lap": 1, "code1_seconds": None}]

        with self.assertRaises(TelemetryUnavailable):
            get_or_generate_telemetry_plot(self.session, self.ver, self.col)

        self.assertEqual(TelemetryCache.objects.count(), 0)

    # (f) Se usa el round_number del evento y el año de su temporada.
    def test_uses_event_round_number_and_season_year(self):
        self.event.round_number = 22
        self.event.save(update_fields=["round_number"])

        get_or_generate_telemetry_plot(self.session, self.ver, self.col)

        self.fetch.assert_called_once_with(2026, 22, "COL", "VER")

    # (g) Eje X = vuelta, eje Y = segundos, dos líneas y título con GP/ronda/pilotos.
    def test_plot_uses_laps_and_seconds_with_descriptive_title(self):
        plotted = []
        titles = []
        real_plot = matplotlib.axes.Axes.plot
        real_set_title = matplotlib.axes.Axes.set_title

        def record_plot(ax, *args, **kwargs):
            plotted.append(args)
            return real_plot(ax, *args, **kwargs)

        def record_title(ax, label, *args, **kwargs):
            titles.append(label)
            return real_set_title(ax, label, *args, **kwargs)

        with patch.object(matplotlib.axes.Axes, "plot", record_plot), patch.object(
            matplotlib.axes.Axes, "set_title", record_title
        ):
            path = get_or_generate_telemetry_plot(self.session, self.ver, self.col)

        self.assertTrue(os.path.isfile(os.path.join(self.media_root, path)))
        self.assertEqual(len(plotted), 2)
        self.assertEqual(list(plotted[0][0]), [1, 2, 3])
        self.assertEqual(list(plotted[0][1]), [95.2, 92.1, 91.7])
        self.assertEqual(list(plotted[1][1]), [95.8, 92.4, 91.5])
        self.assertEqual(len(titles), 1)
        title = titles[0]
        self.assertIn("TIEMPOS POR VUELTA", title)
        self.assertIn("Gran Premio de Prueba", title)
        self.assertIn("R1", title)
        self.assertIn("COL", title)
        self.assertIn("VER", title)

    # Nunca se llama a get_session().load() ni a live timing.
    def test_no_fastf1_session_load_in_this_path(self):
        self.assertFalse(hasattr(services, "fastf1"))
        get_or_generate_telemetry_plot(self.session, self.ver, self.col)
        self.assertEqual(self.fetch.call_count, 1)

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
        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(TelemetryCache.objects.count(), 1)
        with open(absolute, "rb") as regenerated:
            self.assertNotEqual(regenerated.read(), b"contenido anterior")

    @override_settings(TELEMETRY_CACHE_TTL_DAYS=0)
    def test_zero_ttl_disables_cache_reuse(self):
        get_or_generate_telemetry_plot(self.session, self.ver, self.col)
        get_or_generate_telemetry_plot(self.session, self.ver, self.col)

        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(TelemetryCache.objects.count(), 1)

    def test_missing_file_is_cleaned_and_regenerated(self):
        path = get_or_generate_telemetry_plot(self.session, self.ver, self.col)
        os.remove(os.path.join(self.media_root, path))

        new_path = get_or_generate_telemetry_plot(self.session, self.ver, self.col)

        self.assertEqual(new_path, path)
        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(TelemetryCache.objects.count(), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.media_root, new_path)))
