from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("nuevo/", views.new_match, name="new_match"),
    path("partido/<slug:code>/modo/", views.choose_mode, name="choose_mode"),
    path("ver/<slug:code>/", views.viewer, name="viewer"),
    path("control/<slug:code>/", views.control, name="control"),

    # Overlay para transmisiones (Larix / Instagram Live)
    path("overlay/<slug:code>/", views.overlay_page, name="overlay"),
    path("overlay/<slug:code>/preview/", views.overlay_preview, name="overlay_preview"),
    path("overlay/<slug:code>/<slug:category>/", views.overlay_page, name="overlay_cat"),
    path("overlay/<slug:code>/<slug:category>/preview/", views.overlay_preview, name="overlay_cat_preview"),

    # API endpoints
    path("api/<slug:code>/update/", views.update_scores, name="update_scores"),
    path("api/<slug:code>/state/", views.get_state, name="get_state"),
    path("api/<slug:code>/live/", views.live_state, name="live_state"),

    path("api/upload-sponsor/", views.upload_sponsor, name="upload_sponsor"),

]
