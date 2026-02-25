import os
import fastf1
from django.core.management.base import BaseCommand
from django.conf import settings
from f1hub.models import Season, Event, Session
import pandas as pd

class Command(BaseCommand):
    help = 'Download and sync the 2026 F1 schedule using FastF1'

    def handle(self, *args, **options):
        # Configure FastF1 cache
        cache_dir = os.path.join(settings.BASE_DIR, 'fastf1_cache')
        os.makedirs(cache_dir, exist_ok=True)
        fastf1.Cache.enable_cache(cache_dir)

        year = 2026
        
        self.stdout.write(self.style.SUCCESS(f'Fetching schedule for the {year} season...'))
        
        try:
            # Get the schedule for the season
            schedule = fastf1.get_event_schedule(year)
            
            # Create or get the season record
            season, created = Season.objects.get_or_create(
                year=year,
                defaults={'regulations': 'New era of engines and active aerodynamics'}
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created Season {year} record.'))

            # Iterate through the schedule DataFrame
            events_created = 0
            for index, row in schedule.iterrows():
                # FastF1 schedule contains pre-season testing and actual races.
                # Usually testing has EventFormat 'testing'.
                if row['EventFormat'] == 'testing':
                    continue
                
                # Make sure RoundNumber isn't 0 (which might also mean testing)
                if getattr(row, 'RoundNumber', 0) == 0:
                    continue

                event, ev_created = Event.objects.get_or_create(
                    season=season,
                    round_number=row['RoundNumber'],
                    defaults={
                        'name': row['EventName'],
                        'location': row['Location'],
                        'date': row['EventDate'].date()
                    }
                )
                
                if ev_created:
                    events_created += 1

                self.sync_sessions_for_event(event, row)
                
            self.stdout.write(self.style.SUCCESS(f'Successfully synced schedule. Created {events_created} new events.'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to sync schedule: {str(e)}'))

    def sync_sessions_for_event(self, event, row):
        # Maps FastF1 column names to our Session Type choices
        session_mapping = [
            ('Session1', 'Session1DateUTC'),
            ('Session2', 'Session2DateUTC'),
            ('Session3', 'Session3DateUTC'),
            ('Session4', 'Session4DateUTC'),
            ('Session5', 'Session5DateUTC'),
        ]
        
        name_translator = {
            'Practice 1': 'FP1',
            'Practice 2': 'FP2',
            'Practice 3': 'FP3',
            'Qualifying': 'Qualifying',
            'Sprint Shootout': 'Sprint Shootout',
            'Sprint Qualifying': 'Sprint Shootout',
            'Sprint': 'Sprint',
            'Race': 'Race',
        }
        
        for name_col, date_col in session_mapping:
            if hasattr(row, name_col) and hasattr(row, date_col):
                if pd.notna(row[name_col]) and pd.notna(row[date_col]):
                    session_name_raw = row[name_col]
                    session_name = name_translator.get(session_name_raw, session_name_raw)
                    
                    # Convert pandas NaT to None or extract dt
                    session_dt = row[date_col]
                    
                    Session.objects.get_or_create(
                        event=event,
                        name=session_name,
                        defaults={
                            'date_time': session_dt
                        }
                    )
