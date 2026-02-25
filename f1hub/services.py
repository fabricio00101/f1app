import os
import fastf1
import fastf1.plotting
import matplotlib.pyplot as plt
from django.conf import settings
from .models import TelemetryCache

def get_or_generate_telemetry_plot(session_obj, driver1, driver2):
    """
    Generates a telemetry speed comparison plot for two drivers' fastest laps in a session.
    If already cached, returns the path to the cached image.
    """
    
    # Check cache first
    cache, created = TelemetryCache.objects.get_or_create(
        session=session_obj,
        driver1=driver1,
        driver2=driver2,
        defaults={'file_path': ''}
    )
    
    media_dir = os.path.join(settings.MEDIA_ROOT, 'telemetry')
    os.makedirs(media_dir, exist_ok=True)
    
    filename = f"tel_{session_obj.id}_{driver1.acronym}_{driver2.acronym}.png"
    filepath = os.path.join(media_dir, filename)
    rel_path = f"telemetry/{filename}"
    
    if not created and cache.file_path and os.path.exists(filepath):
        return cache.file_path

    # Setup fastf1 cache
    cache_dir = os.path.join(settings.BASE_DIR, 'fastf1_cache')
    fastf1.Cache.enable_cache(cache_dir)
    fastf1.plotting.setup_mpl(misc_mpl_mods=False)
    
    # We might need mapping based on FastF1 event format vs our names
    session_mapping = {
        'FP1': 'FP1', 'FP2': 'FP2', 'FP3': 'FP3',
        'Qualifying': 'Q', 'Sprint Shootout': 'SQ',
        'Sprint': 'S', 'Race': 'R'
    }
    f1_sess_identifier = session_mapping.get(session_obj.name, session_obj.name)

    # Load session
    f1_session = fastf1.get_session(
        session_obj.event.season.year, 
        session_obj.event.round_number, 
        f1_sess_identifier
    )
    f1_session.load(telemetry=True, laps=True, weather=False)

    laps_d1 = f1_session.laps.pick_driver(driver1.acronym)
    laps_d2 = f1_session.laps.pick_driver(driver2.acronym)

    if laps_d1.empty or laps_d2.empty:
        raise ValueError("Laps not found for one or both drivers in this session.")

    fastest_d1 = laps_d1.pick_fastest()
    fastest_d2 = laps_d2.pick_fastest()

    tel_d1 = fastest_d1.get_telemetry().add_distance()
    tel_d2 = fastest_d2.get_telemetry().add_distance()

    # Plot
    fig, ax = plt.subplots(figsize=(10, 5))
    
    # Fastf1 plotting driver color based on team/driver
    color_d1 = fastf1.plotting.driver_color(driver1.acronym)
    color_d2 = fastf1.plotting.driver_color(driver2.acronym)

    ax.plot(tel_d1['Distance'], tel_d1['Speed'], color=color_d1, label=f"{driver1.acronym}")
    ax.plot(tel_d2['Distance'], tel_d2['Speed'], color=color_d2, label=f"{driver2.acronym}")
    
    ax.set_xlabel('Distance in m')
    ax.set_ylabel('Speed in km/h')
    ax.legend()
    ax.set_title(f"Fastest Lap Telemetry: {driver1.acronym} vs {driver2.acronym}\n{session_obj.event.name} {session_obj.event.season.year}")

    plt.tight_layout()
    plt.savefig(filepath)
    plt.close(fig)

    # Update cache record
    cache.file_path = rel_path
    cache.save()

    return rel_path
