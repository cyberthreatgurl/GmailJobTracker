from django.urls import path, re_path

from tracker.admin import admin

from . import views

urlpatterns = [
    path("logs/", views.log_viewer, name="log_viewer"),
    path("reingest_admin/", views.reingest_admin, name="reingest_admin"),
    path("reingest_admin/stream", views.reingest_stream, name="reingest_stream"),
    re_path(r"^(?:rss|feed)(?:\.xml|/.*)?$", views.rss_stub, name="rss_stub"),
    re_path(r"^blog/(?:rss|feed)(?:\.xml|/)?$", views.rss_stub, name="blog_rss_stub"),
    re_path(r"^articles/feed/?$", views.rss_stub, name="articles_feed_stub"),
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
    path("api/company/<int:company_id>/job_titles/", views.get_company_job_titles, name="get_company_job_titles"),
    path("django_admin/", admin.site.urls, name="django_admin"),
    path("aliases/manage/", views.manage_aliases, name="manage_aliases"),
    path(
        "aliases/approve_bulk/", views.approve_bulk_aliases, name="approve_bulk_aliases"
    ),
    path("aliases/reject/", views.reject_alias, name="reject_alias"),
    path("label_companies/", views.label_companies, name="label_companies"),
    path("companies_in_city/", views.companies_in_city, name="companies_in_city"),
    path("company_threads/", views.company_threads, name="company_threads"),
    path("json_viewer/", views.json_file_viewer, name="json_file_viewer"),
    path("system-info/", views.system_info, name="system_info"),
    # removed orphaned import_gmail_filters_view URL
    path("settings/", views.configure_settings, name="configure_settings"),
    path("settings/domains/", views.manage_domains, name="manage_domains"),
    path(
        "api/ingestion_status/", views.ingestion_status_api, name="ingestion_status_api"
    ),
    path("api/company_search/", views.company_search_api, name="company_search_api"),
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
    path("company/<int:company_id>/upload_document/", views.upload_company_document, name="upload_company_document"),
    path("company/document/<int:document_id>/delete/", views.delete_company_document, name="delete_company_document"),
    path("company/<int:company_id>/news/", views.get_company_news, name="get_company_news"),
    path("company/<int:company_id>/refresh_news/", views.refresh_company_news, name="refresh_company_news"),
    path("company/<int:company_id>/news/add_url/", views.add_company_news_url, name="add_company_news_url"),
    path("company/<int:company_id>/news/remove_article/", views.remove_company_news_article, name="remove_company_news_article"),
    path("company/<int:company_id>/interactions/add/", views.add_company_interaction, name="add_company_interaction"),
    path("company/<int:company_id>/interactions/<int:interaction_id>/delete/", views.delete_company_interaction, name="delete_company_interaction"),
    path("company/<int:company_id>/refresh_contracts/", views.refresh_company_contracts, name="refresh_company_contracts"),
    path("defense_contracts/", views.defense_contracts, name="defense_contracts"),
    path("opportunities/", views.opportunities_dashboard, name="opportunities_dashboard"),
    path("opportunities/refresh/<int:opportunity_id>/", views.refresh_opportunity, name="refresh_opportunity"),
    path("opportunities/refresh-json/<int:opportunity_id>/", views.refresh_opportunity_json, name="refresh_opportunity_json"),
    path("opportunities/debug/<int:opportunity_id>/", views.get_opportunity_debug, name="get_opportunity_debug"),
    path("defense_contracts/upload_csv/", views.upload_contracts_csv, name="upload_contracts_csv"),
    path("defense_contracts/upload_json/", views.upload_contract_json, name="upload_contract_json"),
    path("defense_contracts/create_company/", views.create_company_popup, name="create_company_popup"),
    path("defense_contracts/<int:contract_id>/link_company/", views.link_contract_company, name="link_contract_company"),
    path("defense_contracts/<int:contract_id>/refresh/", views.refresh_usaspending_award, name="refresh_usaspending_award"),
    path("api/fetch_contracts/", views.fetch_contracts_ajax, name="fetch_contracts_ajax"),
    path("api/add_ignore_rule/", views.add_contract_ignore_rule, name="add_contract_ignore_rule"),
    path("api/update_naics_description/", views.update_naics_description, name="update_naics_description"),
    path("api/companies/search/", views.search_companies_for_linking, name="search_companies_for_linking"),
    path("api/upload_contract_json/", views.upload_contract_json, name="upload_contract_json"),
    path("news/", views.rss_dashboard, name="rss_dashboard"),
    path("news/fetch/", views.fetch_feeds_ajax, name="rss_fetch_ajax"),
    path("news/add/", views.add_feed, name="rss_add_feed"),
    path("news/delete/", views.delete_feed, name="rss_delete_feed"),
    path("news/link/<int:article_id>/", views.link_article_to_company, name="rss_link_article"),
]
