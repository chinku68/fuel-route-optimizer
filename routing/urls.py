from django.urls import path

from .views import (
    health_check,
    fuel_stations,
    route_preview,
)


urlpatterns = [
    path(
        "health/",
        health_check,
        name="health-check"
    ),

    path(
        "stations/",
        fuel_stations,
        name="fuel-stations"
    ),

    path(
        "route/",
        route_preview,
        name="route-preview"
    ),
]