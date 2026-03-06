import csv
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from tracker.models import DefenseContract, Company
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Constants for fuzzy matching
COMPANY_MATCH_THRESHOLD = 88

class Command(BaseCommand):
    help = 'Load contracts from USASpending CSV export'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Path to the CSV file')

    def handle(self, *args, **options):
        csv_file_path = options['csv_file']
        
        self.stdout.write(f"Importing contracts from {csv_file_path}...")
        print(f"DEBUG: Opening file {csv_file_path}")
        
        try:
            with open(csv_file_path, 'r', encoding='utf-8-sig') as f:
                # Read header line first to normalize
                header_line = f.readline()
                fieldnames = [h.strip().lower() for h in next(csv.reader([header_line]))]
                
                reader = csv.DictReader(f, fieldnames=fieldnames)
                
                # Debug headers
                print(f"DEBUG: CSV Headers (normalized): {fieldnames[:5]} ...")
                
                if 'contract_award_unique_key' not in fieldnames:
                    print("DEBUG: WARNING - 'contract_award_unique_key' not found in headers!")     
                    # Try to find a close match
                    candidates = [h for h in fieldnames if 'unique' in h and 'key' in h]
                    print(f"DEBUG: Candidate key columns: {candidates}")

                count = 0
                created_count = 0
                updated_count = 0
                errors = 0
                
                for row in reader:
                    count += 1
                    if count == 1:
                        print(f"DEBUG: First row keys: {list(row.keys())}")
                        print(f"DEBUG: First row sample values: {list(row.values())[:5]}")
                    
                    if count % 100 == 0:
                        print(f"DEBUG: Processing row {count}...")

                    try:
                        c, u = self.process_row(row)
                        created_count += c
                        updated_count += u
                        if c > 0 and created_count <= 5:
                            print(f"DEBUG: Created contract on row {count}")
                    except Exception as e:
                        errors += 1
                        logger.error(f"Error processing row {count}: {e}")
                        self.stdout.write(self.style.ERROR(f"Error on row {count}: {e}"))
                
                msg = f"Processed {count} rows. Created: {created_count}, Updated: {updated_count}, Errors: {errors}"
                self.stdout.write(self.style.SUCCESS(msg))
                print(f"DEBUG: {msg}")
        
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f"File not found: {csv_file_path}"))
            print(f"DEBUG: File not found: {csv_file_path}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Critical error: {e}"))
            print(f"DEBUG: Critical error: {e}")

    def process_row(self, row):
        # 1. Extract basic fields. Use dictionary access carefully to avoid KeyErrors but log missing critical fields.
        generated_unique_award_id = (row.get('contract_award_unique_key') or 
                                     row.get('prime_award_unique_key') or 
                                     row.get('generated_unique_award_id') or '').strip()
        piid = (row.get('award_id_piid') or row.get('piid') or '').strip()
        
        # Determine award_id
        award_id = generated_unique_award_id or piid
        
        if not award_id:
            logger.warning(f"Skipping row with no award_id or unique key.")
            if count <= 20: # Only print first few skips to avoid spam
                print(f"DEBUG: Skipping row - no ID found. Keys present: {list(row.keys())[:5]}...")
            return 0, 0

        # 2. Parse amounts

        # 2. Parse amounts
        # USASpending CSVs use 'total_dollars_obligated' sometimes, check for aliases
        amount_raw = (row.get('current_total_value_of_award') or 
                     row.get('total_obligation') or 
                     row.get('total_dollars_obligated') or
                     row.get('federal_action_obligation'))
        
        amount = self.parse_decimal(amount_raw)
        
        # 3. Parse dates
        report_date_str = (row.get('initial_report_date') or '').strip()
        action_date_str = (row.get('action_date') or '').strip()
        action_date_str = row.get('action_date', '').strip()
        
        article_date = None
        if report_date_str:
            article_date = self.parse_date(report_date_str)
        if not article_date and action_date_str:
            article_date = self.parse_date(action_date_str)
        
        if not article_date:
            article_date = timezone.now().date()

        # 4. Company Matching
        recipient_name = row.get('recipient_name', '').strip()
        company = self.match_company(recipient_name)
        
        # 5. Officer Parsing
        off1_name = row.get('highly_compensated_officer_1_name', '')
        off1_amt = self.parse_decimal(row.get('highly_compensated_officer_1_amount'))
        off2_name = row.get('highly_compensated_officer_2_name', '')
        off2_amt = self.parse_decimal(row.get('highly_compensated_officer_2_amount'))
        off3_name = row.get('highly_compensated_officer_3_name', '')
        off3_amt = self.parse_decimal(row.get('highly_compensated_officer_3_amount'))
        off4_name = row.get('highly_compensated_officer_4_name', '')
        off4_amt = self.parse_decimal(row.get('highly_compensated_officer_4_amount'))
        off5_name = row.get('highly_compensated_officer_5_name', '')
        off5_amt = self.parse_decimal(row.get('highly_compensated_officer_5_amount'))

        # 6. Description & Metadata
        description = row.get('transaction_description', '') or row.get('description', '')
        
        # New fields requested
        product_service_desc = row.get('product_or_service_code_description', '')
        recipient_dba = row.get('recipient_doing_business_as_name', '')
        recipient_parent_duns = row.get('recipient_parent_duns', '')
        
        # Map location fields
        # Note: CSV fields: primary_place_of_performance_city_name, ..._state_code, ..._country_code
        pop_city = row.get('primary_place_of_performance_city_name', '')
        pop_state = row.get('primary_place_of_performance_state_code', '')
        pop_country = row.get('primary_place_of_performance_country_name', '')
        pop_county = row.get('primary_place_of_performance_county_name', '')

        work_location = self.format_location(pop_city, pop_state, pop_country)

        company_location = self.format_location(
            row.get('recipient_city_name', ''), 
            row.get('recipient_state_code', ''),
            row.get('recipient_country_name', '')
        )

        source_url = row.get('usaspending_permalink', '')
        
        # Update or Create
        contract, created = DefenseContract.objects.update_or_create(
            data_source='usaspending',
            award_id=award_id,
            defaults={
                'generated_internal_id': generated_unique_award_id,
                'contract_number': piid,
                'company_name_raw': recipient_name,
                'company': company,
                'amount': amount,
                'article_date': article_date,
                'description': description,
                'product_or_service_description': product_service_desc,
                
                # Agency info
                'awarding_agency': row.get('awarding_agency_name', ''),
                'awarding_sub_agency': row.get('awarding_sub_agency_name', ''),
                
                # New Metadata
                'recipient_doing_business_as_name': recipient_dba,
                'recipient_parent_duns': recipient_parent_duns,
                
                # Officers
                'highly_compensated_officer_1_name': off1_name,
                'highly_compensated_officer_1_amount': off1_amt,
                'highly_compensated_officer_2_name': off2_name,
                'highly_compensated_officer_2_amount': off2_amt,
                'highly_compensated_officer_3_name': off3_name,
                'highly_compensated_officer_3_amount': off3_amt,
                'highly_compensated_officer_4_name': off4_name,
                'highly_compensated_officer_4_amount': off4_amt,
                'highly_compensated_officer_5_name': off5_name,
                'highly_compensated_officer_5_amount': off5_amt,

                # Location
                'primary_place_of_performance_city_name': pop_city,
                'primary_place_of_performance_county_name': pop_county,
                'primary_place_of_performance_country_name': pop_country,
                'place_of_performance_state': pop_state,
                'work_location': work_location,
                'company_location': company_location,
                
                'source_url': source_url,
                'usaspending_published': True
            }
        )
        
        return (1, 0) if created else (0, 1)

    def parse_decimal(self, value):
        if not value:
            return None
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return None

    def parse_date(self, date_str):
        if not date_str:
            return None
        # Handle formats like '2025-10-15 11:50:06+00' or '2025-10-15'
        try:
            # Try ISO format/date-time
            if ' ' in date_str:
                return datetime.strptime(date_str.split(' ')[0], "%Y-%m-%d").date()
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None

    def format_location(self, city, state, country):
        parts = []
        if city: parts.append(city)
        if state: parts.append(state)
        
        loc = ", ".join(parts)
        if country and country.upper() not in ['USA', 'UNITED STATES']:
            if loc:
                loc += f", {country}"
            else:
                loc = country
        return loc

    def match_company(self, recipient_name):
        if not recipient_name:
            return None

        # Strategy 1: Exact match (case-insensitive)
        exact_match = Company.objects.filter(name__iexact=recipient_name).first()
        if exact_match:
            return exact_match

        # Strategy 2: Fuzzy matching
        # Limit search to companies with similar first letter for performance
        first_char = recipient_name[0].upper()
        candidates = Company.objects.filter(name__istartswith=first_char)

        best_match = None
        best_score = 0

        for company in candidates:
            score = fuzz.ratio(recipient_name.lower(), company.name.lower())
            if score > best_score:
                best_score = score
                best_match = company

        if best_score >= COMPANY_MATCH_THRESHOLD:
            return best_match

        return None
