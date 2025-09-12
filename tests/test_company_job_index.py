# test_company_job_index.py:2
from db_helpers import build_company_job_index

def test_company_job_index_normalization():
    idx = build_company_job_index("Acme Corp", "Senior Engineer", "12345")
    assert idx == "acme corp::senior engineer::12345"

def test_company_job_index_empty_fields():
    idx = build_company_job_index("Acme Corp", "", None)
    assert idx == "acme corp::::"