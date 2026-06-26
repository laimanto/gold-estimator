import pandas as pd
import numpy as np
from pathlib import Path
from statsmodels.tsa.stattools import adfuller
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
import warnings
warnings.filterwarnings("ignore")

DATA_PATH = Path(__file__).parent / "data" / "gold_factors_monthly.csv"
df = pd.read_csv(DATA_PATH, index_col=0, parse_dates=True)

print("=" * 70)
print("STEP 1 — STATIONARITY (ADF Test)")
print("=" * 70)
print(f"  {'Variable':<20} {'Level p':>10} {'Diff p':>10} {'Order'}")
print("  " + "-" * 52)

transforms = {
    "ln_Gold_Real":  np.log(df["Gold_Real"]),
    "TIPS_10yr":     df["TIPS_10yr"],
    "Breakeven":     df["Breakeven"],
    "ln_DXY":        np.log(df["DXY"]),
    "VIX":           df["VIX"],
    "Fed_Rate":      df["Fed_Rate"],
    "ln_SP500":      np.log(df["SP500"]),
    "ln_Oil":        np.log(df["Oil_WTI"]),
    "Credit_Spread":  df["Credit_Spread"],
    "M2_Growth":     df["M2_Growth"],
    "EPU":           df["EPU"],
}

series_data = {}
for name, s in transforms.items():
    s = s.dropna()
    p_level = adfuller(s, autolag="AIC")[1]
    p_diff  = adfuller(s.diff().dropna(), autolag="AIC")[1]
    order   = "I(0)" if p_level < 0.05 else "I(1)"
    series_data[name] = s
    print(f"  {name:<20} {p_level:>10.4f} {p_diff:>10.4f}  {order}")

print()
print("=" * 70)
print("STEP 2 — LONG-RUN COINTEGRATING REGRESSION (levels)")
print("=" * 70)

base = pd.concat(series_data, axis=1)
base.columns = list(series_data.keys())
base = base.dropna()
print(f"\n  Dataset: {len(base)} monthly rows  ({base.index[0].date()} to {base.index[-1].date()})")

diffs = base.diff().dropna()
diffs.columns = ["D_" + c for c in base.columns]

# Long-run: all significant level variables
lr_vars = ["TIPS_10yr", "Breakeven", "ln_DXY", "VIX",
           "ln_SP500", "ln_Oil", "Credit_Spread", "M2_Growth", "EPU"]
X_lr = add_constant(base[lr_vars])
y_lr = base["ln_Gold_Real"]
lr_model = OLS(y_lr, X_lr).fit()

print(f"\n  R² = {lr_model.rsquared:.3f}   Adj R² = {lr_model.rsquared_adj:.3f}   N = {int(lr_model.nobs)}")
print(f"\n  {'Variable':<20} {'Coef':>10} {'p-value':>10} {'Sig'}")
print("  " + "-" * 50)
for var, coef, pval in zip(lr_model.model.exog_names, lr_model.params, lr_model.pvalues):
    sig = "***" if pval < 0.01 else "**" if pval < 0.05 else "*" if pval < 0.1 else ""
    print(f"  {var:<20} {coef:>10.4f} {pval:>10.4f}  {sig}")

print()
print("=" * 70)
print("STEP 3 — SHORT-RUN ECM (first differences + ECT)")
print("=" * 70)

ect = lr_model.resid.shift(1)
ect.name = "ECT_lag1"

sr_vars = ["D_ln_Gold_Real", "D_TIPS_10yr", "D_Breakeven", "D_ln_DXY",
           "D_VIX", "D_ln_SP500", "D_ln_Oil", "D_Credit_Spread",
           "D_M2_Growth", "D_EPU"]
sr_data = diffs[sr_vars].join(ect).dropna()

X_sr = add_constant(sr_data.drop("D_ln_Gold_Real", axis=1))
y_sr = sr_data["D_ln_Gold_Real"]
sr_model = OLS(y_sr, X_sr).fit()

print(f"\n  R² = {sr_model.rsquared:.3f}   Adj R² = {sr_model.rsquared_adj:.3f}   N = {int(sr_model.nobs)}")
print(f"\n  {'Variable':<20} {'Coef':>10} {'p-value':>10} {'Sig'}")
print("  " + "-" * 50)
for var, coef, pval in zip(sr_model.model.exog_names, sr_model.params, sr_model.pvalues):
    sig = "***" if pval < 0.01 else "**" if pval < 0.05 else "*" if pval < 0.1 else ""
    print(f"  {var:<20} {coef:>10.4f} {pval:>10.4f}  {sig}")

print()
print("=" * 70)
print("STEP 4 — PARTIAL R² (variance explained per factor)")
print("=" * 70)

full_r2  = sr_model.rsquared
predictors = [c for c in sr_model.model.exog_names if c != "const"]

partial_r2s = {}
for drop_var in predictors:
    remaining = [v for v in predictors if v != drop_var]
    sub = OLS(y_sr, add_constant(sr_data[remaining])).fit()
    partial_r2s[drop_var] = max(0, full_r2 - sub.rsquared)

total_pr2 = sum(partial_r2s.values())
print(f"\n  {'Factor':<20} {'Partial R²':>12} {'Share':>8}")
print("  " + "-" * 44)
for var, pr2 in sorted(partial_r2s.items(), key=lambda x: -x[1]):
    pct = pr2 / total_pr2 * 100 if total_pr2 > 0 else 0
    print(f"  {var:<20} {pr2:>12.4f} {pct:>7.1f}%")

print()
print("=" * 70)
print("STEP 5 — CORRELATION MATRIX (factors vs gold monthly change)")
print("=" * 70)

corr_df = sr_data.copy()
corr_with_gold = corr_df.corr()["D_ln_Gold_Real"].drop("D_ln_Gold_Real").sort_values()
print()
for var, c in corr_with_gold.items():
    bar = "#" * int(abs(c) * 30)
    direction = "(+)" if c > 0 else "(-)"
    print(f"  {var:<20} {c:>7.3f}  {direction} {bar}")

print()
print("=" * 70)
print("STEP 6 — FORECAST (1-month ahead, June 2026)")
print("=" * 70)

last      = sr_data.iloc[-1]
last_ln_g = base["ln_Gold_Real"].iloc[-1]

x_new  = np.array([last.get(k, 1.0) if k == "const" else last[k]
                   for k in sr_model.model.exog_names])
x_new[sr_model.model.exog_names.index("const")] = 1.0

pred_diff = sr_model.predict(x_new)[0]
pred_ci   = sr_model.get_prediction(x_new).summary_frame(alpha=0.05)
lo = pred_ci["mean_ci_lower"].iloc[0]
hi = pred_ci["mean_ci_upper"].iloc[0]

current_cpi = df["CPI"].iloc[-1]
pred_real   = np.exp(last_ln_g + pred_diff)
pred_nom    = pred_real * current_cpi / 100

print(f"\n  Last observed (May 2026):  ${df['Gold'].iloc[-1]:>8,.2f}  (nominal)")
print(f"  Predicted (June 2026):     ${pred_nom:>8,.2f}  ({pred_diff*100:+.2f}%)")
print(f"  95% confidence range:      [${np.exp(last_ln_g+lo)*current_cpi/100:>7,.0f}, "
      f"${np.exp(last_ln_g+hi)*current_cpi/100:>7,.0f}]")

# Factor contributions to this specific forecast
print(f"\n  Factor contributions to June forecast:")
print(f"  {'Factor':<20} {'Contribution':>14}")
print("  " + "-" * 38)
coef_map = dict(zip(sr_model.model.exog_names, sr_model.params))
for var in predictors:
    contrib = coef_map[var] * last[var]
    direction = "(up)" if contrib > 0 else "(dn)"
    print(f"  {var:<20} {contrib:>+12.4f}  {direction}")

print("\n  Sig codes: *** p<0.01  ** p<0.05  * p<0.1")
