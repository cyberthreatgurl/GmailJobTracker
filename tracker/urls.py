from django.urls import path, include
from . import views
from tracker.admin import custom_admin_site, admin
urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('company/<int:company_id>/', views.company_detail, name='company_detail'),
    path("label/", views.label_applications, name="label_applications"),
    path("label_messages/", views.label_messages, name="label_messages"),
    path("admin/", custom_admin_site.urls, name="custom_admin"),
    path("django_admin/", admin.site.urls, name="django_admin"),
    path("aliases/manage/", views.manage_aliases, name="manage_aliases"),
    path("aliases/approve_bulk/", views.approve_bulk_aliases, name="approve_bulk_aliases"),
    path("aliases/reject/", views.reject_alias, name="reject_alias"),
]