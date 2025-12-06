import json
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


def scrape_and_update(json_file_path):
    """
    Reads URLs from a JSON file, scrapes company names and domains,
    and updates the JSON file with the new data.
    """
    # --- 1. Read the existing JSON data ---
    try:
        with open(json_file_path, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: The file '{json_file_path}' was not found.")
        return
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from the file '{json_file_path}'.")
        return

    urls_to_scrape = data.get('urls', [])
    if not urls_to_scrape:
        print("No URLs found in the JSON file to scrape.")
        return
        
    # --- 2. Scrape each URL ---
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'     
    }

    for url in urls_to_scrape:
        print(f"Scraping URL: {url}...")
        try:
            response = requests.get(url, headers=headers, timeout=10)
            # Raise an exception for bad status codes (4xx or 5xx)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"  Could not fetch URL {url}. Error: {e}")
            continue

        soup = BeautifulSoup(response.content, 'lxml')

        # --- 3. Extract data (This part is specific to the URL's HTML structure) ---
        # For the example CRN URL, companies are in <h2> tags and links are in
        # the following <p> tag. This logic may need to be adjusted for other sites.
        
        company_headings = soup.select('div#content-main h2')
        
        for heading in company_headings:
            try:
                company_name = heading.get_text(strip=True)
                
                # Find the link in the paragraph that follows the heading
                paragraph = heading.find_next_sibling('p')
                if paragraph and paragraph.find('a'):
                    link = paragraph.find('a')['href']
                    
                    # Parse the domain from the link
                    domain = urlparse(link).netloc
                    # Clean up the domain (e.g., remove 'www.')
                    if domain.startswith('www.'):
                        domain = domain[4:]

                    if domain and company_name:
                        print(f"  Found: {company_name} -> {domain}")
                        # Add the new data to our dictionary
                        data['domains_to_companies'][domain] = company_name

            except (AttributeError, TypeError, KeyError) as e:
                # This handles cases where the expected HTML structure is not found
                print(f"  Skipping an entry due to a parsing error: {e}")
                continue

    # --- 4. Write the updated data back to the JSON file ---
    try:
        with open(json_file_path, 'w') as f:
            # Use indent for a nicely formatted (human-readable) file
            json.dump(data, f, indent=4)
        print(f"\nSuccessfully updated '{json_file_path}' with new data.")
    except IOError as e:
        print(f"Error writing to file '{json_file_path}'. Error: {e}")


if __name__ == "__main__":
    scrape_and_update('data.json')