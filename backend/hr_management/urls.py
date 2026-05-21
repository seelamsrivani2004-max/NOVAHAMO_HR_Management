from django.urls import path, include
from django.http import JsonResponse


def health_view(request):
    return JsonResponse({'status': 'OK', 'message': 'Django HR Management Backend Running'})

urlpatterns = [
    path('api/', include('api.urls')),
    path('health/', health_view),
    path('', health_view),
]
