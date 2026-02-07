#!/usr/bin/env python3
"""
California WARN Notice Monitor
Monitors the latest WARN report for specific company layoff notices.
Supports monitoring multiple companies in a single run.
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
from io import BytesIO
import json
import hashlib
from datetime import datetime
from pathlib import Path
from fuzzywuzzy import fuzz
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sys
import os

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    "warn_page_url": "https://edd.ca.gov/en/jobs_and_training/Layoff_Services_WARN/",
    # List of companies to monitor - add as many as you want
    "target_companies": ["UCSF", "UC San Francisco"],
    "fuzzy_match_threshold": 85,  # Similarity score (0-100) for fuzzy matching
    "state_file": "warn_state.json",  # Tracks what we've already seen
    "email_alerts": True,  # Set to False to disable email notifications
    "smtp_config": {
        "server": "smtp.gmail.com",
        "port": 587,
        # GitHub Actions will inject these via environment variables
        # For local testing, you can hardcode them here
        "sender_email": os.getenv("SMTP_SENDER_EMAIL", "your-email@gmail.com"),
        "sender_password": os.getenv("SMTP_SENDER_PASSWORD", "your-app-password"),
        "recipient_email": os.getenv("SMTP_RECIPIENT_EMAIL", "your-email@gmail.com"),
    }
}

# ============================================================================
# CORE FUNCTIONS
# ============================================================================

def fetch_warn_page(url):
    """Fetch the WARN notices page HTML."""
    print(f"[{datetime.now()}] Fetching WARN page...")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"ERROR: Failed to fetch WARN page: {e}")
        sys.exit(1)


def extract_xlsx_url(html_content, base_url):
    """
    Extract the latest WARN report XLSX download URL from the page HTML.
    Looks for links in the "Latest WARN Report" section.
    """
    print(f"[{datetime.now()}] Parsing HTML to find XLSX link...")
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Strategy 1: Find links containing "warn" and ending in ".xlsx"
    xlsx_links = soup.find_all('a', href=lambda x: x and 'warn' in x.lower() and x.endswith('.xlsx'))
    
    if not xlsx_links:
        # Strategy 2: Find any .xlsx link on the page
        xlsx_links = soup.find_all('a', href=lambda x: x and x.endswith('.xlsx'))
    
    if not xlsx_links:
        print("ERROR: Could not find XLSX download link on page")
        sys.exit(1)
    
    # Take the first match (usually the latest report)
    xlsx_path = xlsx_links[0]['href']
    
    # Handle relative vs absolute URLs
    if xlsx_path.startswith('http'):
        xlsx_url = xlsx_path
    else:
        # Construct absolute URL
        from urllib.parse import urljoin
        xlsx_url = urljoin(base_url, xlsx_path)
    
    print(f"[{datetime.now()}] Found XLSX URL: {xlsx_url}")
    return xlsx_url


def download_xlsx(url):
    """Download the XLSX file and return as bytes."""
    print(f"[{datetime.now()}] Downloading XLSX file...")
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        return response.content
    except requests.RequestException as e:
        print(f"ERROR: Failed to download XLSX: {e}")
        sys.exit(1)


def parse_xlsx(xlsx_bytes):
    """Parse XLSX bytes into a pandas DataFrame."""
    print(f"[{datetime.now()}] Parsing XLSX file...")
    try:
        # Read the "Detailed WARN Report" sheet (sheet index 2, or by name)
        df = pd.read_excel(
            BytesIO(xlsx_bytes), 
            engine='openpyxl',
            sheet_name='Detailed WARN Report'  # Specify the correct sheet
        )
        print(f"[{datetime.now()}] Found {len(df)} total WARN notices in file")
        return df
    except Exception as e:
        print(f"ERROR: Failed to parse XLSX: {e}")
        # Fallback: try by index if name doesn't work
        try:
            df = pd.read_excel(
                BytesIO(xlsx_bytes), 
                engine='openpyxl',
                sheet_name=2  # Third sheet (0-indexed)
            )
            print(f"[{datetime.now()}] Found {len(df)} total WARN notices in file (using sheet index)")
            return df
        except Exception as e2:
            print(f"ERROR: Failed to parse XLSX with fallback: {e2}")
            sys.exit(1)

def fuzzy_match_company(company_name, target, threshold=85):
    """
    Use fuzzy string matching to detect company name variations.
    Returns True if similarity score >= threshold.
    """
    if pd.isna(company_name):
        return False
    
    # Normalize both strings
    company_clean = str(company_name).strip().lower()
    target_clean = target.strip().lower()
    
    # Calculate similarity score
    score = fuzz.token_set_ratio(company_clean, target_clean)
    return score >= threshold


def filter_company_records(df, target_company, threshold=85):
    """
    Filter DataFrame for records matching the target company.
    Uses fuzzy matching to handle name variations.
    """
    print(f"[{datetime.now()}] Filtering for company: {target_company}")
    
    # Try to identify the company name column
    # Common column names in WARN notices
    possible_columns = ['Company', 'Employer', 'Company Name', 'Business Name', 'Name']
    company_col = None
    
    for col in df.columns:
        if any(pc.lower() in str(col).lower() for pc in possible_columns):
            company_col = col
            break
    
    if company_col is None:
        print(f"WARNING: Could not identify company name column. Columns: {list(df.columns)}")
        print("Using first column as company name column")
        company_col = df.columns[0]
    
    print(f"[{datetime.now()}] Using column '{company_col}' for company matching")
    
    # Apply fuzzy matching
    matches = df[df[company_col].apply(
        lambda x: fuzzy_match_company(x, target_company, threshold)
    )]
    
    print(f"[{datetime.now()}] Found {len(matches)} matching records")
    return matches


def compute_file_hash(xlsx_bytes):
    """Compute SHA256 hash of the XLSX file for change detection."""
    return hashlib.sha256(xlsx_bytes).hexdigest()


def load_state(state_file):
    """Load previous state from JSON file."""
    state_path = Path(state_file)
    if state_path.exists():
        with open(state_path, 'r') as f:
            return json.load(f)
    return {
        "last_file_hash": None,
        "last_check": None,
        # Note: seen_notices will be stored per-company as "seen_notices_CompanyName"
    }


def save_state(state_file, state):
    """Save current state to JSON file."""
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)


def detect_new_notices(current_matches, state):
    """
    Detect which notices are new since last check.
    Returns list of new notice dictionaries.
    """
    if current_matches.empty:
        return []
    
    seen_notices = set(state.get("seen_notices", []))
    new_notices = []
    
    # Create a unique identifier for each notice
    # Using company + date as a simple key
    for _, row in current_matches.iterrows():
        # Convert row to dict and create identifier
        notice_dict = row.to_dict()
        
        # Try to create a unique key (adapt based on actual column names)
        # Common patterns: Company + Notice Date or Company + Layoff Date
        key_parts = []
        for col in row.index:
            if 'date' in str(col).lower() or 'company' in str(col).lower():
                key_parts.append(str(row[col]))
        
        notice_key = "|".join(key_parts) if key_parts else str(hash(str(row.to_dict())))
        
        if notice_key not in seen_notices:
            new_notices.append(notice_dict)
            seen_notices.add(notice_key)
    
    # Update state with all current notices
    state["seen_notices"] = list(seen_notices)
    
    return new_notices


def send_consolidated_email_alert(all_new_notices, config):
    """Send consolidated email notification for multiple companies."""
    if not config.get("email_alerts"):
        return
    
    smtp_config = config.get("smtp_config", {})
    
    if not all([smtp_config.get("sender_email"), 
                smtp_config.get("sender_password"),
                smtp_config.get("recipient_email")]):
        print("WARNING: Email alerts enabled but SMTP config incomplete. Skipping email.")
        return
    
    print(f"[{datetime.now()}] Sending consolidated email alert...")
    
    total_notices = sum(len(notices) for notices in all_new_notices.values())
    companies_list = ", ".join(all_new_notices.keys())
    
    # Create email content
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"⚠️ WARN Alert: {total_notices} notice(s) for {len(all_new_notices)} companies"
    msg['From'] = smtp_config['sender_email']
    msg['To'] = smtp_config['recipient_email']
    
    # Plain text version
    text_parts = [
        f"New WARN notice(s) detected",
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Companies: {companies_list}",
        f"Total notices: {total_notices}\n",
        "=" * 60,
    ]
    
    for company, notices in all_new_notices.items():
        text_parts.append(f"\n{'='*60}")
        text_parts.append(f"COMPANY: {company} ({len(notices)} notice(s))")
        text_parts.append(f"{'='*60}")
        
        for i, notice in enumerate(notices, 1):
            text_parts.append(f"\nNotice #{i}:")
            for key, value in notice.items():
                text_parts.append(f"  {key}: {value}")
            text_parts.append("")
    
    text_content = "\n".join(text_parts)
    
    # HTML version
    html_parts = [
        "<html><body>",
        f"<h2>⚠️ New WARN Notices Alert</h2>",
        f"<p><strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>",
        f"<p><strong>Companies:</strong> {companies_list}</p>",
        f"<p><strong>Total notices:</strong> {total_notices}</p>",
        "<hr>",
    ]
    
    for company, notices in all_new_notices.items():
        html_parts.append(f"<h3>{company} ({len(notices)} notice(s))</h3>")
        
        for i, notice in enumerate(notices, 1):
            html_parts.append(f"<h4>Notice #{i}</h4>")
            html_parts.append("<table border='1' cellpadding='5'>")
            for key, value in notice.items():
                html_parts.append(f"<tr><td><strong>{key}</strong></td><td>{value}</td></tr>")
            html_parts.append("</table><br>")
    
    html_parts.append("</body></html>")
    html_content = "\n".join(html_parts)
    
    # Attach both versions
    part1 = MIMEText(text_content, 'plain')
    part2 = MIMEText(html_content, 'html')
    msg.attach(part1)
    msg.attach(part2)
    
    # Send email
    try:
        with smtplib.SMTP(smtp_config['server'], smtp_config['port']) as server:
            server.starttls()
            server.login(smtp_config['sender_email'], smtp_config['sender_password'])
            server.send_message(msg)
        print(f"[{datetime.now()}] Consolidated email alert sent successfully")
    except Exception as e:
        print(f"ERROR: Failed to send email: {e}")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution function."""
    print("=" * 70)
    print("California WARN Notice Monitor (Multi-Company)")
    print(f"Target Companies: {', '.join(CONFIG['target_companies'])}")
    print(f"Started: {datetime.now()}")
    print("=" * 70)
    
    # Load previous state
    state = load_state(CONFIG['state_file'])
    print(f"[{datetime.now()}] Last check: {state.get('last_check', 'Never')}")
    
    # Fetch and parse the WARN page (once for all companies)
    html_content = fetch_warn_page(CONFIG['warn_page_url'])
    xlsx_url = extract_xlsx_url(html_content, CONFIG['warn_page_url'])
    xlsx_bytes = download_xlsx(xlsx_url)
    file_hash = compute_file_hash(xlsx_bytes)
    
    # Check if file has changed since last run
    if file_hash == state.get('last_file_hash'):
        print(f"[{datetime.now()}] File unchanged since last check (hash: {file_hash[:16]}...)")
        print(f"[{datetime.now()}] No updates needed")
        state['last_check'] = datetime.now().isoformat()
        save_state(CONFIG['state_file'], state)
        return
    
    print(f"[{datetime.now()}] File has changed (new hash: {file_hash[:16]}...)")
    
    # Parse once (efficient - only parse the Excel file once for all companies)
    df = parse_xlsx(xlsx_bytes)
    
    # Track all new notices across all companies
    all_new_notices = {}
    
    # Check each company
    for company in CONFIG['target_companies']:
        print(f"\n{'='*70}")
        print(f"Checking company: {company}")
        print(f"{'='*70}")
        
        matches = filter_company_records(
            df, 
            company,
            CONFIG['fuzzy_match_threshold']
        )
        
        # Use company-specific state tracking
        # Sanitize company name for use as dictionary key
        company_key = f"seen_notices_{company.replace(' ', '_').replace(',', '').replace('.', '')}"
        company_state = {
            "seen_notices": state.get(company_key, [])
        }
        
        new_notices = detect_new_notices(matches, company_state)
        
        if new_notices:
            all_new_notices[company] = new_notices
            print(f"[{datetime.now()}] 🚨 ALERT: {len(new_notices)} NEW notice(s) for {company}!")
            for i, notice in enumerate(new_notices, 1):
                print(f"\n--- New Notice #{i} ---")
                for key, value in notice.items():
                    print(f"{key}: {value}")
        else:
            print(f"[{datetime.now()}] No new notices for {company}")
        
        # Update state for this company
        state[company_key] = company_state["seen_notices"]
    
    # Send consolidated email if any new notices found
    if all_new_notices:
        print(f"\n{'='*70}")
        print(f"SUMMARY: Found new notices for {len(all_new_notices)} companies")
        print(f"{'='*70}")
        send_consolidated_email_alert(all_new_notices, CONFIG)
    else:
        print(f"\n{'='*70}")
        print(f"SUMMARY: No new notices found for any monitored companies")
        print(f"{'='*70}")
    
    # Update and save state
    state['last_file_hash'] = file_hash
    state['last_check'] = datetime.now().isoformat()
    save_state(CONFIG['state_file'], state)
    
    print("=" * 70)
    print(f"[{datetime.now()}] Monitor run completed successfully")
    print("=" * 70)


if __name__ == "__main__":
    main()
