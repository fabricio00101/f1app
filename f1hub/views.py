from django.shortcuts import render
from django.utils import timezone
from .models import Event, Driver
import datetime


def dashboard(request):
    today = timezone.localdate()

    # Try finding next event
    next_event = Event.objects.filter(date__gte=today).order_by("date").first()
    # Default to first race if none (since season hasn't started or we are running tests)
    if not next_event:
        next_event = Event.objects.filter(season__year=2026).first()

    # Find Colapinto data
    colapinto = Driver.objects.filter(acronym="COL").first()

    # Calendar
    calendar_events = Event.objects.filter(season__year=2026).order_by("date")

    # Mocking Constructors Championship for 2026 since we don't track points yet
    constructors = [
        {"position": 1, "name": "Ferrari", "points": 214, "color": "#ff2800"},
        {"position": 2, "name": "McLaren", "points": 185, "color": "#ff8000"},
        {"position": 3, "name": "Red Bull Racing", "points": 142, "color": "#001a4d"},
        {
            "position": 4,
            "name": "Cadillac F1",
            "points": 89,
            "color": "#f2f2f2",
            "new_team": True,
        },
        {
            "position": 5,
            "name": "Audi Sport",
            "points": 76,
            "color": "#cc0000",
            "new_team": True,
        },
        {"position": 6, "name": "Mercedes", "points": 65, "color": "#00d2be"},
        {"position": 7, "name": "Aston Martin", "points": 45, "color": "#00665e"},
        {"position": 8, "name": "Alpine", "points": 28, "color": "#0090ff"},
        {"position": 9, "name": "Racing Bulls", "points": 12, "color": "#0029b9"},
        {"position": 10, "name": "Williams", "points": 8, "color": "#005aff"},
        {"position": 11, "name": "Haas", "points": 0, "color": "#ffffff"},
    ]

    context = {
        "next_event": next_event,
        "colapinto": colapinto,
        "calendar_events": calendar_events,
        "constructors": constructors,
        "today": today,
    }

    return render(request, "f1hub/dashboard.html", context)


def drivers(request):
    drivers_list = Driver.objects.all().order_by("name")
    return render(request, "f1hub/drivers.html", {"drivers_list": drivers_list})


def teams(request):
    # Distinct teams
    teams_list = Driver.objects.values("team").distinct()
    return render(request, "f1hub/teams.html", {"teams_list": teams_list})


def insights(request):
    return render(request, "f1hub/insights.html")
