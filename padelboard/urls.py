from django.conf import settings

from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('scoreboard.urls')),
]

# Servir /media/ (sponsors subidos) también con DEBUG=False (ej. en Render)
urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
