from django.urls import path, include
from . import views
from tracker.admin import custom_admin_site, admin

urlpatterns = [
    path("reingest_admin/", views.reingest_admin, name="reingest_admin"),
    path("", views.dashboard, name="dashboard"),
    path("company/<int:company_id>/", views.company_detail, name="company_detail"),
    path(
        "company/<int:company_id>/delete/", views.delete_company, name="delete_company"
    ),
    path("label_messages/", views.label_messages, name="label_messages"),
    path("metrics/", views.metrics, name="metrics"),
    path("retrain_model/", views.retrain_model, name="retrain_model"),
    path("admin/", custom_admin_site.urls, name="custom_admin"),
    path("django_admin/", admin.site.urls, name="django_admin"),
    path("aliases/manage/", views.manage_aliases, name="manage_aliases"),
    path(
        "aliases/approve_bulk/", views.approve_bulk_aliases, name="approve_bulk_aliases"
    ),
    path("aliases/reject/", views.reject_alias, name="reject_alias"),
    path("label_companies/", views.label_companies, name="label_companies"),
    path("company_threads/", views.company_threads, name="company_threads"),
    path("json_viewer/", views.json_file_viewer, name="json_file_viewer"),
    path(
        "filters/import/", views.import_gmail_filters_view, name="import_gmail_filters"
    ),
    path("settings/", views.configure_settings, name="configure_settings"),
    path("companies/merge/", views.merge_companies, name="merge_companies"),
]
