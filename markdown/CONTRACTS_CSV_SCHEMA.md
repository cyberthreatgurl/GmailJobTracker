# USASpending CSV Import Schema

This document details the expected CSV format for importing defense contracts into **GmailJobTracker**. 

The import functionality (`load_contracts_csv.py`) is designed to handle CSV exports provided by **USASpending.gov**, specifically the **"Prime Award Transactions"** or **"Assistance Prime Award Transactions"** reports.

## Expected Headers (Auto-Detected)

The import script normalizes headers (lowercase, stripped whitespace) and attempts to match several common column names used by USASpending across different report types.

### Required Fields (One of each group required)

1.  **Unique Identifier** (Used as Primary Key)
    *   `contract_award_unique_key`
    *   `prime_award_unique_key`
    *   `generated_unique_award_id`

2.  **Contract ID / PIID**
    *   `award_id_piid`
    *   `piid`

3.  **Recipient Information**
    *   `recipient_name`

### Optional but Recommended Fields

The script will parse these if present to enrich the contract record:

*   **Amount / Value** (First non-empty value used)
    *   `current_total_value_of_award`
    *   `total_obligation`
    *   `total_dollars_obligated`
    *   `federal_action_obligation`

*   **Dates**
    *   `initial_report_date` (Preferred)
    *   `action_date` (Fallback)

*   **Description**
    *   `transaction_description`
    *   `description`
    *   `product_or_service_code_description` (Added as secondary description)

*   **Agency Information**
    *   `awarding_agency_name`
    *   `awarding_sub_agency_name`

*   **Company Data**
    *   `recipient_doing_business_as_name` (DBA)
    *   `recipient_parent_duns`

*   **Executive Compensation** (Officers 1-5)
    *   `highly_compensated_officer_1_name`
    *   `highly_compensated_officer_1_amount`
    *   ... up to `highly_compensated_officer_5_name/amount`

*   **Place of Performance (Work Location)**
    *   `primary_place_of_performance_city_name`
    *   `primary_place_of_performance_state_code`
    *   `primary_place_of_performance_country_name`
    *   `primary_place_of_performance_county_name`

*   **Recipient Location (Company HQ)**
    *   `recipient_city_name`
    *   `recipient_state_code`
    *   `recipient_country_name`

*   **Metadata**
    *   `usaspending_permalink` (Source URL)

## Import Logic Notes

*   **De-Duplication**: Rows are matched by the unique key. If a record with the same ID exists, it is **updated** with the CSV data. New records are **created**.
*   **Company Matching**: 
    1.  Tries exact case-insensitive match on `recipient_name`.
    2.  Tries fuzzy matching (>88% similarity) against existing companies in the database.
*   **Formatting**: Dollar amounts and dates are automatically parsed from standard US formats.
