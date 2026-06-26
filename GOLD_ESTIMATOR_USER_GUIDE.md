# Gold Price Estimator — Monthly User Guide

**Dashboard:** https://laimanto.github.io/gold-estimator/gold_estimator_v2/Doc/dashboard.html  
**Repository:** https://github.com/laimanto/gold-estimator  
**Anthropic usage:** https://console.anthropic.com/settings/usage  

---

## 1. Monthly Workflow (every 1st of the month)

The Task Scheduler runs automatically at **09:00 on the 1st of each month**.  
If your PC was off that day, it runs automatically on your **next login**.

You do not need to do anything — just check the log afterwards:

```
D:\Backup D\Weekly\USB drive\Invest\AI invest\Gold\monthly_run.log
```

A successful run ends with:
```
✓ Done — 2026-XX-XX
  https://laimanto.github.io/...
```

---

## 2. WGC Data — Download Reminder Calendar

The World Gold Council releases new data quarterly. You must download it manually
(the WGC website requires login; it cannot be automated).

| Quarter | Data covers | Download available |
|---------|-------------|-------------------|
| Q1      | Jan–Mar     | **Mid-May**       |
| Q2      | Apr–Jun     | **Mid-August**    |
| Q3      | Jul–Sep     | **Mid-November**  |
| Q4      | Oct–Dec     | **Mid-February**  |

**How you will be reminded:**
- The script checks the file age every run. If the file is >100 days old:
  1. A popup appears on your screen (if you are logged in)
  2. A reminder file is written: `WGC_DOWNLOAD_REMINDER.txt` in the project root

**Steps to update WGC data:**
1. Go to: https://www.gold.org/goldhub/research/gold-demand-trends
2. Log in (free account) and download the latest `GDT_Tables_Q?xx_EN.xlsx`
3. Place it in: `D:\Backup D\Weekly\USB drive\Invest\AI invest\Gold\gold_estimator_v2\data\`
4. Re-run the monthly script manually (see Section 4)

---

## 3. What the Script Does (Each Run)

| Step | What happens |
|------|-------------|
| 1 | Loads Anthropic API key from `Doc/anthropic.txt` |
| 2 | Checks WGC file age — popup if stale |
| 3 | Fetches live data: FRED (TIPS, DXY, M2…) + yfinance (gold, DJP, oil…) |
| 4 | Refits the OLS model with latest data |
| 5 | Calls Claude Haiku API (~$0.02): researches 7 key factors, returns 3-month forecasts |
| 6 | Updates ANALYST values in `export_html.py` with new numbers + rationale |
| 7 | Regenerates dashboard HTML + adds a new row to the forecast log |
| 8 | Git commit + push → live on GitHub Pages within ~1 minute |

**Cost per run:** ≈ USD $0.02 (Claude Haiku, ~1 200 tokens)

---

## 4. Running Manually

Open PowerShell and run:

```powershell
python "D:\Backup D\Weekly\USB drive\Invest\AI invest\Gold\monthly_run.py"
```

Or right-click the file in File Explorer → "Open with" → Python.

**When to run manually:**
- After downloading new WGC data
- If the automated run failed (check the log)
- Anytime you want to refresh the dashboard mid-month

---

## 5. Checking Settings

### Task Scheduler
1. Press `Win + R` → type `taskschd.msc` → Enter
2. In the left panel click **Task Scheduler Library**
3. Find **"Gold Estimator Monthly"** in the list
4. Right-click → **Run** to trigger manually
5. Right-click → **Properties** to change the schedule

### Anthropic API Usage
- Go to: https://console.anthropic.com/settings/usage
- Each run appears as ~1 200 tokens on `claude-haiku-4-5-20251001`
- Cost is negligible (~$0.02/month)

### Live Dashboard
- URL: https://laimanto.github.io/gold-estimator/gold_estimator_v2/Doc/dashboard.html
- Updates appear within 1–2 minutes of git push

---

## 6. File & Folder Reference

```
D:\Backup D\Weekly\USB drive\Invest\AI invest\Gold\
│
├── monthly_run.py              ← automation script
├── monthly_run.log             ← log of every run (check here if something failed)
├── WGC_DOWNLOAD_REMINDER.txt   ← created when WGC data is stale (delete after updating)
├── .gitignore                  ← protects API keys from being pushed to GitHub
│
├── Doc\
│   ├── anthropic.txt           ← Anthropic API key (NEVER shared / not in git)
│   └── fred API key.txt        ← FRED API key (NEVER shared / not in git)
│
└── gold_estimator_v2\
    ├── export_html.py          ← dashboard generator; ANALYST dict is patched here monthly
    ├── fetch_data.py           ← pulls live FRED + yfinance data
    ├── model.py                ← refits OLS model
    │
    ├── data\
    │   ├── GDT_Tables_Q?xx_EN.xlsx  ← WGC quarterly file (replace quarterly)
    │   ├── forecast_log.csv         ← forecast history (auto-updated)
    │   └── model_results.json       ← current factor values + model coefficients
    │
    └── Doc\
        └── dashboard.html      ← generated dashboard (pushed to GitHub Pages)
```

---

## 7. Troubleshooting

| Symptom | Fix |
|---------|-----|
| Log shows `ERROR: Doc/anthropic.txt not found` | Check the file exists at `Doc\anthropic.txt`; the key should start with `sk-ant-` |
| Log shows `fetch_data.py failed` | Check internet connection; FRED/yfinance may be down temporarily — re-run manually |
| Log shows `Git push warning` | GitHub may have changed the token; re-authenticate via GitHub Desktop |
| Dashboard not updated on the website | Wait 2 minutes after a successful push; check https://github.com/laimanto/gold-estimator/actions |
| Task did not run automatically | Open Task Scheduler → check last run time and result code |
| WGC popup appeared | Download new GDT file (Section 2), then re-run monthly script |

---

## 8. Updating Factor Forecasts Manually (Optional)

If you want to override Claude's research for a specific factor before running:

1. Open `gold_estimator_v2\export_html.py` in any text editor
2. Find the `ANALYST = {` block (around line 89)
3. Edit the value directly, e.g. change `"Oil_WTI": 72.00,` to `"Oil_WTI": 68.00,`
4. Save and run `export_html.py` directly, or run `monthly_run.py`
   (monthly_run.py will overwrite your manual change with Claude's research —
   run `export_html.py` alone if you want to keep your manual values)

---

*Last updated: 2026-06-26*
