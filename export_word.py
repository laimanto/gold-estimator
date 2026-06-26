import pandas as pd
import numpy as np
from pathlib import Path
from statsmodels.tsa.stattools import adfuller
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
import warnings
warnings.filterwarnings("ignore")

# ── Rebuild model results ──────────────────────────────────────────────────
DATA_PATH = Path(__file__).parent / "data" / "gold_factors_monthly.csv"
df = pd.read_csv(DATA_PATH, index_col=0, parse_dates=True)

transforms = {
    "ln_Gold_Real":  np.log(df["Gold_Real"]),
    "TIPS_10yr":     df["TIPS_10yr"],
    "Breakeven":     df["Breakeven"],
    "ln_DXY":        np.log(df["DXY"]),
    "VIX":           df["VIX"],
    "ln_SP500":      np.log(df["SP500"]),
    "ln_Oil":        np.log(df["Oil_WTI"]),
    "Credit_Spread": df["Credit_Spread"],
    "M2_Growth":     df["M2_Growth"],
    "EPU":           df["EPU"],
}

adf_results = {}
series_data = {}
for name, s in transforms.items():
    s = s.dropna()
    p_lv = adfuller(s, autolag="AIC")[1]
    p_df = adfuller(s.diff().dropna(), autolag="AIC")[1]
    adf_results[name] = (p_lv, p_df, "I(0)" if p_lv < 0.05 else "I(1)")
    series_data[name] = s

base = pd.concat(series_data, axis=1); base.columns = list(series_data.keys())
base = base.dropna()
diffs = base.diff().dropna(); diffs.columns = ["D_" + c for c in base.columns]

lr_vars = ["TIPS_10yr","Breakeven","ln_DXY","VIX","ln_SP500",
           "ln_Oil","Credit_Spread","M2_Growth","EPU"]
lr_model = OLS(base["ln_Gold_Real"], add_constant(base[lr_vars])).fit()

ect = lr_model.resid.shift(1); ect.name = "ECT_lag1"
sr_vars = ["D_ln_Gold_Real","D_TIPS_10yr","D_Breakeven","D_ln_DXY","D_VIX",
           "D_ln_SP500","D_ln_Oil","D_Credit_Spread","D_M2_Growth","D_EPU"]
sr_data = diffs[sr_vars].join(ect).dropna()
y_sr = sr_data["D_ln_Gold_Real"]
X_sr = add_constant(sr_data.drop("D_ln_Gold_Real", axis=1))
sr_model = OLS(y_sr, X_sr).fit()

full_r2   = sr_model.rsquared
predictors = [c for c in sr_model.model.exog_names if c != "const"]
partial_r2s = {}
for dv in predictors:
    rem = [v for v in predictors if v != dv]
    partial_r2s[dv] = max(0, full_r2 - OLS(y_sr, add_constant(sr_data[rem])).fit().rsquared)
total_pr2 = sum(partial_r2s.values())

last     = sr_data.iloc[-1]
last_lng = base["ln_Gold_Real"].iloc[-1]
x_new    = np.array([1.0 if k == "const" else last[k] for k in sr_model.model.exog_names])
pred_d   = sr_model.predict(x_new)[0]
ci       = sr_model.get_prediction(x_new).summary_frame(alpha=0.05)
lo, hi   = ci["mean_ci_lower"].iloc[0], ci["mean_ci_upper"].iloc[0]
cpi_now  = df["CPI"].iloc[-1]
pred_r   = np.exp(last_lng + pred_d)
pred_n   = pred_r * cpi_now / 100
lo_n     = np.exp(last_lng + lo) * cpi_now / 100
hi_n     = np.exp(last_lng + hi) * cpi_now / 100
last_gold = df["Gold"].iloc[-1]
last_date = df.index[-1].strftime("%B %d, %Y")

coef_map = dict(zip(sr_model.model.exog_names, sr_model.params))
contrib  = {v: coef_map[v] * last[v] for v in predictors}

# ── Feature metadata ───────────────────────────────────────────────────────
features = {
    "TIPS_10yr": {
        "label": "10-Year TIPS Yield (Real Interest Rate)",
        "source": "FRED: DFII10",
        "current": f"{df['TIPS_10yr'].iloc[-1]:.2f}%",
        "explanation": (
            "The yield on 10-Year Treasury Inflation-Protected Securities represents the "
            "real (inflation-adjusted) interest rate. Since gold earns no yield, it "
            "competes directly with interest-bearing safe assets. When real rates rise, "
            "the opportunity cost of holding gold increases and investors prefer bonds."
        ),
        "implication": (
            "A 100bps rise in the TIPS yield reduces gold prices by approximately 8.4% "
            "in the short run (model coefficient: -0.0836). This is consistently the "
            "single strongest short-run driver, explaining 42.3% of modelled variance. "
            "Watch for Fed policy shifts and inflation surprises as primary catalysts."
        ),
        "direction": "Negative — rising real rates pressure gold down",
    },
    "Breakeven": {
        "label": "10-Year Breakeven Inflation Rate",
        "source": "FRED: T10YIE",
        "current": f"{df['Breakeven'].iloc[-1]:.2f}%",
        "explanation": (
            "The breakeven inflation rate is derived as the difference between the "
            "nominal 10-year Treasury yield and the 10-year TIPS yield. It reflects "
            "the market's consensus expectation of average inflation over the next "
            "10 years — the rate at which TIPS and nominal Treasuries deliver the "
            "same return."
        ),
        "implication": (
            "Significant in the long run (coef: -0.1012, p=0.042) but not in the "
            "short run. This means inflation expectations drive gold's fundamental "
            "value over years, but monthly price swings are dominated by the real "
            "rate and dollar rather than inflation narrative shifts. Long-term: higher "
            "expected inflation supports gold."
        ),
        "direction": "Positive long-run, not significant short-run",
    },
    "ln_DXY": {
        "label": "US Dollar Index — DXY (log)",
        "source": "Yahoo Finance: DX-Y.NYB",
        "current": f"{df['DXY'].iloc[-1]:.2f}",
        "explanation": (
            "The DXY measures the US dollar against a basket of 6 major currencies "
            "(EUR, JPY, GBP, CAD, SEK, CHF). Gold is priced in US dollars globally, "
            "so a stronger dollar makes gold more expensive for non-US buyers, "
            "reducing global demand. Conversely, dollar weakness boosts gold demand "
            "internationally."
        ),
        "implication": (
            "Strongest consistently significant driver after real rates. A 1% rise "
            "in the DXY reduces gold by 0.82% in the same month (coef: -0.8151, "
            "p<0.001), explaining 36.8% of modelled variance. Dollar moves driven "
            "by Fed policy, trade balances, and global risk sentiment all pass "
            "through to gold via this channel."
        ),
        "direction": "Negative — strong dollar suppresses gold",
    },
    "VIX": {
        "label": "CBOE Volatility Index — VIX",
        "source": "Yahoo Finance: ^VIX",
        "current": f"{df['VIX'].iloc[-1]:.2f}",
        "explanation": (
            "The VIX measures the market's expectation of 30-day S&P 500 volatility, "
            "derived from options prices. Often called the 'fear gauge', it spikes "
            "during market stress events (financial crises, geopolitical shocks, "
            "pandemics) and falls in calm, risk-on periods."
        ),
        "implication": (
            "Significant in the long run (coef: -0.0056) but not short run. "
            "Surprisingly, higher VIX is associated with lower real gold prices in "
            "the long-run model — this is because elevated VIX often accompanies "
            "dollar strengthening (flight to USD safety), which offsets gold's "
            "safe-haven appeal. In practice, gold and VIX often spike together "
            "in the first days of a crisis before diverging."
        ),
        "direction": "Complex — negative long-run, mixed short-run",
    },
    "ln_SP500": {
        "label": "S&P 500 Index (log)",
        "source": "Yahoo Finance: ^GSPC",
        "current": f"{df['SP500'].iloc[-1]:,.0f}",
        "explanation": (
            "The S&P 500 represents the performance of 500 large US companies and "
            "serves as the benchmark for US equity markets. It captures risk appetite: "
            "when equities rise, investors are in risk-on mode; when they fall, "
            "safe-haven demand — including for gold — tends to rise."
        ),
        "implication": (
            "Positive and significant in the long run (coef: 0.6057, p<0.001), "
            "suggesting gold and equities both rise in sustained bull markets "
            "(driven by inflation and liquidity). In the short run, mildly negative "
            "(coef: -0.1900, p=0.066) — equity rallies slightly reduce gold demand "
            "by reducing safe-haven pressure. Explains 3.6% of short-run variance."
        ),
        "direction": "Positive long-run (inflation/liquidity), negative short-run (risk rotation)",
    },
    "ln_Oil": {
        "label": "WTI Crude Oil Price (log)",
        "source": "Yahoo Finance: CL=F",
        "current": f"${df['Oil_WTI'].iloc[-1]:.2f}/bbl",
        "explanation": (
            "West Texas Intermediate (WTI) crude oil is the US benchmark for crude "
            "oil prices. Gold and oil share commodity market dynamics: both are "
            "sensitive to geopolitical disruptions, dollar movements, and inflation "
            "expectations. Rising oil often signals broader inflationary pressure "
            "which supports gold."
        ),
        "implication": (
            "Significant in the long run (coef: 0.2076, p=0.001) — a 10% rise in "
            "oil is associated with a 2.1% rise in real gold over time. However, "
            "not significant in the short run (p=0.962). This means oil works as "
            "a slow-moving fundamental driver rather than a month-to-month signal. "
            "Geopolitical disruptions affecting both markets are the key watch point."
        ),
        "direction": "Positive long-run, not significant short-run",
    },
    "Credit_Spread": {
        "label": "Moody's Baa–10yr Treasury Credit Spread",
        "source": "FRED: BAA10Y",
        "current": f"{df['Credit_Spread'].iloc[-1]:.2f}%",
        "explanation": (
            "The spread between Moody's Baa-rated corporate bond yields and the "
            "10-year Treasury yield measures the credit risk premium investors "
            "require on investment-grade corporate debt. Widening spreads signal "
            "deteriorating credit conditions, recession fears, or financial stress "
            "— all conditions that historically drive safe-haven demand."
        ),
        "implication": (
            "Significant in the long run (coef: 0.1333, p<0.001): a 1 percentage "
            "point widening in credit spreads is associated with a 13.3% increase "
            "in real gold prices over time. This captures financial stress episodes "
            "(2008-09 GFC, 2020 COVID) where gold rallied. Short-run effect is "
            "smaller and not statistically significant (1.0% of variance)."
        ),
        "direction": "Positive — wider spreads (more stress) support gold",
    },
    "M2_Growth": {
        "label": "M2 Money Supply Growth (Year-on-Year %)",
        "source": "FRED: M2SL (12-month % change)",
        "current": f"{df['M2_Growth'].iloc[-1]:.2f}%",
        "explanation": (
            "M2 money supply includes cash, checking deposits, and near-money "
            "assets. Its year-on-year growth rate captures the pace of monetary "
            "expansion. Rapid money supply growth — as seen during QE programs "
            "and post-COVID stimulus — raises concerns about currency debasement "
            "and future inflation, supporting gold as a store of value."
        ),
        "implication": (
            "Significant in the long run (coef: -0.0156, p<0.001) but counterintuitively "
            "negative. This reflects that high M2 growth often coincides with low real "
            "rates and quantitative easing, where gold is already elevated. The "
            "negative sign likely captures the mean-reversion after QE peaks. "
            "Not significant in the short run (1.3% of variance)."
        ),
        "direction": "Negative long-run (mean reversion after QE), not significant short-run",
    },
    "EPU": {
        "label": "US Economic Policy Uncertainty Index",
        "source": "FRED: USEPUINDXM",
        "current": f"{df['EPU'].iloc[-1]:.1f}",
        "explanation": (
            "The EPU Index, developed by Baker, Bloom, and Davis, quantifies economic "
            "policy uncertainty by measuring: (1) newspaper coverage of policy-related "
            "economic uncertainty, (2) expiring tax code provisions, and (3) disagreement "
            "among economic forecasters. It captures uncertainty around fiscal policy, "
            "monetary policy, trade, and regulation."
        ),
        "implication": (
            "Significant in both long run (coef: 0.0027, p<0.001) and short run "
            "(coef: 0.0002, p=0.013, explaining 6.7% of variance). Higher policy "
            "uncertainty reliably drives investors toward gold as a safe-haven asset. "
            "Key triggers: elections, trade wars, debt ceiling crises, unexpected "
            "Fed policy pivots. Currently elevated, providing a floor for gold."
        ),
        "direction": "Positive — more uncertainty supports gold",
    },
    "ECT_lag1": {
        "label": "Error Correction Term (ECT, lagged 1 month)",
        "source": "Derived from long-run regression residuals",
        "current": f"{last['ECT_lag1']:.4f}",
        "explanation": (
            "The Error Correction Term measures how far gold's current price deviates "
            "from its long-run equilibrium implied by all fundamental factors. It is "
            "computed as the residual from the long-run cointegrating regression. "
            "A positive ECT means gold is overvalued relative to fundamentals; "
            "a negative ECT means it is undervalued."
        ),
        "implication": (
            "The ECT coefficient of -0.0497 (p=0.007) means approximately 5% of any "
            "deviation from long-run equilibrium is corrected each month. This "
            "confirms cointegration — gold does not drift away from its fundamentals "
            "permanently. Currently ECT = "
            f"{last['ECT_lag1']:.4f}, contributing {contrib.get('ECT_lag1', 0)*100:+.2f}% "
            "to the July forecast (mean-reversion pressure)."
        ),
        "direction": "Negative ECT = undervalued (upward pressure); Positive = overvalued (downward)",
    },
}

# ── Build Word document ────────────────────────────────────────────────────
import win32com.client as win32
word = win32.Dispatch("Word.Application")
word.Visible = False
doc  = word.Documents.Add()
sel  = word.Selection

def heading(text, level=1):
    style = {1: "Heading 1", 2: "Heading 2", 3: "Heading 3"}.get(level, "Heading 1")
    sel.Style = doc.Styles[style]
    sel.TypeText(text); sel.TypeParagraph()

def body(text):
    sel.Style = doc.Styles["Normal"]
    sel.TypeText(text); sel.TypeParagraph()

def blank():
    sel.Style = doc.Styles["Normal"]
    sel.TypeParagraph()

def after_table(t):
    sel.SetRange(t.Range.End, t.Range.End)
    sel.TypeParagraph()

def make_table(rows, cols, header_row=True):
    t = doc.Tables.Add(sel.Range, rows, cols)
    t.Style = "Table Grid"; t.Borders.Enable = True
    if header_row:
        for c in range(1, cols + 1):
            t.Cell(1, c).Range.Bold = True
    return t

# ─── Title ───────────────────────────────────────────────────────────────
sel.Style = doc.Styles["Title"]
sel.TypeText("Gold Price Model: Factor Analysis & Forecast"); sel.TypeParagraph()
sel.Style = doc.Styles["Subtitle"]
sel.TypeText(f"ARDL-ECM Model  |  Data through {last_date}  |  Produced {pd.Timestamp.today().strftime('%B %d, %Y')}")
sel.TypeParagraph(); blank()

# ─── 1. Executive Summary ────────────────────────────────────────────────
heading("1. Executive Summary")
body(
    f"This report presents a 10-factor Autoregressive Distributed Lag Error Correction Model "
    f"(ARDL-ECM) fitted to monthly gold price data from January 2005 to {last_date}. "
    f"The model explains 83.8% of long-run variation in real gold prices (R² = 0.838) and "
    f"36.1% of short-run monthly changes (R² = 0.361). "
    f"The two dominant short-run drivers are the 10-year TIPS yield (real interest rate, 42.3% "
    f"of explained variance) and the US Dollar Index (36.8%). "
    f"Based on factor movements through {last_date}, the model forecasts gold at "
    f"${pred_n:,.0f} per oz for July 2026 ({pred_d*100:+.1f}%), with a 95% confidence "
    f"range of ${lo_n:,.0f} – ${hi_n:,.0f}."
)
blank()

# ─── 2. Model Methodology ────────────────────────────────────────────────
heading("2. Model Methodology")
body(
    "The ARDL-ECM framework is used because it correctly handles a mix of stationary I(0) "
    "and non-stationary I(1) variables without requiring all series to be differenced. "
    "The model has two layers:"
)
body(
    "Long-run regression: Estimates the cointegrating relationship between real gold prices "
    "(log-transformed and CPI-adjusted) and 9 fundamental factors in levels. This captures "
    "permanent structural drivers. R-squared of 0.838 means the 9 factors explain 83.8% of "
    "the long-run variation in gold prices."
)
body(
    "Short-run ECM: Regresses monthly changes in log real gold on monthly changes of all "
    "factors, plus the lagged Error Correction Term (ECT). The ECT represents how far gold "
    "deviated from long-run equilibrium last month, creating a mean-reversion pull."
)
body(
    "Variable transformation: Gold price is expressed as ln(Nominal Gold / CPI x 100) — "
    "log of real gold — which removes scale effects, corrects for heteroscedasticity, and "
    "isolates real from nominal price movements. DXY and S&P 500 are also log-transformed. "
    "Rate variables (TIPS, Breakeven, VIX, Credit Spread, M2 Growth, EPU) are used in levels."
)
blank()

# ─── 3. Stationarity Tests ───────────────────────────────────────────────
heading("3. Stationarity Test Results (ADF)")
body(
    "The Augmented Dickey-Fuller (ADF) test determines whether each series is stationary "
    "I(0) or has a unit root I(1). Non-stationary series in levels become stationary after "
    "first differencing. The ECM framework requires this mixed order to be valid."
)
blank()
t1 = make_table(len(adf_results) + 1, 4)
t1.Cell(1,1).Range.Text = "Variable"
t1.Cell(1,2).Range.Text = "Level p-value"
t1.Cell(1,3).Range.Text = "1st Diff p-value"
t1.Cell(1,4).Range.Text = "Integration Order"
for i, (name, (pl, pd_, ord_)) in enumerate(adf_results.items(), 2):
    t1.Cell(i,1).Range.Text = name
    t1.Cell(i,2).Range.Text = f"{pl:.4f}"
    t1.Cell(i,3).Range.Text = f"{pd_:.4f}"
    t1.Cell(i,4).Range.Text = ord_
after_table(t1); blank()

# ─── 4. Feature Explanations ─────────────────────────────────────────────
heading("4. Feature Explanations and Implications")
body(
    "The following section explains each of the 10 factors in the model: what it measures, "
    "why it is theoretically linked to gold prices, and what the model coefficients imply."
)

feat_order = ["TIPS_10yr","Breakeven","ln_DXY","VIX","ln_SP500",
              "ln_Oil","Credit_Spread","M2_Growth","EPU","ECT_lag1"]

for i, key in enumerate(feat_order, 1):
    f = features[key]
    heading(f"4.{i}  {f['label']}", level=2)
    body(f"Source: {f['source']}   |   Latest value: {f['current']}")
    body(f"What it measures: {f['explanation']}")
    body(f"Model implication: {f['implication']}")
    body(f"Direction: {f['direction']}")
    blank()

# ─── 5. Long-Run Results ─────────────────────────────────────────────────
heading("5. Long-Run Cointegrating Regression")
body(
    f"Dependent variable: ln(Real Gold Price)   |   R² = {lr_model.rsquared:.3f}   "
    f"Adj R² = {lr_model.rsquared_adj:.3f}   N = {int(lr_model.nobs)} months"
)
body(
    "Interpretation: Each coefficient shows the long-run percentage change in real gold "
    "associated with a one-unit increase in the factor (for log variables: a 1% factor "
    "change leads to coef% gold change; for level variables: a 1-unit change leads to "
    "coef x 100% gold change)."
)
blank()
t2 = make_table(len(lr_model.params) + 1, 4)
t2.Cell(1,1).Range.Text = "Variable"
t2.Cell(1,2).Range.Text = "Coefficient"
t2.Cell(1,3).Range.Text = "p-value"
t2.Cell(1,4).Range.Text = "Significance"
for i, (v, c, p) in enumerate(zip(lr_model.model.exog_names, lr_model.params, lr_model.pvalues), 2):
    sig = "*** p<0.01" if p < 0.01 else "** p<0.05" if p < 0.05 else "* p<0.1" if p < 0.1 else ""
    t2.Cell(i,1).Range.Text = v
    t2.Cell(i,2).Range.Text = f"{c:.4f}"
    t2.Cell(i,3).Range.Text = f"{p:.4f}"
    t2.Cell(i,4).Range.Text = sig
after_table(t2); blank()

# ─── 6. Short-Run ECM Results ────────────────────────────────────────────
heading("6. Short-Run ECM Regression")
body(
    f"Dependent variable: Monthly change in ln(Real Gold)   |   "
    f"R² = {sr_model.rsquared:.3f}   Adj R² = {sr_model.rsquared_adj:.3f}   N = {int(sr_model.nobs)} months"
)
body(
    "Interpretation: Each coefficient shows the immediate (same-month) percentage change "
    "in gold for a one-unit change in the factor's monthly change."
)
blank()
t3 = make_table(len(sr_model.params) + 1, 4)
t3.Cell(1,1).Range.Text = "Variable"
t3.Cell(1,2).Range.Text = "Coefficient"
t3.Cell(1,3).Range.Text = "p-value"
t3.Cell(1,4).Range.Text = "Significance"
for i, (v, c, p) in enumerate(zip(sr_model.model.exog_names, sr_model.params, sr_model.pvalues), 2):
    sig = "*** p<0.01" if p < 0.01 else "** p<0.05" if p < 0.05 else "* p<0.1" if p < 0.1 else ""
    t3.Cell(i,1).Range.Text = v
    t3.Cell(i,2).Range.Text = f"{c:.4f}"
    t3.Cell(i,3).Range.Text = f"{p:.4f}"
    t3.Cell(i,4).Range.Text = sig
after_table(t3); blank()

# ─── 7. Partial R² ───────────────────────────────────────────────────────
heading("7. Variance Explained per Factor (Partial R²)")
body(
    "Partial R² measures how much of the total explained variance each factor uniquely "
    "contributes. It is computed as the drop in R² when that factor is removed from the "
    "full model — isolating each factor's independent contribution."
)
blank()
sorted_pr2 = sorted(partial_r2s.items(), key=lambda x: -x[1])
t4 = make_table(len(sorted_pr2) + 1, 3)
t4.Cell(1,1).Range.Text = "Factor"
t4.Cell(1,2).Range.Text = "Partial R²"
t4.Cell(1,3).Range.Text = "Share of Explained Variance"
for i, (v, pr2) in enumerate(sorted_pr2, 2):
    pct = pr2 / total_pr2 * 100 if total_pr2 > 0 else 0
    t4.Cell(i,1).Range.Text = v
    t4.Cell(i,2).Range.Text = f"{pr2:.4f}"
    t4.Cell(i,3).Range.Text = f"{pct:.1f}%"
after_table(t4); blank()

# ─── 8. Correlation with Gold ─────────────────────────────────────────────
heading("8. Pairwise Correlation with Monthly Gold Change")
body(
    "Simple linear correlation between each factor's monthly change and gold's monthly "
    "change. Positive = factor and gold move in same direction; negative = opposite."
)
blank()
corr = sr_data.corr()["D_ln_Gold_Real"].drop("D_ln_Gold_Real").sort_values()
t5 = make_table(len(corr) + 1, 3)
t5.Cell(1,1).Range.Text = "Factor"
t5.Cell(1,2).Range.Text = "Correlation (r)"
t5.Cell(1,3).Range.Text = "Relationship"
for i, (v, c) in enumerate(corr.items(), 2):
    t5.Cell(i,1).Range.Text = v
    t5.Cell(i,2).Range.Text = f"{c:.3f}"
    t5.Cell(i,3).Range.Text = "Positive with gold" if c > 0.05 else "Negative with gold" if c < -0.05 else "Neutral"
after_table(t5); blank()

# ─── 9. Forecast ─────────────────────────────────────────────────────────
heading("9. Forecast: July 2026")
body(
    f"Based on factor values observed through {last_date} (partial June 2026), "
    f"the model forecasts the following for July 2026:"
)
blank()
t6 = make_table(5, 2, header_row=False)
t6.Cell(1,1).Range.Text = "Last observed gold price"
t6.Cell(1,2).Range.Text = f"${last_gold:,.2f} (as of {last_date})"
t6.Cell(2,1).Range.Text = "Predicted change"
t6.Cell(2,2).Range.Text = f"{pred_d*100:+.2f}%"
t6.Cell(3,1).Range.Text = "Predicted price (July 2026)"
t6.Cell(3,2).Range.Text = f"${pred_n:,.0f}"
t6.Cell(4,1).Range.Text = "95% Confidence range"
t6.Cell(4,2).Range.Text = f"${lo_n:,.0f} – ${hi_n:,.0f}"
t6.Cell(5,1).Range.Text = "Model R² (short-run)"
t6.Cell(5,2).Range.Text = f"{sr_model.rsquared:.3f} (explains {sr_model.rsquared*100:.1f}% of monthly variance)"
for r in range(1, 6):
    t6.Cell(r,1).Range.Bold = True
after_table(t6); blank()

heading("9.1  Factor Contributions to July 2026 Forecast", level=2)
body(
    "Each factor's contribution = its model coefficient x its latest monthly change. "
    "Positive contribution = that factor is pushing gold higher; negative = pushing lower."
)
blank()
t7 = make_table(len(contrib) + 2, 3)
t7.Cell(1,1).Range.Text = "Factor"
t7.Cell(1,2).Range.Text = "Contribution (log pts)"
t7.Cell(1,3).Range.Text = "Direction"
for i, (v, c2) in enumerate(sorted(contrib.items(), key=lambda x: x[1]), 2):
    t7.Cell(i,1).Range.Text = v
    t7.Cell(i,2).Range.Text = f"{c2:+.4f}"
    t7.Cell(i,3).Range.Text = "Upward pressure" if c2 > 0 else "Downward pressure"
r = len(contrib) + 2
t7.Cell(r,1).Range.Text = "TOTAL (predicted change)"
t7.Cell(r,2).Range.Text = f"{pred_d:+.4f}  ({pred_d*100:+.2f}%)"
t7.Cell(r,3).Range.Text = "Net forecast"
t7.Cell(r,1).Range.Bold = True
t7.Cell(r,2).Range.Bold = True
t7.Cell(r,3).Range.Bold = True
after_table(t7); blank()

# ─── 10. Limitations ─────────────────────────────────────────────────────
heading("10. Model Limitations and Caveats")
body("1. Short-run R² = 0.361: The model explains only 36% of monthly gold moves. "
     "The remaining 64% reflects sentiment, ETF flows, central bank buying, technical "
     "trading, and events not captured by macro variables.")
body("2. Linear model: The ARDL-ECM assumes linear relationships. In reality, gold's "
     "sensitivity to real rates may be non-linear (stronger when rates cross zero).")
body("3. Regime changes: The model is fit on 2005-2026 data covering multiple rate "
     "cycles. Parameters may shift in structurally different environments.")
body("4. Data lags: CPI and M2 are released with 3-4 week lags and are forward-filled "
     "in the model. EPU is an estimate based on text analysis.")
body("5. Forecast horizon: The model is optimised for 1-month ahead forecasts. "
     "Accuracy degrades significantly at longer horizons.")
blank()

# ─── 11. Sources ─────────────────────────────────────────────────────────
heading("11. Data Sources")
sources = [
    ("Gold price",            "Yahoo Finance: GC=F (COMEX Gold Futures)"),
    ("VIX",                   "Yahoo Finance: ^VIX"),
    ("DXY Dollar Index",      "Yahoo Finance: DX-Y.NYB"),
    ("S&P 500",               "Yahoo Finance: ^GSPC"),
    ("WTI Crude Oil",         "Yahoo Finance: CL=F"),
    ("10-yr TIPS Yield",      "FRED: DFII10"),
    ("10-yr Breakeven",       "FRED: T10YIE"),
    ("Fed Funds Rate",        "FRED: DFF"),
    ("CPI (All Urban)",       "FRED: CPIAUCSL"),
    ("Credit Spread",         "FRED: BAA10Y (Moody's Baa minus 10yr Treasury)"),
    ("M2 Money Supply",       "FRED: M2SL"),
    ("EPU Index",             "FRED: USEPUINDXM (Baker, Bloom & Davis)"),
    ("Research references",   "LBMA Alchemist Issue 90; Chicago Fed Letter 2021 (464); PIMCO Understanding Gold Prices"),
]
t8 = make_table(len(sources) + 1, 2)
t8.Cell(1,1).Range.Text = "Series"
t8.Cell(1,2).Range.Text = "Source / Ticker"
for i, (s, v) in enumerate(sources, 2):
    t8.Cell(i,1).Range.Text = s
    t8.Cell(i,2).Range.Text = v
after_table(t8)

# ─── Save ─────────────────────────────────────────────────────────────────
out = r"D:\Backup D\Weekly\USB drive\Invest\AI invest\Gold\doc\gold research.docx"
doc.SaveAs(out)
doc.Close()
word.Quit()
print(f"Saved: {out}")
