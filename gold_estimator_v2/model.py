"""
Two-period first-differences OLS gold price model.
Follows LBMA / Chicago Fed methodology: use monthly CHANGES to avoid
spurious co-trending from non-stationary levels series.

Dependent variable : Δln(Gold_Real) = monthly % change in real gold price
Independent vars   : monthly changes in each factor (Δ), or level for
                     stationary flow/index variables (CB, M2_Growth)

OLS assumption checks included: VIF (multicollinearity), Cook's D (influence),
outliers, Jarque-Bera (normality), Durbin-Watson (autocorrelation).

3-month model runs in two modes:
  1. Non-overlapping quarters (from monthly data)  — original approach
  2. Overlapping 13-week windows (from weekly data) — adds data, HAC SE
"""

import json, math, warnings
import numpy as np
import pandas as pd
from pathlib import Path
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
from statsmodels.stats.outliers_influence import variance_inflation_factor, OLSInfluence
from statsmodels.stats.stattools import durbin_watson
from scipy import stats as scipy_stats

warnings.filterwarnings("ignore")

DATA_PATH        = Path(__file__).parent / "data" / "gold_factors_monthly.csv"
DATA_PATH_WEEKLY = Path(__file__).parent / "data" / "gold_factors_weekly.csv"
DATA_PATH_DAILY  = Path(__file__).parent / "data" / "gold_factors_daily.csv"
OUT_JSON         = Path(__file__).parent / "data" / "model_results.json"

df = pd.read_csv(DATA_PATH, index_col=0, parse_dates=True)

# ── log transforms ───────────────────────────────────────────────────────
# Use NOMINAL gold as dependent variable — TIPS already captures inflation
# (TIPS = nominal rate − inflation expectation), so CPI deflation is redundant.
# Δln(Gold_Nominal) is directly what an investor observes on Yahoo Finance.
df["ln_Gold_Nominal"] = np.log(df["Gold"])     # nominal gold (not CPI-adjusted)
df["ln_Gold_Real"]    = np.log(df["Gold_Real"]) # kept for fair-value reference only
df["ln_DXY"]       = np.log(df["DXY"])
df["ln_QQQ"]       = np.log(df["QQQ"])
df["ln_Oil"]       = np.log(df["Oil_WTI"])
df["ln_VIX"]       = np.log(df["VIX"])
df["ln_EPU"]       = np.log(df["EPU"])

# ── first differences (monthly changes) ──────────────────────────────────
df["D_Gold"]         = df["ln_Gold_Nominal"].diff()   # nominal gold returns
df["D_TIPS_10yr"]    = df["TIPS_10yr"].diff()
df["D_Breakeven"]    = df["Breakeven"].diff()    # kept for reference; NOT in OLS
df["D_Credit_Spread"]= df["Credit_Spread"].diff()
df["D_ln_DXY"]      = df["ln_DXY"].diff()
df["D_ln_QQQ"]      = df["ln_QQQ"].diff()     # was D_ln_SP500
df["D_ln_Oil"]      = df["ln_Oil"].diff()
df["D_ln_VIX"]      = df["ln_VIX"].diff()
df["D_ln_EPU"]      = df["ln_EPU"].diff()

HAS_CB    = "CB_Net_Purchases" in df.columns
HAS_ETF   = "ETF_Flow"         in df.columns
HAS_JEWEL = "Jewellery"        in df.columns
HAS_TECH  = "Technology"       in df.columns
HAS_BC    = "Bar_Coin"         in df.columns
HAS_BCOM  = "DJP"              in df.columns
if HAS_BCOM:
    _D_ln_DJP = np.log(df["DJP"].replace(0, np.nan)).diff()
    _W_GOLD   = 0.127
    df["D_ln_BCOM_exgold"] = (_D_ln_DJP - _W_GOLD * df["D_Gold"]) / (1 - _W_GOLD)

# ── factor metadata ──────────────────────────────────────────────────────
# D_ln_Oil kept in FACTOR_META but flagged context_only (not in Dollar Era OLS)
FACTOR_META = {
    "D_TIPS_10yr":     ("Real Interest Rate (TIPS)",  "Δ pp",       "diff_level", "TIPS_10yr"),
    "D_ln_DXY":        ("US Dollar Strength (DXY)",   "Δ% (log)",   "diff_log",   "DXY"),
    "M2_Growth":       ("Money Supply Growth (M2)",    "% YoY (lvl)","level",      "M2_Growth"),
    "D_ln_VIX":        ("Market Fear (VIX)",           "Δ% (log)",   "diff_log",   "VIX"),
    "D_ln_EPU":        ("Policy Uncertainty (EPU)",    "Δ% (log)",   "diff_log",   "EPU"),
    "D_Credit_Spread": ("Credit / Default Risk",       "Δ pp",       "diff_level", "Credit_Spread"),
    "D_ln_QQQ":        ("Stock Market (QQQ)",          "Δ% (log)",   "diff_log",   "QQQ"),
    "D_ln_Oil":        ("Oil Price (WTI)",             "Δ% (log)",   "diff_log",   "Oil_WTI"),  # QE Era
    "Oil_Residual":    ("Oil Price (Commodity-Adj.)", "Δ% (log)",   "diff_log",   "Oil_WTI"),  # Dollar Era active
}
if HAS_CB:
    FACTOR_META["CB_Net_Purchases"] = ("Central Bank Buying (CB)",    "t/qtr", "level", "CB_Net_Purchases")
if HAS_ETF:
    FACTOR_META["ETF_Flow"]        = ("Gold ETF Flow (WGC)",   "t/qtr", "level", "ETF_Flow")
    FACTOR_META["ETF_Residual"]    = ("ETF Flow (Macro-Adj.)", "t/qtr", "level", "ETF_Flow")
    FACTOR_META["ETF_Residual_QE"] = ("ETF Flow (Macro-Adj.)", "t/qtr", "level", "ETF_Flow")
if HAS_JEWEL:
    FACTOR_META["Jewellery"]        = ("Jewellery Demand (WGC)",       "t/qtr", "level", "Jewellery")
if HAS_TECH:
    FACTOR_META["Technology"]       = ("Technology Demand (WGC)",      "t/qtr", "level", "Technology")
if HAS_BC:
    FACTOR_META["Bar_Coin"]         = ("Bar & Coin Demand (WGC)",      "t/qtr", "level", "Bar_Coin")
if HAS_BCOM:
    FACTOR_META["D_ln_BCOM_exgold"] = ("Commodity Index (ex-Gold)", "Δ% (log)", "diff_log", "DJP")

# Dollar Era primary OLS factors (Stage 2): ETF_Residual replaces raw ETF_Flow, Oil removed
_struct_p2 = ["CB_Net_Purchases", "ETF_Residual", "Jewellery", "Technology", "Bar_Coin"]
_struct_p1 = ["CB_Net_Purchases", "ETF_Residual_QE", "Jewellery", "Technology", "Bar_Coin"]

BASE_FACTORS = ["D_TIPS_10yr", "D_ln_DXY", "M2_Growth", "D_ln_VIX", "D_ln_EPU",
                "D_Credit_Spread", "D_ln_QQQ"]  # excludes Oil; used in QE Era

# Dollar Era: primary macro + BCOM_exgold + Oil_Residual + structural
# QE Era: same primaries + BCOM_exgold + raw Oil + structural
ALL_FACTORS_P2 = BASE_FACTORS + ["D_ln_BCOM_exgold", "Oil_Residual"] + _struct_p2
ALL_FACTORS_P1 = BASE_FACTORS + ["D_ln_BCOM_exgold", "D_ln_Oil"]     + _struct_p1

GROUPS = [
    ("Rates & Inflation",        ["D_TIPS_10yr"]),
    ("US Dollar & Money Supply", ["D_ln_DXY", "M2_Growth"]),
    ("Risk & Uncertainty",       ["D_ln_VIX", "D_ln_EPU", "D_Credit_Spread"]),
    ("Financial Markets",        ["D_ln_QQQ", "D_ln_BCOM_exgold", "Oil_Residual"]),
    ("Structural Demand",        ["CB_Net_Purchases", "ETF_Residual", "Jewellery", "Technology", "Bar_Coin"]),
]

# ── OLS assumption diagnostics ───────────────────────────────────────────

def check_assumptions(fitted, X_with_const):
    """Return dict of OLS assumption diagnostics."""
    resid = fitted.resid
    n     = len(resid)

    # VIF (drop const column)
    x_cols = [c for c in X_with_const.columns if c != "const"]
    X_arr  = X_with_const[x_cols].values
    vif = {}
    for i, col in enumerate(x_cols):
        try:
            v = variance_inflation_factor(X_arr, i)
            vif[col] = round(float(v), 2)
        except Exception:
            vif[col] = None

    high_vif = {k: v for k, v in vif.items() if v is not None and v > 5}

    # Jarque-Bera normality test
    jb_stat, jb_pval = scipy_stats.jarque_bera(resid.values)[:2]

    # Durbin-Watson (autocorrelation)
    dw = durbin_watson(resid.values)

    # Cook's distance (influential observations)
    influence  = OLSInfluence(fitted)
    cooks_d    = influence.cooks_distance[0]
    threshold  = 4.0 / n
    n_influential = int((cooks_d > threshold).sum())
    max_cooks  = float(np.nanmax(cooks_d))

    # Extreme residuals (|z| > 3)
    resid_z  = (resid - resid.mean()) / resid.std()
    n_outliers = int((resid_z.abs() > 3).sum())

    warnings_list = []
    if high_vif:
        warnings_list.append(
            f"Multicollinearity: VIF > 5 — {', '.join(f'{k}={v}' for k,v in high_vif.items())}")
    if jb_pval < 0.05:
        warnings_list.append(
            f"Residuals non-normal (Jarque-Bera p={jb_pval:.4f})")
    if abs(dw - 2.0) > 0.5:
        warnings_list.append(
            f"Serial autocorrelation concern (Durbin-Watson={dw:.2f}, expected ~2.0)")
    if n_influential > 0:
        warnings_list.append(
            f"{n_influential} influential obs (Cook's D > 4/n={threshold:.4f}, max={max_cooks:.3f})")
    if n_outliers > 0:
        warnings_list.append(
            f"{n_outliers} extreme residuals (|z| > 3 SD)")

    return {
        "vif":              vif,
        "high_vif":         high_vif,
        "jb_pval":          round(float(jb_pval), 5),
        "durbin_watson":    round(float(dw), 3),
        "n_influential":    n_influential,
        "max_cooks_d":      round(max_cooks, 4),
        "n_outliers_3sd":   n_outliers,
        "warnings":         warnings_list,
    }


def run_ols(data: pd.DataFrame, factors: list, label: str) -> tuple:
    """Returns (result_dict, fitted_model)."""
    avail = [f for f in factors if f in data.columns]
    sub   = data[["D_Gold"] + avail].dropna()
    y     = sub["D_Gold"]
    X     = add_constant(sub[avail])
    m     = OLS(y, X).fit()

    full_r2 = m.rsquared
    pr2 = {}
    for col in avail:
        rest = [c for c in avail if c != col]
        pr2[col] = max(0.0, full_r2 - OLS(y, add_constant(sub[rest])).fit().rsquared)

    total = sum(pr2.values()) or 1.0
    std_X = sub[avail].std()
    std_Y = float(y.std())
    factors_out = {}
    for col in avail:
        meta = FACTOR_META[col]
        coef = float(m.params[col])
        pval = float(m.pvalues[col])
        sig  = "***" if pval < 0.01 else "**" if pval < 0.05 else "*" if pval < 0.1 else ""
        sb   = coef * float(std_X[col]) / std_Y if std_Y > 0 else 0.0
        factors_out[col] = {
            "label":          meta[0],
            "unit":           meta[1],
            "input_type":     meta[2],
            "raw_col":        meta[3],
            "coef":           round(coef, 6),
            "pval":           round(pval, 4),
            "sig":            sig,
            "partial_r2":     round(pr2[col], 5),
            "partial_r2_pct": round(pr2[col] / total * 100, 1),
            "std_beta":       round(sb, 4),
        }

    diag = check_assumptions(m, X)

    result = {
        "label":        label,
        "n":            int(m.nobs),
        "r2":           round(m.rsquared, 4),
        "r2_adj":       round(m.rsquared_adj, 4),
        "rmse":         round(float(np.sqrt(m.mse_resid)), 6),
        "intercept":    round(float(m.params["const"]), 6),
        "factors":      factors_out,
        "diagnostics":  diag,
    }
    return result, m


def run_ols_3m_nonoverlap(data: pd.DataFrame, factors: list, label: str) -> dict:
    """3-month non-overlapping OLS from monthly data (original approach)."""
    avail = [f for f in factors if f in data.columns]
    sub   = data[["D_Gold"] + avail].dropna()

    agg = pd.DataFrame(index=sub.index)
    agg["D_Gold_3m"] = sub["D_Gold"].rolling(3).sum()
    for col in avail:
        it = FACTOR_META[col][2]
        if it == "level":
            agg[col + "_3m"] = sub[col].rolling(3).mean()
        else:
            agg[col + "_3m"] = sub[col].rolling(3).sum()

    nonov   = agg.iloc[2::3]
    cols_3m = ["D_Gold_3m"] + [c + "_3m" for c in avail]
    nonov   = nonov[cols_3m].dropna()

    if len(nonov) <= len(avail) + 3:
        return {"r2": None, "r2_adj": None, "n": len(nonov),
                "note": "insufficient data"}

    y3 = nonov["D_Gold_3m"]
    X3 = add_constant(nonov[[c + "_3m" for c in avail]])
    m3 = OLS(y3, X3).fit()

    return {
        "label":   label,
        "n":       int(m3.nobs),
        "r2":      round(m3.rsquared, 4),
        "r2_adj":  round(m3.rsquared_adj, 4),
        "method":  "non-overlapping quarterly windows (monthly data)",
    }


def run_ols_3m_weekly_overlap(factors: list, label: str,
                              period_start: str, period_end=None) -> dict:
    """
    3-month OLS using overlapping 13-week windows from weekly data.
    HAC Newey-West SE (lag=13) corrects for 12-week overlap autocorrelation.
    Returns full factor-level results (coef, sig, partial_r2_pct, std_beta, RMSE, intercept).
    Coefficients are quarterly-scale: coef × (X_forecast_level_or_change) = 3m log-return.
    """
    if not DATA_PATH_WEEKLY.exists():
        return {"r2": None, "note": "gold_factors_weekly.csv not found — run fetch_data.py first"}

    dfw = pd.read_csv(DATA_PATH_WEEKLY, index_col=0, parse_dates=True)

    # Log transforms (same as monthly model)
    for col_raw, col_ln in [("DXY","ln_DXY"),("QQQ","ln_QQQ"),("Oil_WTI","ln_Oil"),
                             ("VIX","ln_VIX"),("EPU","ln_EPU")]:
        if col_raw in dfw.columns:
            dfw[col_ln] = np.log(dfw[col_raw])

    # Use NOMINAL gold — consistent with monthly model
    if "Gold" in dfw.columns:
        dfw["D_Gold"] = np.log(dfw["Gold"]).diff()
    elif "Gold_Real" in dfw.columns:
        dfw["D_Gold"] = np.log(dfw["Gold_Real"]).diff()

    for col in ["TIPS_10yr", "Breakeven", "Credit_Spread"]:
        if col in dfw.columns:
            dfw[f"D_{col}"] = dfw[col].diff()
    for col_ln, col_d in [("ln_DXY","D_ln_DXY"),("ln_QQQ","D_ln_QQQ"),
                           ("ln_Oil","D_ln_Oil"),("ln_VIX","D_ln_VIX"),
                           ("ln_EPU","D_ln_EPU")]:
        if col_ln in dfw.columns:
            dfw[col_d] = dfw[col_ln].diff()

    avail = [f for f in factors if f in dfw.columns]
    if not avail:
        return {"r2": None, "note": "no factor columns found in weekly data"}

    dfw_p = dfw[period_start:period_end].copy()
    if "D_Gold" not in dfw_p.columns:
        return {"r2": None, "note": "D_Gold not available in weekly data"}

    # 13-week rolling aggregates
    roll = pd.DataFrame(index=dfw_p.index)
    roll["D_Gold_13w"] = dfw_p["D_Gold"].rolling(13).sum()
    for col in avail:
        if col not in dfw_p.columns:
            continue
        it = FACTOR_META[col][2]
        roll[col + "_13w"] = (dfw_p[col].rolling(13).mean()
                              if it == "level" else dfw_p[col].rolling(13).sum())

    avail_13w = [c for c in avail if c + "_13w" in roll.columns]
    cols_13w  = ["D_Gold_13w"] + [c + "_13w" for c in avail_13w]
    roll_clean = roll[cols_13w].dropna()

    if len(roll_clean) < 30:
        return {"r2": None, "n": len(roll_clean), "note": "insufficient data"}

    y = roll_clean["D_Gold_13w"]
    X = add_constant(roll_clean[[c + "_13w" for c in avail_13w]])
    m = OLS(y, X).fit(cov_type='HAC', cov_kwds={'maxlags': 13})

    full_r2 = m.rsquared
    pr2 = {}
    for col in avail_13w:
        rest_cols = [c + "_13w" for c in avail_13w if c != col]
        if rest_cols:
            red = OLS(y, add_constant(roll_clean[rest_cols])).fit(
                cov_type='HAC', cov_kwds={'maxlags': 13})
            pr2[col] = max(0.0, full_r2 - red.rsquared)
        else:
            pr2[col] = full_r2

    total_pr2 = sum(pr2.values()) or 1.0
    std_Y = float(y.std())
    std_X = roll_clean[[c + "_13w" for c in avail_13w]].std()

    factors_out = {}
    for col in avail_13w:
        meta = FACTOR_META[col]
        pname = col + "_13w"
        coef  = float(m.params[pname])
        pval  = float(m.pvalues[pname])
        sig   = "***" if pval < 0.01 else "**" if pval < 0.05 else "*" if pval < 0.1 else ""
        sb    = coef * float(std_X[pname]) / std_Y if std_Y > 0 else 0.0
        factors_out[col] = {
            "label":          meta[0],
            "unit":           meta[1],
            "input_type":     meta[2],
            "raw_col":        meta[3],
            "coef":           round(coef, 6),
            "pval":           round(pval, 4),
            "sig":            sig,
            "partial_r2":     round(pr2[col], 5),
            "partial_r2_pct": round(pr2[col] / total_pr2 * 100, 1),
            "std_beta":       round(sb, 4),
        }

    return {
        "label":     label,
        "n":         int(m.nobs),
        "r2":        round(m.rsquared, 4),
        "r2_adj":    round(m.rsquared_adj, 4),
        "rmse":      round(float(np.sqrt(m.mse_resid)), 6),
        "intercept": round(float(m.params["const"]), 6),
        "factors":   factors_out,
        "method":    "overlapping 13-week windows (weekly data), HAC Newey-West lag=13",
    }


# Factors available at daily frequency (excludes M2_Growth, EPU, CB which are monthly/quarterly)
DAILY_FACTORS = ["D_TIPS_10yr", "D_ln_DXY", "D_ln_VIX", "D_ln_QQQ", "D_ln_Oil", "D_Credit_Spread"]

def run_ols_daily(period_start: str, period_end=None, label: str = "") -> dict:
    """Daily first-differences OLS — 6 factors with daily data (no M2/EPU/CB)."""
    if not DATA_PATH_DAILY.exists():
        return {"r2": None, "note": "gold_factors_daily.csv not found"}

    dfd = pd.read_csv(DATA_PATH_DAILY, index_col=0, parse_dates=True)

    for col_raw, col_ln in [("DXY","ln_DXY"),("QQQ","ln_QQQ"),("Oil_WTI","ln_Oil"),
                             ("VIX","ln_VIX")]:
        if col_raw in dfd.columns:
            dfd[col_ln] = np.log(dfd[col_raw])

    if "Gold_Real" in dfd.columns:
        dfd["ln_Gold_Real"] = np.log(dfd["Gold_Real"])
        dfd["D_Gold"]       = dfd["ln_Gold_Real"].diff()

    dfd["D_TIPS_10yr"]     = dfd["TIPS_10yr"].diff()    if "TIPS_10yr"     in dfd.columns else np.nan
    dfd["D_Credit_Spread"] = dfd["Credit_Spread"].diff() if "Credit_Spread" in dfd.columns else np.nan
    dfd["D_ln_DXY"]        = dfd["ln_DXY"].diff()       if "ln_DXY"        in dfd.columns else np.nan
    dfd["D_ln_QQQ"]        = dfd["ln_QQQ"].diff()       if "ln_QQQ"        in dfd.columns else np.nan
    dfd["D_ln_Oil"]        = dfd["ln_Oil"].diff()       if "ln_Oil"        in dfd.columns else np.nan
    dfd["D_ln_VIX"]        = dfd["ln_VIX"].diff()       if "ln_VIX"        in dfd.columns else np.nan

    dfd_p = dfd[period_start:period_end].copy()
    avail  = [f for f in DAILY_FACTORS if f in dfd_p.columns]
    sub    = dfd_p[["D_Gold"] + avail].dropna()

    if len(sub) < 100:
        return {"r2": None, "n": len(sub), "note": "insufficient data"}

    y = sub["D_Gold"]
    X = add_constant(sub[avail])
    m = OLS(y, X).fit()

    return {
        "label":  label or f"Daily {period_start[:7]}–{(period_end or 'now')}",
        "n":      int(m.nobs),
        "r2":     round(m.rsquared, 4),
        "r2_adj": round(m.rsquared_adj, 4),
        "rmse":   round(float(np.sqrt(m.mse_resid)), 6),
        "factors": avail,
        "method": "daily first-differences OLS (6 factors: TIPS, DXY, VIX, QQQ, Oil, Credit)",
    }


# ── Run models ───────────────────────────────────────────────────────────
P1_START, P1_END = "2010-01-01", "2022-02-28"
P2_START         = "2022-03-01"
CB_START         = "2016-01-01"

data_all = df.copy()
p1_data  = data_all[P1_START:P1_END]
p2_data  = data_all[P2_START:]
p1_cb    = data_all[CB_START:P1_END]

print("=" * 70)
print("PERIOD 1 — QE Era — monthly changes (Jan 2010 – Feb 2022)")
print("=" * 70)
r1, m1_fit = run_ols(p1_data, BASE_FACTORS, "QE Era (Jan 2010 – Feb 2022)")
print(f"N={r1['n']}  R²={r1['r2']}  Adj R²={r1['r2_adj']}  RMSE={r1['rmse']:.5f}")
for col, info in r1["factors"].items():
    print(f"  {info['label']:<36} coef={info['coef']:>9.5f}  {info['sig']:<3}  "
          f"partial R²={info['partial_r2']*100:>5.2f}%  VIF={r1['diagnostics']['vif'].get(col,'?')}")
if r1["diagnostics"]["warnings"]:
    print("  DIAGNOSTICS:", " | ".join(r1["diagnostics"]["warnings"]))

print()
print("=" * 70)
print("PERIOD 2 — Dollar Era — monthly changes (Mar 2022 – Jun 2026)")
print("=" * 70)
r2, m2_fit = run_ols(p2_data, ALL_FACTORS_P2, "Dollar Weaponization Era (Mar 2022 – Jun 2026)")
print(f"N={r2['n']}  R²={r2['r2']}  Adj R²={r2['r2_adj']}  RMSE={r2['rmse']:.5f}")
for col, info in r2["factors"].items():
    print(f"  {info['label']:<36} coef={info['coef']:>9.5f}  {info['sig']:<3}  "
          f"partial R²={info['partial_r2']*100:>5.2f}%  VIF={r2['diagnostics']['vif'].get(col,'?')}")
if r2["diagnostics"]["warnings"]:
    print("  DIAGNOSTICS:", " | ".join(r2["diagnostics"]["warnings"]))

print()
print("=" * 70)
print("CB SUPPLEMENT — QE Era with CB (Jan 2016 – Feb 2022)")
print("=" * 70)
r1_cb, _ = run_ols(p1_cb, ALL_FACTORS_P1, "QE Era w/ CB (Jan 2016 – Feb 2022)")
print(f"N={r1_cb['n']}  R²={r1_cb['r2']}  Adj R²={r1_cb['r2_adj']}")
if "CB_Net_Purchases" in r1_cb["factors"]:
    info = r1_cb["factors"]["CB_Net_Purchases"]
    print(f"  CB: coef={info['coef']:.6f}  {info['sig']}  partial R²={info['partial_r2']*100:.2f}%")

print()
print("=" * 70)
print("3-MONTH NON-OVERLAPPING OLS (from monthly data)")
print("=" * 70)
r1_3m     = run_ols_3m_nonoverlap(p1_data, ALL_FACTORS_P1, "QE Era 3m non-overlap")
r2_3m     = run_ols_3m_nonoverlap(p2_data, ALL_FACTORS_P2, "Dollar Era 3m non-overlap")
r1cb_3m   = run_ols_3m_nonoverlap(p1_cb,   ALL_FACTORS_P1, "QE Era CB 3m non-overlap")
print(f"  QE Era:     N={r1_3m['n']}Q  R²={r1_3m['r2']}  Adj R²={r1_3m['r2_adj']}")
print(f"  Dollar Era: N={r2_3m['n']}Q  R²={r2_3m['r2']}  Adj R²={r2_3m['r2_adj']}")

print()
print("=" * 70)
print("STAGE 0 — BCOM ex-Gold  (strip ~12.7% gold self-weight from DJP)")
print("=" * 70)
if HAS_BCOM and DATA_PATH_WEEKLY.exists():
    _dfw_s0 = pd.read_csv(DATA_PATH_WEEKLY, index_col=0, parse_dates=True)
    if "DJP" in _dfw_s0.columns and "Gold" in _dfw_s0.columns:
        _D_ln_DJP_w  = np.log(_dfw_s0["DJP"].replace(0, np.nan)).diff()
        _D_ln_Gold_w = np.log(_dfw_s0["Gold"].replace(0, np.nan)).diff()
        _W_GOLD_W    = 0.127
        _dfw_s0["D_ln_BCOM_exgold"] = (_D_ln_DJP_w - _W_GOLD_W * _D_ln_Gold_w) / (1 - _W_GOLD_W)
        _dfw_s0.to_csv(DATA_PATH_WEEKLY)
        _djp_latest = float(_dfw_s0["DJP"].dropna().iloc[-1])
        print(f"  D_ln_BCOM_exgold computed (W_gold=12.7%)  Latest DJP=${_djp_latest:.2f}")
    else:
        print("  DJP not in weekly CSV — run fetch_data.py first")
        HAS_BCOM = False
else:
    if not HAS_BCOM:
        print("  Skipped — DJP not in monthly CSV (run fetch_data.py)")
    ALL_FACTORS_P1 = [f for f in ALL_FACTORS_P1 if f != "D_ln_BCOM_exgold"]
    ALL_FACTORS_P2 = [f for f in ALL_FACTORS_P2 if f != "D_ln_BCOM_exgold"]

print()
print("=" * 70)
print("STAGE 1 — ETF Orthogonalization (Dollar Era weekly, strip macro DNA)")
print("=" * 70)
stage1_result = {}
HAS_RESID = False
if HAS_ETF and DATA_PATH_WEEKLY.exists():
    _dfw_s1 = pd.read_csv(DATA_PATH_WEEKLY, index_col=0, parse_dates=True)
    for _cr, _cl in [("DXY","ln_DXY"), ("EPU","ln_EPU")]:
        if _cr in _dfw_s1.columns:
            _dfw_s1[_cl] = np.log(_dfw_s1[_cr])
    _dfw_s1["D_TIPS_10yr"] = _dfw_s1["TIPS_10yr"].diff() if "TIPS_10yr" in _dfw_s1 else np.nan
    if "ln_DXY" in _dfw_s1.columns:
        _dfw_s1["D_ln_DXY"] = _dfw_s1["ln_DXY"].diff()
    _s1_cols = ["ETF_Flow", "D_TIPS_10yr", "D_ln_DXY", "M2_Growth"]
    _s1_data = _dfw_s1[P2_START:][_s1_cols].dropna()
    if len(_s1_data) > 20:
        _X_s1 = add_constant(_s1_data[["D_TIPS_10yr", "D_ln_DXY", "M2_Growth"]])
        _m_s1 = OLS(_s1_data["ETF_Flow"], _X_s1).fit()
        stage1_result = {
            "intercept": round(float(_m_s1.params["const"]),        6),
            "coef_TIPS": round(float(_m_s1.params["D_TIPS_10yr"]),  6),
            "coef_DXY":  round(float(_m_s1.params["D_ln_DXY"]),     6),
            "coef_M2":   round(float(_m_s1.params["M2_Growth"]),    6),
            "r2":        round(float(_m_s1.rsquared),               4),
        }
        # Predict over full weekly history using available columns
        _Xfull = _dfw_s1[["D_TIPS_10yr","D_ln_DXY","M2_Growth"]].dropna()
        _Xfull_c = add_constant(_Xfull, has_constant="add")
        _fitted = _m_s1.predict(_Xfull_c)
        _dfw_s1.loc[_fitted.index, "ETF_Residual"] = (
            _dfw_s1.loc[_fitted.index, "ETF_Flow"] - _fitted)
        _dfw_s1.to_csv(DATA_PATH_WEEKLY)
        HAS_RESID = True
        print(f"  Stage 1 R²={stage1_result['r2']:.4f} | "
              f"TIPS coef={stage1_result['coef_TIPS']:+.4f}  "
              f"DXY coef={stage1_result['coef_DXY']:+.4f}  "
              f"M2 coef={stage1_result['coef_M2']:+.4f}")
        _cur_resid = float(_dfw_s1["ETF_Residual"].dropna().iloc[-1])
        _cur_etf   = float(_dfw_s1["ETF_Flow"].dropna().iloc[-1])
        print(f"  Latest ETF_Flow={_cur_etf:.1f}t  ETF_Residual={_cur_resid:.1f}t")
    else:
        print("  Skipped — insufficient Dollar Era weekly data")

if not HAS_RESID:
    ALL_FACTORS_P2 = [f for f in ALL_FACTORS_P2 if f != "ETF_Residual"]

print()
print("=" * 70)
print("STAGE 1a_QE — ETF Orthogonalization (QE Era weekly, era-specific coefs)")
print("=" * 70)
stage1_etf_qe_result = {}
HAS_RESID_QE = False
if HAS_ETF and DATA_PATH_WEEKLY.exists():
    _dfw_s1q = pd.read_csv(DATA_PATH_WEEKLY, index_col=0, parse_dates=True)
    _s1q_cols = ["ETF_Flow", "D_TIPS_10yr", "D_ln_DXY", "M2_Growth"]
    _s1q_data = _dfw_s1q[P1_START:P1_END][_s1q_cols].dropna()
    if len(_s1q_data) > 20:
        _X_s1q  = add_constant(_s1q_data[["D_TIPS_10yr", "D_ln_DXY", "M2_Growth"]])
        _m_s1q  = OLS(_s1q_data["ETF_Flow"], _X_s1q).fit()
        stage1_etf_qe_result = {
            "intercept": round(float(_m_s1q.params["const"]),       6),
            "coef_TIPS": round(float(_m_s1q.params["D_TIPS_10yr"]), 6),
            "coef_DXY":  round(float(_m_s1q.params["D_ln_DXY"]),    6),
            "coef_M2":   round(float(_m_s1q.params["M2_Growth"]),   6),
            "r2":        round(float(_m_s1q.rsquared),              4),
        }
        _Xq   = _dfw_s1q[P1_START:P1_END][["D_TIPS_10yr", "D_ln_DXY", "M2_Growth"]].dropna()
        _Xq_c = add_constant(_Xq, has_constant="add")
        _fitted_q = _m_s1q.predict(_Xq_c)
        _dfw_s1q.loc[_fitted_q.index, "ETF_Residual_QE"] = (
            _dfw_s1q.loc[_fitted_q.index, "ETF_Flow"] - _fitted_q)
        _dfw_s1q.to_csv(DATA_PATH_WEEKLY)
        HAS_RESID_QE = True
        print(f"  Stage 1a_QE R²={stage1_etf_qe_result['r2']:.4f} | "
              f"TIPS coef={stage1_etf_qe_result['coef_TIPS']:+.4f}  "
              f"DXY coef={stage1_etf_qe_result['coef_DXY']:+.4f}  "
              f"M2 coef={stage1_etf_qe_result['coef_M2']:+.4f}")
        _cur_resid_qe = float(_dfw_s1q["ETF_Residual_QE"].dropna().iloc[-1])
        print(f"  N={len(_s1q_data)} QE Era weekly obs; latest ETF_Residual_QE={_cur_resid_qe:.1f}t")
    else:
        print("  Skipped — insufficient QE Era weekly data")

if not HAS_RESID_QE:
    ALL_FACTORS_P1 = [f for f in ALL_FACTORS_P1 if f != "ETF_Residual_QE"]

print()
print("=" * 70)
print("STAGE 1b — Oil Orthogonalization (Dollar Era weekly, strip macro DNA)")
print("=" * 70)
stage1_oil_result = {}
HAS_OIL_RESID = False
if DATA_PATH_WEEKLY.exists():
    _dfw_s1b = pd.read_csv(DATA_PATH_WEEKLY, index_col=0, parse_dates=True)
    # Compute D_ln_Oil if not already in the CSV
    if "D_ln_Oil" not in _dfw_s1b.columns and "Oil_WTI" in _dfw_s1b.columns:
        _dfw_s1b["D_ln_Oil"] = np.log(_dfw_s1b["Oil_WTI"]).diff()
    # D_TIPS_10yr and D_ln_DXY already saved by Stage 1a; compute if missing
    if "D_TIPS_10yr" not in _dfw_s1b.columns and "TIPS_10yr" in _dfw_s1b.columns:
        _dfw_s1b["D_TIPS_10yr"] = _dfw_s1b["TIPS_10yr"].diff()
    if "D_ln_DXY" not in _dfw_s1b.columns and "DXY" in _dfw_s1b.columns:
        _dfw_s1b["D_ln_DXY"] = np.log(_dfw_s1b["DXY"]).diff()
    _s1b_cols = ["D_ln_Oil", "D_TIPS_10yr", "D_ln_DXY", "M2_Growth"]
    _s1b_data = _dfw_s1b[P2_START:][_s1b_cols].dropna()
    if len(_s1b_data) > 20:
        _X_s1b = add_constant(_s1b_data[["D_TIPS_10yr", "D_ln_DXY", "M2_Growth"]])
        _m_s1b = OLS(_s1b_data["D_ln_Oil"], _X_s1b).fit()
        stage1_oil_result = {
            "intercept": round(float(_m_s1b.params["const"]),        6),
            "coef_TIPS": round(float(_m_s1b.params["D_TIPS_10yr"]),  6),
            "coef_DXY":  round(float(_m_s1b.params["D_ln_DXY"]),     6),
            "coef_M2":   round(float(_m_s1b.params["M2_Growth"]),    6),
            "r2":        round(float(_m_s1b.rsquared),               4),
        }
        # Predict residuals over full weekly history
        _Xfull_b  = _dfw_s1b[["D_TIPS_10yr", "D_ln_DXY", "M2_Growth"]].dropna()
        _Xfull_bc = add_constant(_Xfull_b, has_constant="add")
        _fitted_b = _m_s1b.predict(_Xfull_bc)
        # Oil_Residual = D_ln_Oil - (macro-predicted component)
        _d_ln_oil_aligned = _dfw_s1b.loc[_fitted_b.index, "D_ln_Oil"]
        _dfw_s1b.loc[_fitted_b.index, "Oil_Residual"] = _d_ln_oil_aligned - _fitted_b
        _dfw_s1b.to_csv(DATA_PATH_WEEKLY)
        HAS_OIL_RESID = True
        print(f"  Stage 1b R²={stage1_oil_result['r2']:.4f} | "
              f"TIPS coef={stage1_oil_result['coef_TIPS']:+.6f}  "
              f"DXY coef={stage1_oil_result['coef_DXY']:+.6f}  "
              f"M2 coef={stage1_oil_result['coef_M2']:+.6f}")
        _cur_oil_wti = float(_dfw_s1b["Oil_WTI"].dropna().iloc[-1])
        _cur_oil_r   = float(_dfw_s1b["Oil_Residual"].dropna().iloc[-1])
        print(f"  Latest Oil_WTI=${_cur_oil_wti:.1f}  Oil_Residual={_cur_oil_r:+.4f}")
    else:
        print("  Skipped — insufficient Dollar Era weekly data")

if not HAS_OIL_RESID:
    ALL_FACTORS_P2 = [f for f in ALL_FACTORS_P2 if f != "Oil_Residual"]

print()
print("=" * 70)
print("3-MONTH OVERLAPPING OLS (weekly data, Newey-West HAC)")
print("=" * 70)
r1_3m_w = run_ols_3m_weekly_overlap(ALL_FACTORS_P1, "QE Era 3m weekly-overlap",
                                     P1_START, P1_END)
# Rename QE-era factor keys → Dollar-era keys so _combined_row finds them in the same display row
if "ETF_Residual_QE" in r1_3m_w.get("factors", {}):
    r1_3m_w["factors"]["ETF_Residual"] = r1_3m_w["factors"].pop("ETF_Residual_QE")
if "D_ln_Oil" in r1_3m_w.get("factors", {}):
    r1_3m_w["factors"]["Oil_Residual"] = r1_3m_w["factors"].pop("D_ln_Oil")
r2_3m_w = run_ols_3m_weekly_overlap(ALL_FACTORS_P2, "Dollar Era 3m weekly-overlap",
                                     P2_START)
print(f"  QE Era:     N={r1_3m_w.get('n','?')}w  R2={r1_3m_w.get('r2')}  Adj R2={r1_3m_w.get('r2_adj')}")
print(f"  Dollar Era: N={r2_3m_w.get('n','?')}w  R2={r2_3m_w.get('r2')}  Adj R2={r2_3m_w.get('r2_adj')}")
if r1_3m_w.get("note"): print(f"  Note: {r1_3m_w['note']}")

print()
print("=" * 70)
print("DAILY OLS (6 daily-frequency factors: TIPS, DXY, VIX, QQQ, Oil, Credit)")
print("=" * 70)
r1_daily = run_ols_daily(P1_START, P1_END, "QE Era daily")
r2_daily = run_ols_daily(P2_START, label="Dollar Era daily")
print(f"  QE Era:     N={r1_daily.get('n','?')}d  R2={r1_daily.get('r2')}  Adj R2={r1_daily.get('r2_adj')}")
print(f"  Dollar Era: N={r2_daily.get('n','?')}d  R2={r2_daily.get('r2')}  Adj R2={r2_daily.get('r2_adj')}")
if r1_daily.get("note"): print(f"  Note: {r1_daily['note']}")

# ── Fair Value: trailing model residuals ─────────────────────────────────
# Residuals from Period 2 model: how much did gold move beyond what macro factors explain?
# Positive cumulative residual = gold ran ahead of fundamentals (over-valued signal).
p2_resid = m2_fit.resid    # monthly residuals, DatetimeIndex

# Rolling 3m and 6m cumulative residuals (log units)
roll_3m = p2_resid.rolling(3).sum()
roll_6m = p2_resid.rolling(6).sum()

trailing_3m = float(p2_resid.tail(3).sum())
trailing_6m = float(p2_resid.tail(6).sum())
trailing_3m_pct = (math.exp(trailing_3m) - 1) * 100
trailing_6m_pct = (math.exp(trailing_6m) - 1) * 100

# Z-score: how unusual is today's 3m cumulative residual vs historical?
hist_3m_std  = float(roll_3m.dropna().std())
hist_3m_mean = float(roll_3m.dropna().mean())
z_score_3m   = (trailing_3m - hist_3m_mean) / hist_3m_std if hist_3m_std > 0 else 0.0

fair_value = {
    "trailing_3m_log":  round(trailing_3m, 5),
    "trailing_6m_log":  round(trailing_6m, 5),
    "trailing_3m_pct":  round(trailing_3m_pct, 2),
    "trailing_6m_pct":  round(trailing_6m_pct, 2),
    "z_score_3m":       round(z_score_3m, 2),
    "signal":           "above model" if trailing_3m > 0 else "below model",
    # model-implied current fair value: current price adjusted for residual gap
    # (if trailing_3m < 0, gold is below model → fair value is higher than current)
    "fair_value_log":   None,  # filled after current is built
    "description": (
        f"Gold moved {abs(round(trailing_3m_pct,1))}% "
        f"{'above' if trailing_3m > 0 else 'below'} Dollar Era model expectations "
        f"over the past 3 months (z={z_score_3m:+.2f})"
    ),
}
print(f"\nFair Value Signal (Dollar Era):")
print(f"  3m cumulative residual: {trailing_3m_pct:+.2f}%  z={z_score_3m:+.2f}")
print(f"  6m cumulative residual: {trailing_6m_pct:+.2f}%")
print(f"  Signal: {fair_value['signal']}")

# ── Current raw values ───────────────────────────────────────────────────
latest = df.ffill().iloc[-1]
current = {
    "date":            str(df.dropna(subset=["ln_Gold_Nominal"]).index[-1].date()),
    "Gold_Nominal":    round(float(df["Gold"].dropna().iloc[-1]), 2),
    "ln_Gold_Nominal": round(float(df["ln_Gold_Nominal"].dropna().iloc[-1]), 6),
    # Keep real and CPI for reference / fair value display only
    "Gold_Real":       round(float(df["Gold_Real"].dropna().iloc[-1]), 2),
    "CPI":             round(float(latest["CPI"]), 3),
}
RAW_COLS = {
    "TIPS_10yr":       "TIPS_10yr",
    "Breakeven":       "Breakeven",
    "DXY":             "DXY",
    "VIX":             "VIX",
    "QQQ":             "QQQ",
    "Oil_WTI":         "Oil_WTI",
    "Credit_Spread":   "Credit_Spread",
    "M2_Growth":       "M2_Growth",
    "EPU":             "EPU",
    "CB_Net_Purchases":"CB_Net_Purchases",
    "ETF_Flow":        "ETF_Flow",
    "Jewellery":       "Jewellery",
    "Technology":      "Technology",
    "Bar_Coin":        "Bar_Coin",
    "DJP":             "DJP",
}
for key, col in RAW_COLS.items():
    val = latest[col] if col in latest.index else None
    current[key] = round(float(val), 4) if val is not None and not np.isnan(float(val)) else None

# ETF_Residual current value (from weekly data if available)
if HAS_RESID:
    try:
        _dfw_r = pd.read_csv(DATA_PATH_WEEKLY, index_col=0, parse_dates=True)
        _resid_val = _dfw_r["ETF_Residual"].dropna().iloc[-1]
        current["ETF_Residual"] = round(float(_resid_val), 4)
    except Exception:
        current["ETF_Residual"] = 0.0
else:
    current["ETF_Residual"] = None

# model-implied fair value = where gold SHOULD be if residual gap closes
# trailing_3m < 0 means gold is below model → fair value > current price
fv_nominal = current["Gold_Nominal"] * math.exp(-trailing_3m)
fair_value["fair_value_price"] = round(fv_nominal, 0)
fair_value["fair_value_pct_from_current"] = round((fv_nominal / current["Gold_Nominal"] - 1) * 100, 2)

print(f"\nCurrent ({current['date']}):  Gold=${current['Gold_Nominal']:,.0f}  "
      f"TIPS={current['TIPS_10yr']}%  DXY={current['DXY']}  QQQ={current['QQQ']:,.1f}")
print(f"  Model fair value (residual catch-up): ${fv_nominal:,.0f}  "
      f"({fair_value['fair_value_pct_from_current']:+.1f}% from current)")

# ── Save ─────────────────────────────────────────────────────────────────
output = {
    "generated":    str(pd.Timestamp.now().date()),
    "period1":      r1,
    "period2":      r2,
    "period1_cb":   r1_cb,
    "period1_3m":   r1_3m,
    "period2_3m":   r2_3m,
    "period1cb_3m": r1cb_3m,
    "period1_3m_weekly":  r1_3m_w,
    "period2_3m_weekly":  r2_3m_w,
    "period1_daily":      r1_daily,
    "period2_daily":      r2_daily,
    "fair_value":   fair_value,
    "current":      current,
    "has_cb":       HAS_CB,
    "groups":       GROUPS,
    "factor_meta":  {k: {"label": v[0], "unit": v[1], "input_type": v[2], "raw_col": v[3]}
                     for k, v in FACTOR_META.items()},
    "stage1_etf":    stage1_result,         # Stage 1a P2: ETF_Flow ~ TIPS + DXY + M2 (Dollar Era)
    "stage1_etf_qe": stage1_etf_qe_result, # Stage 1a QE: ETF_Flow ~ TIPS + DXY + M2 (QE Era)
    "stage1_oil":    stage1_oil_result,     # Stage 1b: D_ln_Oil ~ TIPS + DXY + M2
}
with open(OUT_JSON, "w") as f:
    json.dump(output, f, indent=2)
print(f"\nSaved -> {OUT_JSON}")
