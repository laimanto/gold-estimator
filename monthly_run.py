#!/usr/bin/env python3
"""
monthly_run.py  —  Gold Price Estimator monthly automation
===========================================================
Run once a month (manually or via Windows Task Scheduler).

Flow:
  1. Load Anthropic API key from Doc/anthropic.txt
  2. Check WGC file freshness — popup reminder if stale (>100 days)
  3. fetch_data.py  — refresh live FRED + yfinance data
  4. model.py       — refit OLS model
  5. Claude API     — research >5% weight factors, return updated forecasts
  6. Patch ANALYST  — write new values + comments into export_html.py
  7. export_html.py — new forecast log entry + regenerate dashboard
  8. git add / commit / push

Task Scheduler setup (one-time, run on day 1 of each month):
  - Open Task Scheduler → Create Basic Task
  - Trigger : Monthly, day 1, time 09:00
  - Action  : Start a program
  - Program : C:\\Users\\laima\\AppData\\Local\\Programs\\Python\\Python311\\python.exe
              (adjust to your python path — run `where python` to find it)
  - Arguments: "D:\\Backup D\\Weekly\\USB drive\\Invest\\AI invest\\Gold\\monthly_run.py"
  - Start in : D:\\Backup D\\Weekly\\USB drive\\Invest\\AI invest\\Gold
"""

import json, re, subprocess, sys
from datetime import date, datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
V2   = ROOT / "gold_estimator_v2"
GIT  = Path(r"C:\Users\laima\AppData\Local\GitHubDesktop\app-3.5.12\resources\app\git\cmd\git.exe")
LOG  = ROOT / "monthly_run.log"

# Factors Claude will research (Dollar Era weight >5%, excluding dynamic WGC fields)
RESEARCH_FACTORS = {
    "TIPS_10yr":         "10yr TIPS yield (%),              FRED DFII10",
    "Breakeven":         "10yr inflation expectation (%),   FRED T10YIE",
    "DXY":               "US Dollar Index,                  DX-Y.NYB",
    "Oil_WTI":           "WTI Crude Oil $/bbl,              CL=F",
    "CB_Net_Purchases":  "Central bank gold demand t/qtr,   WGC",
    "ETF_Flow":          "Gold ETF net flow t/qtr,          WGC",
    "DJP":               "Bloomberg Commodity ETF price,    DJP",
}

# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── Step 1: API key ───────────────────────────────────────────────────────────
def load_api_key():
    for p in [ROOT / "Doc" / "anthropic.txt", V2 / "Doc" / "anthropic.txt"]:
        if p.exists():
            key = p.read_text(encoding="utf-8").strip()
            if key:
                return key
    sys.exit("ERROR: Doc/anthropic.txt not found or empty — add your Anthropic API key there.")


# ── Step 2: WGC file check ────────────────────────────────────────────────────
def check_wgc():
    import glob as _g
    files = sorted(_g.glob(str(V2 / "data" / "GDT_Tables_Q*_EN.xlsx")))
    if not files:
        _remind("WGC FILE MISSING",
                "WGC GDT file not found.\n"
                "Download from: gold.org/goldhub/research/gold-demand-trends\n"
                f"Place in: {V2 / 'data'}")
        return False
    latest  = Path(files[-1])
    age     = (date.today() - date.fromtimestamp(latest.stat().st_mtime)).days
    log(f"WGC file: {latest.name}  ({age} days old)")
    if age > 100:
        _remind(
            "WGC FILE STALE — ACTION REQUIRED",
            f"Current file: {latest.name}  ({age} days old)\n\n"
            "A new quarter's data is likely available.\n"
            "1. Go to: gold.org/goldhub/research/gold-demand-trends\n"
            "2. Download the latest GDT_Tables_Q?xx_EN.xlsx\n"
            f"3. Place it in:  {V2 / 'data'}\n"
            "4. Re-run monthly_run.py\n\n"
            "Release schedule: Q1→May  Q2→Aug  Q3→Nov  Q4→Feb"
        )
        return False
    return True


def _remind(title, msg):
    log(f"⚠️  {title}:\n{msg}")
    # Write a reminder file the user will notice
    reminder = ROOT / "WGC_DOWNLOAD_REMINDER.txt"
    reminder.write_text(f"{title}\n{'='*60}\n{msg}\n\nGenerated: {date.today()}\n",
                        encoding="utf-8")
    # Try Windows popup (works when run interactively; silently skipped in headless Task Scheduler)
    try:
        safe_msg = msg.replace('"', "'").replace("\n", "\\n")
        subprocess.run(
            ["powershell", "-Command",
             f'Add-Type -AssemblyName System.Windows.Forms;'
             f'[System.Windows.Forms.MessageBox]::Show("{safe_msg}", "{title}", "OK", "Warning")'],
            capture_output=True, timeout=15
        )
    except Exception:
        pass


# ── Step 3 & 4: Run python scripts ───────────────────────────────────────────
def run_script(label, script_path):
    log(f"Running {label} ...")
    r = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True, text=True, cwd=str(V2)
    )
    if r.returncode not in (0, 255):   # 255 = harmless PowerShell exit quirk
        log(f"  ERROR in {label}:\n{r.stderr[-600:]}")
        raise RuntimeError(f"{label} failed (exit {r.returncode})")
    log(f"  {label} done.")


# ── Step 5: Claude factor research ───────────────────────────────────────────
def research_factors(api_key, current_vals, analyst_vals):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    today  = date.today().strftime("%Y-%m-%d")

    ctx_lines = []
    for key, desc in RESEARCH_FACTORS.items():
        cur  = current_vals.get(key, "n/a")
        prev = analyst_vals.get(key, "n/a")
        if isinstance(cur,  float): cur  = round(cur,  3)
        if isinstance(prev, float): prev = round(prev, 3)
        ctx_lines.append(f"  {key:<22} live={cur:<10} last_3m_forecast={prev:<10} ({desc})")

    prompt = f"""Today: {today}. You are the analyst updating a gold price OLS model's 3-month forecasts.

Live values (just fetched) vs last month's 3-month forecasts:
{chr(10).join(ctx_lines)}

Dollar Era model weights for context:
  ETF_Residual=30%  BCOM_exGold/DJP=17%  Oil=11%  CB_Purchases=9%
  DXY=9%  TIPS=7%  Jewellery=6%  (others <5%)

Provide updated 3-month forecasts. Reason about:
- Fed policy and real rate trajectory (TIPS, Breakeven)
- USD drivers: inflation differentials, risk appetite (DXY)
- Oil: OPEC+ supply, geopolitical risk premium (Oil_WTI)
- Central bank gold demand: de-dollarisation trend (CB_Net_Purchases)
- Commodity cycle: energy vs metals/ag mix (DJP)
- ETF flow momentum: retail/institutional sentiment (ETF_Flow)

Return ONLY a valid JSON object with no other text:
{{
  "TIPS_10yr": <float>,
  "Breakeven": <float>,
  "DXY": <float>,
  "Oil_WTI": <float>,
  "CB_Net_Purchases": <float>,
  "ETF_Flow": <float>,
  "DJP": <float>,
  "comments": {{
    "TIPS_10yr": "<one concise sentence>",
    "Breakeven": "<one concise sentence>",
    "DXY": "<one concise sentence>",
    "Oil_WTI": "<one concise sentence>",
    "CB_Net_Purchases": "<one concise sentence>",
    "ETF_Flow": "<one concise sentence>",
    "DJP": "<one concise sentence>"
  }}
}}"""

    log("Calling Claude (Haiku) for factor research ...")
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}]
    )
    text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    log(f"  Tokens used: {resp.usage.input_tokens} in / {resp.usage.output_tokens} out")

    start = text.find("{")
    end   = text.rfind("}") + 1
    if start < 0:
        raise ValueError(f"Claude returned no JSON:\n{text[:300]}")
    return json.loads(text[start:end])


# ── Step 5b: Read existing ANALYST values from export_html.py ────────────────
def read_analyst_values():
    src, result, inside = (V2 / "export_html.py").read_text(encoding="utf-8"), {}, False
    for line in src.splitlines():
        if "ANALYST = {" in line:
            inside = True
        if inside:
            m = re.match(r'\s+"(\w+)":\s+([\d.]+),', line)
            if m:
                try:
                    result[m.group(1)] = float(m.group(2))
                except ValueError:
                    pass
        if inside and line.strip() == "}":
            break
    return result


# ── Step 6: Patch ANALYST dict in export_html.py ─────────────────────────────
def patch_analyst(new_vals, comments):
    path  = V2 / "export_html.py"
    src   = path.read_text(encoding="utf-8")
    today = date.today().strftime("%d %b %Y")

    # Keys with fixed float values (patchable)
    patchable = ["TIPS_10yr", "Breakeven", "DXY", "Oil_WTI",
                 "CB_Net_Purchases", "ETF_Flow"]
    for key in patchable:
        if key not in new_vals:
            continue
        val     = new_vals[key]
        comment = comments.get(key, f"Updated {today}")
        # Match:  "KEY":   <number>,   # <anything to end of line>
        pat  = rf'("{re.escape(key)}":\s+)[\d.]+,([ \t]+#[^\n]*)'
        repl = rf'\g<1>{val:.2f},\g<2>'
        # Replace number, keep spacing and update comment text
        src = re.sub(pat, lambda m: f'{m.group(1)}{val:.2f},{m.group(2).split("#")[0]}# {comment}', src)

    # DJP has a dynamic default — replace whole value expression
    if "DJP" in new_vals:
        val     = new_vals["DJP"]
        comment = comments.get("DJP", f"Updated {today}")
        pat  = r'"DJP":\s+(?:cur\.get\("DJP"\) or [\d.]+|[\d.]+),([ \t]+#[^\n]*)'
        src  = re.sub(pat, lambda m: f'"DJP":            {val:.2f},{m.group(1).split("#")[0]}# {comment}', src)

    path.write_text(src, encoding="utf-8")
    log(f"Patched ANALYST in export_html.py:")
    for k in list(patchable) + ["DJP"]:
        if k in new_vals:
            log(f"  {k:<22} → {new_vals[k]:.2f}   # {comments.get(k, '')[:60]}")


# ── Step 8: Git commit + push ─────────────────────────────────────────────────
def git_push():
    today = date.today().strftime("%Y-%m-%d")
    def _git(*args):
        r = subprocess.run([str(GIT)] + list(args), cwd=str(ROOT),
                           capture_output=True, text=True)
        return r.stdout.strip(), r.stderr.strip(), r.returncode

    _git("add", "-A")
    out, err, rc = _git("commit", "-m", f"Monthly update: {today}")
    if rc != 0:
        if "nothing to commit" in (out + err):
            log("Git: nothing new to commit.")
            return
        log(f"Git commit warning: {err[:200]}")
    else:
        log(f"Git commit: {out[:80]}")

    out, err, rc = _git("push")
    if rc != 0:
        log(f"Git push warning: {err[:200]}")
    else:
        log("Git push: OK → github.com/laimanto/gold-estimator")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    today = date.today().strftime("%Y-%m-%d")
    log(f"\n{'='*60}")
    log(f"Gold Estimator Monthly Run — {today}")
    log(f"{'='*60}")

    # 1. API key
    api_key = load_api_key()
    log("API key loaded.")

    # 2. WGC check
    wgc_ok = check_wgc()
    if not wgc_ok:
        log("Continuing with prior WGC data — structural demand uses last known quarter.")

    # 3. Fetch live data
    run_script("fetch_data.py", V2 / "fetch_data.py")

    # 4. Refit model
    run_script("model.py", V2 / "model.py")

    # 5. Claude factor research
    with open(V2 / "data" / "model_results.json", encoding="utf-8") as f:
        current_vals = json.load(f).get("current", {})
    analyst_vals = read_analyst_values()

    research  = research_factors(api_key, current_vals, analyst_vals)
    comments  = research.pop("comments", {})

    # 6. Patch ANALYST values
    patch_analyst(research, comments)

    # 7. Regenerate dashboard (also writes forecast log entry)
    run_script("export_html.py", V2 / "export_html.py")

    # 8. Publish
    git_push()

    log(f"\n✓ Done — {today}")
    log("  https://laimanto.github.io/gold-estimator/gold_estimator_v2/Doc/dashboard.html")


if __name__ == "__main__":
    main()
