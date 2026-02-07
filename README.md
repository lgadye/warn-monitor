# California WARN Notice Monitor

Automated monitoring of California WARN (Worker Adjustment and Retraining Notification) notices for specific companies.

## Features

✅ **Automatic URL Detection** - Scrapes the latest XLSX link from the EDD page (handles filename changes)  
✅ **Fuzzy Company Matching** - Catches name variations like "Anthropic" vs "Anthropic PBC"  
✅ **Change Detection** - Only alerts on genuinely new notices  
✅ **Email Notifications** - Sends formatted alerts when new notices appear  
✅ **State Persistence** - Remembers what notices have been seen  
✅ **GitHub Actions Ready** - Runs automatically on schedule  

---

## Quick Start

### Option 1: Local Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Edit configuration in warn_monitor.py
# Update: target_company, email settings

# Run manually
python warn_monitor.py
```

### Option 2: GitHub Actions (Recommended)

1. **Create a new GitHub repository**
   ```bash
   git init
   git add warn_monitor.py requirements.txt
   mkdir -p .github/workflows
   mv .github_workflows_warn-monitor.yml .github/workflows/warn-monitor.yml
   git commit -m "Initial commit"
   git remote add origin https://github.com/YOUR-USERNAME/warn-monitor.git
   git push -u origin main
   ```

2. **Configure GitHub Secrets**
   
   Go to: **Settings → Secrets and variables → Actions → New repository secret**
   
   Add these secrets:
   - `SMTP_SENDER_EMAIL`: Your Gmail address (e.g., `you@gmail.com`)
   - `SMTP_SENDER_PASSWORD`: Your Gmail App Password ([how to create](https://support.google.com/accounts/answer/185833))
   - `SMTP_RECIPIENT_EMAIL`: Where to send alerts (can be same as sender)

3. **Update the script configuration**
   
   Edit `warn_monitor.py` and update the `CONFIG` section:
   ```python
   CONFIG = {
       "target_company": "Anthropic",  # ← Change this
       "email_alerts": True,
       # ... rest stays the same
   }
   ```

4. **Enable GitHub Actions**
   
   - Go to the **Actions** tab in your repo
   - Enable workflows if prompted
   - The script will run every Monday at 9 AM UTC
   - You can also click "Run workflow" to test immediately

---

## Configuration Options

Edit the `CONFIG` dictionary in `warn_monitor.py`:

| Setting | Description | Default |
|---------|-------------|---------|
| `target_company` | Company name to monitor | `"Anthropic"` |
| `fuzzy_match_threshold` | Similarity score (0-100) for name matching | `85` |
| `email_alerts` | Enable/disable email notifications | `True` |
| `warn_page_url` | EDD WARN page URL | (California EDD) |

### Fuzzy Matching Examples

With threshold `85`:
- ✅ "Anthropic" matches "Anthropic PBC"
- ✅ "Google" matches "Google LLC"
- ✅ "Meta Platforms" matches "Meta Platforms Inc."
- ❌ "Apple" does NOT match "Alphabet"

Lower the threshold to be more permissive (more false positives).

---

## How It Works

### High-Level Logic Flow

```
1. FETCH → Scrape EDD WARN page HTML
           ↓
2. EXTRACT → Find latest XLSX download link
           ↓
3. DOWNLOAD → Get the Excel file
           ↓
4. HASH → Compute file fingerprint (SHA256)
           ↓
5. CHANGED? → Compare with last week's hash
    │
    ├─ NO → Exit (no updates)
    │
    └─ YES → Continue...
           ↓
6. PARSE → Read Excel into DataFrame
           ↓
7. FILTER → Fuzzy match company name
           ↓
8. DETECT NEW → Compare with seen_notices list
           ↓
9. ALERT → Send email if new notices found
           ↓
10. SAVE STATE → Update warn_state.json
```

### Key Components

**1. Smart URL Extraction**
```python
extract_xlsx_url(html_content, base_url)
```
- Searches for links containing "warn" + ".xlsx"
- Handles both relative and absolute URLs
- Adapts to filename changes automatically

**2. Fuzzy Company Matching**
```python
fuzzy_match_company(company_name, target, threshold=85)
```
- Uses token-based similarity scoring
- Handles: abbreviations, suffixes (Inc/LLC/PBC), punctuation
- Returns True if similarity ≥ threshold

**3. State Persistence**
```json
{
  "last_file_hash": "a1b2c3...",
  "last_check": "2025-02-06T09:00:00",
  "seen_notices": ["Anthropic|2025-01-15", ...]
}
```
- Tracks file changes via hash
- Remembers which notices have been seen
- Prevents duplicate alerts

**4. Change Detection**
```python
detect_new_notices(current_matches, state)
```
- Creates unique keys for each notice (company + date)
- Compares against `seen_notices` list
- Returns only truly new entries

---

## Email Notification Setup

### For Gmail:

1. **Enable 2-Factor Authentication**
   - Go to Google Account → Security
   - Turn on 2-Step Verification

2. **Generate App Password**
   - Visit: https://myaccount.google.com/apppasswords
   - Create password for "Mail" → "Other: WARN Monitor"
   - Copy the 16-character password

3. **Use in GitHub Secrets**
   - `SMTP_SENDER_PASSWORD` = the 16-character app password (not your regular password)

### For Other Email Providers:

Edit the `smtp_config` in `warn_monitor.py`:

```python
"smtp_config": {
    "server": "smtp.office365.com",  # Outlook
    "port": 587,
    # ... etc
}
```

Common SMTP servers:
- Gmail: `smtp.gmail.com:587`
- Outlook: `smtp.office365.com:587`
- Yahoo: `smtp.mail.yahoo.com:587`

---

## Testing & Troubleshooting

### Test Locally First

```bash
# Dry run (see what it finds)
python warn_monitor.py

# Check state file
cat warn_state.json
```

### Common Issues

**"Could not find XLSX download link"**
- EDD changed their page structure
- Update the `extract_xlsx_url()` function's CSS selectors

**"No new notices" but you expect some**
- Check `warn_state.json` → clear `seen_notices` to reset
- Lower `fuzzy_match_threshold` if name matching is too strict

**Email not sending**
- Verify Gmail App Password (not regular password)
- Check spam folder
- Enable "Less secure app access" if using old Gmail setup

**GitHub Actions not running**
- Check Actions tab for errors
- Verify secrets are set correctly
- Ensure workflow file is in `.github/workflows/` (not `_workflows`)

---

## Customization Examples

### Monitor Multiple Companies

```python
# In main(), loop over multiple companies:
for company in ["Anthropic", "OpenAI", "Scale AI"]:
    CONFIG['target_company'] = company
    # ... run monitoring logic
```

### Change Schedule

Edit `.github/workflows/warn-monitor.yml`:

```yaml
schedule:
  - cron: '0 9 * * 1'    # Every Monday 9 AM
  - cron: '0 9 * * 4'    # Every Thursday 9 AM
```

Use [crontab.guru](https://crontab.guru/) to design schedules.

### Save Results to CSV

```python
# After filtering matches:
if not matches.empty:
    matches.to_csv(f"results_{datetime.now():%Y%m%d}.csv", index=False)
```

---

## File Structure

```
warn-monitor/
├── warn_monitor.py          # Main script
├── requirements.txt         # Python dependencies
├── warn_state.json         # State persistence (auto-generated)
├── .github/
│   └── workflows/
│       └── warn-monitor.yml # GitHub Actions config
└── README.md               # This file
```

---

## Security Notes

⚠️ **Never commit credentials to Git**
- Use GitHub Secrets for email passwords
- Add `warn_state.json` to `.gitignore` if it contains sensitive data

⚠️ **App Passwords are safer than regular passwords**
- They're specific to one application
- Can be revoked without changing your main password

---

## License

MIT License - feel free to modify and adapt for your needs.

---

## Support

For issues or questions:
1. Check the Troubleshooting section
2. Review GitHub Actions logs (Actions tab → latest run → click job)
3. Test locally with verbose output
