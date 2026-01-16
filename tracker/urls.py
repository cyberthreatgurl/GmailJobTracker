from django.urls import path

from tracker.admin import admin

from . import views

urlpatterns = [
    path("logs/", views.log_viewer, name="log_viewer"),
    path("reingest_admin/", views.reingest_admin, name="reingest_admin"),
    path("reingest_admin/stream", views.reingest_stream, name="reingest_stream"),
    path("", views.dashboard, name="dashboard"),
    path(
        "company/<int:company_id>/delete/", views.delete_company, name="delete_company"
    ),
    path("label_messages/", views.label_messages, name="label_messages"),
    path("metrics/", views.metrics, name="metrics"),
    path("retrain_model/", views.retrain_model, name="retrain_model"),
    path("manual_entry/", views.manual_entry, name="manual_entry"),
    path("manual_entry/<str:thread_id>/edit/", views.edit_manual_entry, name="edit_manual_entry"),
    path("manual_entry/<str:thread_id>/delete/", views.delete_manual_entry, name="delete_manual_entry"),
    path("manual_entry/bulk_delete/", views.bulk_delete_manual_entries, name="bulk_delete_manual_entries"),
    path("django_admin/", admin.site.urls, name="django_admin"),
    path("aliases/manage/", views.manage_aliases, name="manage_aliases"),
    path(
        "aliases/approve_bulk/", views.approve_bulk_aliases, name="approve_bulk_aliases"
    ),
    path("aliases/reject/", views.reject_alias, name="reject_alias"),
    path("label_companies/", views.label_companies, name="label_companies"),
    path("company_threads/", views.company_threads, name="company_threads"),
    path("json_viewer/", views.json_file_viewer, name="json_file_viewer"),
    path("system-info/", views.system_info, name="system_info"),
    # removed orphaned import_gmail_filters_view URL
    path("settings/", views.configure_settings, name="configure_settings"),
    path("settings/domains/", views.manage_domains, name="manage_domains"),
    path(
        "api/ingestion_status/", views.ingestion_status_api, name="ingestion_status_api"
    ),
    path("companies/merge/", views.merge_companies, name="merge_companies"),
    path(
        "filters/labels_compare/",
        views.gmail_filters_labels_compare,
        name="gmail_filters_labels_compare",
    ),
    path("debug/label_rule/", views.label_rule_debugger, name="label_rule_debugger"),
    path("upload_eml/", views.upload_eml, name="upload_eml"),
    path("job_search_tracker/", views.job_search_tracker, name="job_search_tracker"),
    path("missing_applications/", views.missing_applications, name="missing_applications"),
    path("api/scrape_job_posting/", views.scrape_job_posting, name="scrape_job_posting"),
]
