"""
Fallback data fetcher using Treasury.gov + BLS for FRED alternatives.
Use this if fetch_data.py fails due to FRED timeouts.
"""
import pandas as pd
import requests
import yfinance as yf
from io import StringIO
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

START = "2004-01-01"
END   = "2026-05-31"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
}

# ---------- Yahoo Finance: Gold, VIX, DXY, 10yr Treasury ----------
yf_tickers = {
    "GC=F":     "Gold",
    "^VIX":     "VIX",
    "DX-Y.NYB": "DXY",
    "^TNX":     "Treasury_10yr",   # nominal 10-yr yield (to derive real rate)
}

yf_data = {}
for ticker, label in yf_tickers.items():
    df = yf.download(ticker, start=START, end=END, progress=False, auto_adjust=True)
    df = df[["Close"]].rename(columns={"Close": label})
    yf_data[label] = df
    print(f"OK  {label:15s} {len(df)} rows  last: {df.index[-1].date()}")

# ---------- Treasury.gov: Daily TIPS yields ----------
# Treasury publishes TIPS yield curve rates directly
tips_url = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-xml-data-download?"
    "type=daily_treasury_real_yield_curve&field_tdr_date_value=all&download=true"
)
# Fallback: use pre-built CSV from Treasury API
# TIPS 10-yr is column 'BC_10YEAR' in the real yield curve file
try:
    r = requests.get(tips_url, headers=headers, timeout=60)
    print(f"Treasury TIPS status: {r.status_code}, size: {len(r.content)} bytes")
except Exception as e:
    print(f"Treasury TIPS failed: {e}")

# ---------- Alternative: Use FRED API with key if available ----------
# Set FRED_API_KEY env variable to use this
import os
fred_api_key = os.environ.get("FRED_API_KEY", "")
if fred_api_key:
    fred_series = {
        "DFII10":   "TIPS_10yr",
        "T10YIE":   "Breakeven",
        "DFF":      "Fed_Rate",
        "CPIAUCSL": "CPI",
    }
    for series_id, label in fred_series.items():
        url = (f"https://api.stlouisfed.org/fred/series/observations"
               f"?series_id={series_id}&api_key={fred_api_key}"
               f"&observation_start={START}&file_type=json")
        r = requests.get(url, headers=headers, timeout=60)
        data = r.json()
        df = pd.DataFrame(data["observations"])[["date", "value"]]
        df.columns = ["DATE", label]
        df["DATE"] = pd.to_datetime(df["DATE"])
        df[label] = pd.to_numeric(df[label], errors="coerce")
        df = df.set_index("DATE")
        print(f"OK  {label:12s} {len(df)} rows via FRED API")
else:
    print("\nNo FRED_API_KEY found. Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html")
    print("Then run: $env:FRED_API_KEY='your_key_here'; python fetch_data_fallback.py")
