from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("drivers/", views.drivers, name="drivers"),
    path("teams/", views.teams, name="teams"),
    path("insights/", views.insights, name="insights"),
]
