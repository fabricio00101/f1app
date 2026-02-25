import os
import fastf1
from django.core.management.base import BaseCommand
from django.conf import settings
from f1hub.models import Driver

class Command(BaseCommand):
    help = 'Download and sync F1 drivers using FastF1'

    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=int,
            default=2025,
            help='Year to fetch drivers from (def: 2025 until 2026 starts)',
        )
        parser.add_argument(
            '--round',
            type=str,
            default='last',
            help='Round number or name to fetch from (def: last round of the year)',
        )

    def handle(self, *args, **options):
        cache_dir = os.path.join(settings.BASE_DIR, 'fastf1_cache')
        os.makedirs(cache_dir, exist_ok=True)
        fastf1.Cache.enable_cache(cache_dir)
        
        year = options['year']
        round_val = options['round']
        
        if round_val.isdigit():
            round_val = int(round_val)
        elif round_val == 'last':
            # FastF1 schedule can give us the last round
            schedule = fastf1.get_event_schedule(year)
            schedule = schedule[schedule['EventFormat'] != 'testing']
            if schedule.empty:
                self.stdout.write(self.style.ERROR(f'No events found for {year}'))
                return
            round_val = schedule.iloc[-1]['RoundNumber']
        
        self.stdout.write(self.style.SUCCESS(f'Fetching drivers for {year} round {round_val}...'))
        
        try:
            session = fastf1.get_session(year, round_val, 'R')
            # Load only what we need to avoid long downloads
            session.load(telemetry=False, laps=False, weather=False)
            
            drivers_synced = 0
            for drv_num in session.drivers:
                info = session.get_driver(drv_num)
                
                name = info.get('FullName', 'Unknown')
                acronym = info.get('Abbreviation', str(drv_num))
                team = info.get('TeamName', 'Unknown')
                nationality = info.get('CountryCode', 'Unknown')
                
                driver, created = Driver.objects.update_or_create(
                    acronym=acronym,
                    defaults={
                        'name': name,
                        'team': team,
                        'nationality': nationality
                    }
                )
                if created:
                    self.stdout.write(f"Created driver: {name} ({acronym})")
                drivers_synced += 1
                
            self.stdout.write(self.style.SUCCESS(f'Successfully synced {drivers_synced} drivers.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to sync drivers: {e}'))
