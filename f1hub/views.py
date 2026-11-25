import logging
import os
from urllib.parse import urljoin

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from .context_processors import season_year, standings_context
from .jobs import TELEMETRY_USER_ERROR, get_job, start_job
from .models import Driver, Session
from .services import get_cached_telemetry_plot

logger = logging.getLogger(__name__)


def dashboard(request):
    # Find Colapinto data
    colapinto = Driver.objects.filter(acronym="COL").first()

    # Equipos derivados de los pilotos: se mantiene como estado vacío cuando
    # todavía no hay standings persistidos (los traerá ``sync_standings``).
    constructors = [
        {"name": row["team"]}
        for row in Driver.objects.exclude(team="")
        .values("team")
        .distinct()
        .order_by("team")
    ]

    # La clasificación real (driver_standings / constructor_standings) la
    # inyecta race_context desde la BD. Acá solo resolvemos la fila del piloto
    # destacado para no buscarla dentro de la plantilla.
    colapinto_standing = None
    if colapinto:
        colapinto_standing = next(
            (
                row
                for row in standings_context(season_year())["driver_standings"]
                if row.driver_code == colapinto.acronym
            ),
            None,
        )

    # next_event, calendar_events y today los aporta race_context (context
    # processor), para que el layout use los mismos datos en todas las vistas.
    context = {
        "colapinto": colapinto,
        "colapinto_standing": colapinto_standing,
        "constructors": constructors,
    }

    return render(request, "f1hub/dashboard.html", context)


def drivers(request):
    drivers_list = Driver.objects.all().order_by("name")
    return render(request, "f1hub/drivers.html", {"drivers_list": drivers_list})


def teams(request):
    # Una sola consulta para todos los equipos: traemos solo los campos reales
    # de los pilotos y agrupamos en Python. Así evitamos N+1 y agregados
    # específicos de backend (StringAgg/ArrayAgg) que no funcionan en SQLite.
    teams_by_name = {}
    rows = (
        Driver.objects.values("team", "acronym", "nationality")
        .order_by("team", "acronym")
    )
    for row in rows:
        team = teams_by_name.setdefault(
            row["team"],
            {"team": row["team"], "driver_count": 0, "drivers": []},
        )
        team["driver_count"] += 1
        team["drivers"].append(
            {"acronym": row["acronym"], "nationality": row["nationality"]}
        )

    teams_list = list(teams_by_name.values())
    return render(request, "f1hub/teams.html", {"teams_list": teams_list})


def insights(request):
    return render(request, "f1hub/insights.html")


def _source_label(session):
    """Etiqueta legible de la fuente del gráfico: evento, sesión y fecha local."""
    when = timezone.localtime(session.date_time).strftime("%d/%m/%Y")
    return f"{session.event.name} – {session.name} – {when}"


def _media_url(plot_path):
    """Convierte la ruta devuelta por el servicio en una URL bajo MEDIA_URL."""
    if not plot_path:
        return ""

    plot_path = str(plot_path)
    if os.path.isabs(plot_path):
        plot_path = os.path.relpath(plot_path, str(settings.MEDIA_ROOT))
    plot_path = plot_path.replace("\\", "/").lstrip("/")

    base = str(settings.MEDIA_URL)
    # MEDIA_URL del proyecto es relativa ("media/"); sin la barra inicial el
    # navegador la resolvería contra la URL de esta vista.
    if not base.startswith(("http://", "https://", "/")):
        base = "/" + base
    if not base.endswith("/"):
        base += "/"

    # El servicio puede devolver ya la URL con el prefijo de media incluido.
    prefix = base.rstrip("/").rsplit("/", 1)[-1] + "/"
    if plot_path.startswith(prefix):
        plot_path = plot_path[len(prefix):]

    return urljoin(base, plot_path)


def _session_limit():
    """Cantidad máxima de sesiones del selector (configurable, default 50)."""
    try:
        limit = int(getattr(settings, "TELEMETRY_SESSION_LIMIT", 50))
    except (TypeError, ValueError):
        limit = 50
    return limit if limit > 0 else 50


def _default_driver_pair(drivers_list):
    """Devuelve los dos líderes de la clasificación persistida.

    La vista usa los dos primeros ``DriverStanding`` por ``position`` de la
    temporada activa (hoy ANT y VER), porque suelen ser los que tienen vueltas
    compartidas en Ergast. Solo se aceptan códigos presentes en la tabla
    ``Driver``; si no hay dos, se completa con el orden alfabético de siempre.
    """
    by_code = {driver.acronym: driver for driver in drivers_list}
    chosen = []
    for row in standings_context(season_year())["driver_standings"]:
        driver = by_code.get(getattr(row, "driver_code", ""))
        if driver is not None and driver not in chosen:
            chosen.append(driver)
            if len(chosen) == 2:
                return chosen[0], chosen[1]
    for driver in drivers_list:
        if driver not in chosen:
            chosen.append(driver)
            if len(chosen) == 2:
                break
    if len(chosen) == 2:
        return chosen[0], chosen[1]
    return (chosen[0], chosen[0]) if chosen else (None, None)


def _driver_season_error(d1, d2, session):
    """Rechaza pilotos asignados explícitamente a otra temporada.

    Los pilotos sin temporada asignada (filas antiguas) se permiten para no
    dejar fuera a datos legacy; ``sync_drivers`` siempre guarda el año.
    """
    season = session.event.season
    for driver in (d1, d2):
        if driver.season_id and driver.season_id != season.pk:
            return (
                f"El piloto {driver.name} ({driver.acronym}) no pertenece a la "
                f"temporada {season.year} de la sesión seleccionada."
            )
    return ""


def telemetry(request):
    """Compara tiempos por vuelta reales de dos pilotos en una sesión de la BD.

    Si ya hay un PNG válido en caché se sirve en el mismo request; si no, se
    lanza un trabajo en segundo plano y la plantilla sondea su estado. El
    servicio obtiene las vueltas desde ``fetch_lap_comparison`` (FastF1/Ergast),
    sin F1TV ni live timing, y nunca bloquea la respuesta.
    """
    drivers_list = list(Driver.objects.all().order_by("name"))
    limit = _session_limit()
    now = timezone.now()
    # Igual que ``sync_drivers``: FastF1 solo tiene datos de sesiones ya
    # disputadas. Filtrar por fecha aquí evita que el default (y el selector)
    # apunte a una carrera futura y que el worker pierda tiempo en un 404.
    sessions_list = list(
        Session.objects.select_related("event")
        .filter(event__season__year=season_year(), date_time__lte=now)
        .order_by("-date_time")[:limit]
    )
    sessions_criterion = (
        f"Últimas {len(sessions_list)} sesiones de la temporada "
        f"{season_year()} ya disputadas (más recientes primero)."
    )
    # Por defecto, la última carrera ya disputada. Si todavía no hubo ninguna,
    # se muestra un estado vacío en vez de intentar generar telemetría.
    default_session = next(
        (session for session in sessions_list if session.name == "Race"), None
    )

    requested_d1 = request.GET.get("d1")
    requested_d2 = request.GET.get("d2")
    if requested_d1 and requested_d2:
        d1 = Driver.objects.filter(acronym=requested_d1).first()
        d2 = Driver.objects.filter(acronym=requested_d2).first()
    else:
        d1, d2 = _default_driver_pair(drivers_list)

    session_id = request.GET.get("session")
    selected_session = default_session
    if session_id:
        # Comparar como texto evita ValueError con pk no numérico.
        selected_session = next(
            (s for s in sessions_list if str(s.pk) == session_id), None
        )

    error = ""
    plot_url = ""
    source_label = ""
    job_key = ""

    if not drivers_list or not sessions_list:
        error = "No hay pilotos ni sesiones disponibles para comparar telemetría."
    elif session_id and selected_session is None:
        error = (
            "La sesión seleccionada no existe. Solo se pueden comparar "
            "sesiones ya disputadas."
        )
    elif selected_session is None:
        error = (
            f"Todavía no hay carreras disputadas en la temporada {season_year()} "
            "para comparar tiempos por vuelta. Probá después de la próxima carrera."
        )
    elif d1 is None or d2 is None:
        error = "Los pilotos seleccionados no existen."
    else:
        error = _driver_season_error(d1, d2, selected_session)
        if not error:
            source_label = _source_label(selected_session)
            try:
                cached_path = get_cached_telemetry_plot(selected_session, d1, d2)
            except Exception:
                # El detalle técnico va al log; al usuario solo un mensaje claro.
                logger.exception(
                    "No se pudo consultar la caché de telemetría para %s/%s en la sesión %s",
                    d1.acronym, d2.acronym, selected_session.pk,
                )
                error = TELEMETRY_USER_ERROR
            else:
                if cached_path:
                    plot_url = _media_url(cached_path)
                else:
                    job_key = start_job(selected_session, d1, d2).key

    context = {
        "drivers_list": drivers_list,
        "sessions_list": sessions_list,
        "sessions_criterion": sessions_criterion,
        "season_year": season_year(),
        "d1": d1,
        "d2": d2,
        "selected_session": selected_session,
        "plot_url": plot_url,
        "source_label": source_label,
        "error": error,
        "job_key": job_key,
    }
    return render(request, "f1hub/telemetry.html", context)


def telemetry_job_status(request):
    """Estado JSON del trabajo en segundo plano (sondeo desde la UI)."""
    job = get_job(request.GET.get("key", ""))
    if job is None:
        return JsonResponse(
            {
                "status": "unknown",
                "plot_url": "",
                "error": TELEMETRY_USER_ERROR,
            },
            status=404,
        )

    return JsonResponse(
        {
            "status": job.status,
            "plot_url": _media_url(job.plot_path),
            "error": job.error,
        }
    )
