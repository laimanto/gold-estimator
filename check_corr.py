import yfinance as yf, pandas as pd, numpy as np
from scipy.stats import pearsonr
from datetime import datetime
import warnings; warnings.filterwarnings('ignore')

START = '2000-01-01'
END   = datetime.today().strftime('%Y-%m-%d')

sp_raw  = yf.download('^GSPC', start=START, end=END, interval='1d', progress=False)
gold_raw= yf.download('GC=F',  start=START, end=END, interval='1d', progress=False)
irx_raw = yf.download('^IRX',  start=START, end=END, interval='1d', progress=False)

def to_weekly(raw, name):
    s = raw['Close'].squeeze()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s.resample('W-FRI').last().rename(name)

sp500 = to_weekly(sp_raw, 'SP500')
gold  = to_weekly(gold_raw, 'Gold')
fed   = to_weekly(irx_raw, 'FedRate').to_frame()

df = pd.concat([sp500, gold, fed], axis=1)
df.ffill(inplace=True); df.dropna(inplace=True)
print(f'Rows: {len(df)}, range: {df.index[0].date()} to {df.index[-1].date()}')

returns = pd.DataFrame({
    'SP500':   df['SP500'].pct_change(),
    'Gold':    df['Gold'].pct_change(),
    'FedRate': df['FedRate'].diff(),
}).dropna()

zero_gold = (returns['Gold'] == 0).mean() * 100
zero_sp   = (returns['SP500'] == 0).mean() * 100
print(f'Zero Gold returns: {zero_gold:.1f}%  |  Zero SP500 returns: {zero_sp:.1f}%')
print()

for label, mask in [
    ('Bubble 2000-2009',  (returns.index >= '2000-01-01') & (returns.index <= '2009-12-31')),
    ('QE 2010-2022',      (returns.index >= '2010-01-01') & (returns.index <= '2022-12-31')),
    ('DollarWeap 2023+',  (returns.index >= '2023-01-01')),
]:
    r = returns[mask]
    print(f'=== {label} (n={mask.sum()}) ===')
    for a, b, name in [
        ('FedRate', 'Gold',  'Fed-chg vs Gold  '),
        ('FedRate', 'SP500', 'Fed-chg vs SP500 '),
        ('Gold',    'SP500', 'Gold    vs SP500 '),
    ]:
        v = r[[a, b]].dropna()
        c, p = pearsonr(v[a], v[b])
        stars = '***' if p < 0.001 else ('**' if p < 0.01 else ('*' if p < 0.05 else '  '))
        print(f'  {name}: r={c:+.3f}  p={p:.4f}  {stars}')
    print()
