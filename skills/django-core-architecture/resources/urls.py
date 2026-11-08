"""
Root URL Configuration for Django project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/stable/topics/http/urls/
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthcheck_view(request):
    """
    Lightweight health check endpoint used by Docker, Kubernetes, and orchestrators.
    Verifies that the WSGI/ASGI application process is serving requests.
    """
    return JsonResponse(
        {
            "status": "healthy",
            "environment": getattr(settings, "ENVIRONMENT", "unknown"),
        },
        status=200,
    )


urlpatterns = [
    # Built-in Administrative interface
    path("admin/", admin.site.urls),
    # Container & Infrastructure Health Check Probe
    path("api/health/", healthcheck_view, name="healthcheck"),
    # API namespace root placeholder (domain apps mount here)
    path("api/v1/", include([]), name="api_v1_root"),
]

# Serve media files in local development when DEBUG is active
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
