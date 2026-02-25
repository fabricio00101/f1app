import os
import django

# Setup django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from f1hub.models import Session, Driver, Event, Season
from f1hub.services import get_or_generate_telemetry_plot

def test():
    # Find a 2025 event that has a race session
    season = Season.objects.filter(year=2025).first()
    if not season:
        print("No 2025 season found.")
        return
        
    event = Event.objects.filter(season=season).order_by('round_number').last()
    if not event:
        print("No events found for 2025")
        return
        
    session = Session.objects.filter(event=event, name='Race').first()
    if not session:
        # Create a dummy session if it doesn't exist
        print(f"No race session found for event {event.name}. Continuing with 2025 test.")
        # But for test to work we need an existing fastf1 round
        # fastf1 will fetch the actual data matching the identifier
        session_obj, _ = Session.objects.get_or_create(
            event=event,
            name='Race',
            defaults={"date_time": event.date}
        )
        session = session_obj

    print(f"Testing telemetry for: {event.name} - {session.name}")
    
    driver1 = Driver.objects.filter(acronym='VER').first()
    driver2 = Driver.objects.filter(acronym='NOR').first()
    
    if not driver1 or not driver2:
        print("Max or Lando drivers not found")
        return
        
    try:
        path = get_or_generate_telemetry_plot(session, driver1, driver2)
        print(f"Telemetry plot successfully generated at: {path}")
    except Exception as e:
        print(f"Error generating telemetry: {e}")

if __name__ == '__main__':
    test()
