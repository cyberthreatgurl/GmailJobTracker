from django.urls import path, include
from . import views
from tracker.admin import custom_admin_site

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('company/<int:company_id>/', views.company_detail, name='company_detail'),
    path("label/", views.label_applications, name="label_applications"),
    path("admin/",custom_admin_site.urls), 
]