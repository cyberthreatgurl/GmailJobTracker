from django.urls import reverse
import pytest
from django.utils import timezone
from tracker.models import DefenseContract, Company

@pytest.mark.django_db
def test_link_contract_company_bulk_update(client, django_user_model):
    """
    Test linking a contract also links other unlinked contracts 
    with the same raw company name.
    """
    user = django_user_model.objects.create_user(username='testuser', password='password')
    client.force_login(user)
    
    # Create target Company
    now = timezone.now()
    company = Company.objects.create(name="Acme Corp", first_contact=now, last_contact=now)
    
    # Create 3 contracts with same raw name, UNLINKED
    c1 = DefenseContract.objects.create(company_name_raw="Acme Inc", description="C1", article_date=now, source_url="http://example.com/1") 
    c2 = DefenseContract.objects.create(company_name_raw="Acme Inc", description="C2", article_date=now, source_url="http://example.com/2") 
    c3 = DefenseContract.objects.create(company_name_raw="Acme Inc", description="C3", article_date=now, source_url="http://example.com/3") 
    
    # Create control contracts
    c4 = DefenseContract.objects.create(company_name_raw="Other Inc", description="C4", article_date=now, source_url="http://example.com/4") 
    c5 = DefenseContract.objects.create(company_name_raw="Acme Inc", description="C5", company=company, article_date=now, source_url="http://example.com/5") 

    # Action: Link C1 to company
    url = reverse('link_contract_company', args=[c1.id])
    payload = {'company_id': company.id}
    
    response = client.post(url, payload)
    
    assert response.status_code == 200, f"Response: {response.content}"
    data = response.json()
    assert data['success'] is True
    
    # Verify C1 is linked (Primary update)
    c1.refresh_from_db()
    assert c1.company == company
    
    # Verify C2, C3 are linked (Bulk update)
    c2.refresh_from_db()
    c3.refresh_from_db()
    assert c2.company == company
    assert c3.company == company
    
    # Verify C4 is untouched
    c4.refresh_from_db()
    assert c4.company is None
    
    # Verify C5 is untouched (already linked)
    c5.refresh_from_db()
    assert c5.company == company 
    
    # Check response metadata
    assert data['updated_count'] == 2
    assert set(data['updated_ids']) == {c2.id, c3.id}

@pytest.mark.django_db
def test_unlink_contract(client, django_user_model):
    user = django_user_model.objects.create_user(username='testuser2', password='password')
    client.force_login(user)
    now = timezone.now()
    company = Company.objects.create(name="Acme Corp", first_contact=now, last_contact=now)
    c1 = DefenseContract.objects.create(company_name_raw="Acme Inc", company=company, article_date=now, source_url="http://example.com/unlink")
    
    url = reverse('link_contract_company', args=[c1.id])
    payload = {'company_id': '0'}
    
    response = client.post(url, payload)
    assert response.status_code == 200
    c1.refresh_from_db()
    assert c1.company is None
