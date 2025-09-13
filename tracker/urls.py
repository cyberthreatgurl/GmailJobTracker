from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('company/<int:company_id>/', views.company_detail, name='company_detail'),
]
