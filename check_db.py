import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from f1hub.models import Event
print(f"Total events in DB: {Event.objects.count()}")
