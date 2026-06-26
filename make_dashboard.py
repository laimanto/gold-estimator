"""Generate dashboard.html — interactive Plotly dashboard."""
import os, warnings
warnings.filterwarnings('ignore')

import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import pearsonr
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

# ── Data ───────────────────────────────────────────────────────────────────────
START = '2000-01-01'
END   = datetime.today().strftime('%Y-%m-%d')

print('Downloading data...')
# Download daily then resample to W-FRI so all series share identical Friday dates
sp_raw  = yf.download('^GSPC', start=START, end=END, interval='1d', progress=False)
gold_raw= yf.download('GC=F',  start=START, end=END, interval='1d', progress=False)
irx_raw = yf.download('^IRX',  start=START, end=END, interval='1d', progress=False)

def to_weekly(raw, name):
    s = raw['Close'].squeeze()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s.resample('W-FRI').last().rename(name)

sp500      = to_weekly(sp_raw,  'SP500')
gold       = to_weekly(gold_raw,'Gold')
fed_weekly = to_weekly(irx_raw, 'FedRate').to_frame()

df = pd.concat([sp500, gold, fed_weekly], axis=1)
df.ffill(inplace=True)
df.dropna(inplace=True)
print(f'Merged: {len(df):,} rows  {df.index[0].date()} to {df.index[-1].date()}')

# ── Returns + correlations ─────────────────────────────────────────────────────
# pct_change for prices; diff() for rate (pct_change breaks near-zero yields)
returns = pd.DataFrame({
    'SP500':   df['SP500'].pct_change(),
    'Gold':    df['Gold'].pct_change(),
    'FedRate': df['FedRate'].diff(),   # absolute change in %-pts per week
})
returns.dropna(inplace=True)
WINDOW  = 52
roll_fg = returns['FedRate'].rolling(WINDOW).corr(returns['Gold'])    # Fed-rate-change vs gold return
roll_fs = returns['FedRate'].rolling(WINDOW).corr(returns['SP500'])   # Fed-rate-change vs equity return
roll_gs = returns['Gold'].rolling(WINDOW).corr(returns['SP500'])      # gold return vs equity return

PAIRS = [
    ('FedRate', 'Gold',  'Fed ↔ Gold'),
    ('FedRate', 'SP500', 'Fed ↔ S&P 500'),
    ('Gold',    'SP500', 'Gold ↔ S&P 500'),
]
CORR_PERIODS = {
    'Bubble (2000–2009)':                   ('2000-01-01', '2009-12-31'),
    'QE ∞ (2010–2022)':                    ('2010-01-01', '2022-12-31'),
    f'Dollar Weaponization (2023–{END[:7]})': ('2023-01-01', END),
}

def period_corr(rets, start, end):
    mask = (rets.index >= pd.Timestamp(start)) & (rets.index <= pd.Timestamp(end))
    r = rets[mask]
    rows = []
    for col_a, col_b, label in PAIRS:
        valid = r[[col_a, col_b]].dropna(); n = len(valid)
        if n > 10:
            corr, _ = pearsonr(valid[col_a], valid[col_b])
            rows.append({'Pair': label, 'Correlation': round(corr, 3)})
        else:
            rows.append({'Pair': label, 'Correlation': 0.0})
    return pd.DataFrame(rows).set_index('Pair')

period_labels = list(CORR_PERIODS.keys())
pair_labels   = [p[2] for p in PAIRS]
n_periods, n_pairs = len(period_labels), len(pair_labels)
corr_matrix = np.zeros((n_periods, n_pairs))
for i, (_, (s, e)) in enumerate(CORR_PERIODS.items()):
    tbl = period_corr(returns, s, e)
    for j, pair in enumerate(pair_labels):
        corr_matrix[i, j] = tbl.loc[pair, 'Correlation']

# ── Style constants ────────────────────────────────────────────────────────────
_DARK_BG = '#0f0f1a'
_CARD_BG = '#141428'
_PLOT_BG = '#1a1a2e'
_TEXT    = '#c0c8e0'
_GRID    = 'rgba(255,255,255,0.08)'
_ZERO    = 'rgba(255,255,255,0.18)'
SP_C     = '#378ADD'
GOLD_C   = '#EF9F27'
FED_C    = '#E24B4A'

_PERIODS = [
    ('2000-01-01', '2009-12-31', '#BA7517', 0.10, 'Bubble<br>2000–2009'),
    ('2010-01-01', '2022-12-31', '#185FA5', 0.09, 'QE ∞<br>2010–2022'),
    ('2023-01-01', END,          '#7F77DD', 0.11, 'Dollar<br>Weaponization'),
]

# ── Chart 1: Price + Rate ──────────────────────────────────────────────────────
f1 = make_subplots(specs=[[{'secondary_y': True}]])

for p0, p1, col, alpha, lbl in _PERIODS:
    s = pd.Timestamp(p0)
    e = min(pd.Timestamp(p1), df.index[-1])
    f1.add_vrect(x0=s, x1=e, fillcolor=col, opacity=alpha,
                 layer='below', line_width=0)
    f1.add_annotation(
        x=s + (e - s) / 2, y=1.05, yref='paper',
        text=lbl, showarrow=False, xanchor='center',
        font=dict(size=10, color=col),
        bgcolor='rgba(20,20,40,0.75)', borderpad=3,
    )

f1.add_trace(go.Scatter(
    x=df.index, y=df['SP500'], name='S&P 500',
    line=dict(color=SP_C, width=2),
    hovertemplate='S&P 500: $%{y:,.0f}<extra></extra>',
), secondary_y=False)

f1.add_trace(go.Scatter(
    x=df.index, y=df['Gold'], name='Gold ($/oz)',
    line=dict(color=GOLD_C, width=2),
    hovertemplate='Gold: $%{y:,.0f}<extra></extra>',
), secondary_y=False)

f1.add_trace(go.Scatter(
    x=df.index, y=df['FedRate'], name='13-wk T-bill %',
    line=dict(color=FED_C, width=1.5, dash='dash'),
    hovertemplate='Rate: %{y:.2f}%<extra></extra>',
), secondary_y=True)

ten_yrs_ago = (pd.Timestamp(END) - pd.DateOffset(years=10)).strftime('%Y-%m-%d')

f1.update_layout(
    title=dict(
        text=f'S&P 500 · Gold · 13-wk T-bill Rate — Weekly ({START[:4]}–{END[:7]})',
        font=dict(size=14, color=_TEXT),
    ),
    hovermode='x unified',
    height=600,
    paper_bgcolor=_CARD_BG,
    plot_bgcolor=_PLOT_BG,
    font=dict(color=_TEXT),
    legend=dict(orientation='h', yanchor='bottom', y=1.07,
                xanchor='right', x=1, bgcolor='rgba(20,20,40,0.85)'),
    margin=dict(t=115, b=60, l=75, r=90),
)
f1.update_yaxes(title_text='Price (USD)', secondary_y=False,
                tickformat='$,.0f', gridcolor=_GRID, zerolinecolor=_ZERO)
f1.update_yaxes(title_text='Rate (%)', secondary_y=True,
                range=[0, 9], tickformat='.1f', ticksuffix='%', showgrid=False)
f1.update_xaxes(
    showgrid=True, gridcolor=_GRID,
    range=[ten_yrs_ago, END],
    rangeslider=dict(
        visible=True,
        bgcolor='#1a1a2e',
        bordercolor='#2a2a4a',
        thickness=0.06,
    ),
)

# ── Chart 2: Correlation heatmap ───────────────────────────────────────────────
_ylabels = [p.split('(')[0].strip() for p in period_labels]

f2 = go.Figure(data=go.Heatmap(
    z=corr_matrix,
    x=pair_labels,
    y=_ylabels,
    colorscale='RdYlGn',
    zmin=-1, zmax=1,
    text=[[f'{v:.2f}' for v in row] for row in corr_matrix],
    texttemplate='<b>%{text}</b>',
    textfont=dict(size=15, color='#111111'),
    colorbar=dict(title=dict(text='Pearson r', font=dict(color=_TEXT)),
                  tickfont=dict(color=_TEXT)),
    hovertemplate='<b>%{y}</b><br>%{x}<br>r = %{z:.3f}<extra></extra>',
))
f2.update_layout(
    title=dict(text='Correlation Heatmap — Weekly Returns by Period',
               font=dict(size=13, color=_TEXT)),
    height=480,
    paper_bgcolor=_CARD_BG,
    plot_bgcolor=_CARD_BG,
    font=dict(color=_TEXT),
    margin=dict(t=55, b=90, l=220, r=80),
    xaxis=dict(side='bottom', tickfont=dict(size=13)),
    yaxis=dict(tickfont=dict(size=12)),
)

# ── Chart 3: Rolling 52-week correlation ──────────────────────────────────────
f3 = go.Figure()

for p0, p1, col, alpha, lbl in _PERIODS:
    s = pd.Timestamp(p0)
    e = min(pd.Timestamp(p1), df.index[-1])
    f3.add_vrect(x0=s, x1=e, fillcolor=col, opacity=alpha * 0.7,
                 layer='below', line_width=0)

f3.add_hline(y=0, line=dict(color='rgba(200,200,200,0.3)', width=1))

for series, name, color in [
    (roll_fg, 'Fed ↔ Gold',      FED_C),
    (roll_fs, 'Fed ↔ S&P 500',  SP_C),
    (roll_gs, 'Gold ↔ S&P 500', GOLD_C),
]:
    f3.add_trace(go.Scatter(
        x=series.index, y=series, name=name,
        line=dict(color=color, width=1.8),
        hovertemplate=name + ': %{y:.3f}<extra></extra>',
    ))

f3.update_layout(
    title=dict(text=f'Rolling {WINDOW}-Week Correlation (weekly returns)',
               font=dict(size=13, color=_TEXT)),
    hovermode='x unified',
    height=520,
    paper_bgcolor=_CARD_BG,
    plot_bgcolor=_PLOT_BG,
    font=dict(color=_TEXT),
    yaxis=dict(range=[-1.1, 1.1], title='Rolling Pearson r', tickformat='.2f',
               gridcolor=_GRID, zerolinecolor=_ZERO),
    xaxis=dict(
        range=[ten_yrs_ago, df.index[-1]],
        showgrid=True, gridcolor=_GRID,
        rangeslider=dict(
            visible=True,
            bgcolor='#1a1a2e',
            bordercolor='#2a2a4a',
            thickness=0.06,
        ),
    ),
    legend=dict(orientation='h', yanchor='bottom', y=1.02,
                xanchor='right', x=1, bgcolor='rgba(20,20,40,0.85)'),
    margin=dict(t=70, b=60, l=65, r=40),
)

# ── Assemble HTML ──────────────────────────────────────────────────────────────
cfg_zoom = {'responsive': True, 'displayModeBar': True}
cfg_static = {'responsive': True}

div1 = pio.to_html(f1, include_plotlyjs='cdn', full_html=False, config=cfg_zoom)
div2 = pio.to_html(f2, include_plotlyjs=False, full_html=False, config=cfg_static)
div3 = pio.to_html(f3, include_plotlyjs=False, full_html=False, config=cfg_zoom)

html = (
    '<!DOCTYPE html>\n'
    '<html lang="en">\n'
    '<head>\n'
    '  <meta charset="UTF-8">\n'
    '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
    '  <title>Gold · S&amp;P 500 · Fed Rate Dashboard</title>\n'
    '  <style>\n'
    '    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}\n'
    f'   body{{background:{_DARK_BG};color:{_TEXT};font-family:Segoe UI,Helvetica,Arial,sans-serif;padding:28px 20px 48px}}\n'
    '    header{text-align:center;margin-bottom:28px}\n'
    '    header h1{font-size:1.45em;font-weight:600;letter-spacing:.03em;color:#d0d8f0;margin-bottom:6px}\n'
    '    header p{font-size:.80em;color:#5a6278}\n'
    f'   .card{{background:{_CARD_BG};border-radius:10px;padding:6px 10px 10px;margin-bottom:20px;box-shadow:0 4px 22px rgba(0,0,0,.55)}}\n'
    '  </style>\n'
    '</head>\n'
    '<body>\n'
    '  <header>\n'
    '    <h1>S&amp;P 500 &middot; Gold &middot; Fed Rate &mdash; Interactive Dashboard</h1>\n'
    f'   <p>Weekly data {START[:4]}&ndash;{END[:7]}'
    ' &nbsp;&bull;&nbsp; Hover to inspect values'
    ' &nbsp;&bull;&nbsp; Use the range slider to navigate years'
    ' &nbsp;&bull;&nbsp; Double-click to reset view</p>\n'
    '  </header>\n'
    f'  <div class="card">{div1}</div>\n'
    f'  <div class="card">{div3}</div>\n'
    f'  <div class="card">{div2}</div>\n'
    '</body>\n'
    '</html>\n'
)

out = 'dashboard.html'
with open(out, 'w', encoding='utf-8') as fh:
    fh.write(html)

kb = os.path.getsize(out) / 1024
print(f'\nDashboard saved -> {out}  ({kb:.0f} KB)')
