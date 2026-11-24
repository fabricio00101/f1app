from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("drivers/", views.drivers, name="drivers"),
    path("teams/", views.teams, name="teams"),
    path("insights/", views.insights, name="insights"),
    path("telemetry/", views.telemetry, name="telemetry"),
    path("telemetry/status/", views.telemetry_job_status, name="telemetry_job_status"),
]
