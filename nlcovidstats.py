#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Aug 15 11:51:39 2020

This is best run inside Spyder, not as standalone script.

Author: @hk_nien on Twitter.
"""
import re
import sys
import io
import urllib
import urllib.request
from pathlib import Path
import time
import locale
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import nl_regions
import scipy.signal
import scipy.interpolate
import scipy.integrate
import tools


try:
    DATA_PATH = Path(__file__).parent / 'data'
except NameError:
    DATA_PATH = Path('data')


# These delay values are tuned to match the RIVM Rt estimates.
# The represent the delay (days) from infection to report date,
# referencing the report date.
DELAY_INF2REP = [
    ('2020-07-01', 7.5),
    ('2020-09-01', 7),
    ('2020-09-15', 9),
    ('2020-10-09', 9),
    ('2020-11-08', 7)
    ]

# this will contain dataframes, initialized by init_data().
# - mun: municipality demograhpics
# - cases: cases by municipality
# - restrictions: Dutch restrictions by date
# - Rt_rivm: RIVM Rt estimates
# - anomalies: anomaly data
DFS = {}


#%%




def load_restrictions():
    """Return restrictions DataFrame; index=DateTime, column=Description."""

    df = pd.read_csv(DATA_PATH / 'restrictions.csv')
    df['Date'] = pd.to_datetime(df['Date']) + pd.Timedelta('12:00:00')
    df.set_index('Date', inplace=True)
    return df


def download_Rt_rivm_coronawatchNL(maxage='16 days 15 hours',  force=False):
    """Download reproduction number from RIVM if new version is available.

    Old function; CoronawatchNL is not updated anymore, so it seems
    (2020-12-20).

    Parameters:

    - maxage: maximum time difference between last datapoint and present time.
    - force: whether to download without checking the date.

    Usually, data is published on Tue 14:30 covering data up to Sunday the
    week before, so the data will be stale after 16 days 14:30 h.
    Data is downloaded from a Git repository that has some delay w.r.t. the
    RIVM publication.
    """

    # get last date available locally
    fpath = Path('data/RIVM_NL_reproduction_index.csv')
    if fpath.is_file():
        df = pd.read_csv(fpath)
        last_time = pd.to_datetime(df['Datum'].iloc[-1])
        now_time = pd.to_datetime('now')
        if not (force or now_time >= last_time + pd.Timedelta(maxage)):
            print('Not updating RIVM Rt data; seems recent enough.')
            return
        local_file_data = fpath.read_bytes()
    else:
        local_file_data = b'dummy'

    # Data via CoronawatchNL seems stale as of 2020-12-20
    url = 'https://raw.githubusercontent.com/J535D165/CoronaWatchNL/master/data-dashboard/data-reproduction/RIVM_NL_reproduction_index.csv'
    print(f'Getting latest R data ...')
    with urllib.request.urlopen(url) as response:
        data_bytes = response.read()
        if data_bytes == local_file_data:
            print(f'{fpath}: already latest version.')
        else:
            fpath.write_bytes(data_bytes)
            print(f'Wrote {fpath} .')



def download_Rt_rivm(maxage='11 days 15 hours',  force=False):
    """Download reproduction number from RIVM if new version is available.

    Parameters:

    - maxage: maximum time difference between last datapoint and present time.
    - force: whether to download without checking the date.

    Usually, data is published on Tue 14:30 covering data up to the Friday
    before. The data will be stale after 11 days 14:30 h.

    For history purposes, files will be saved as
    'rivm_reproductiegetal.csv' (latest)
    'rivm_reproductiegetal-yyyy-mm-dd.csv' (by most recent date in the data file).
    """


    # get last date available locally
    fname_tpl = 'data/rivm_reproductiegetal{}.csv'
    fpath = Path(fname_tpl.format(''))

    if fpath.is_file():
        df = pd.read_csv(fpath)
        last_time = pd.to_datetime(df['Date'].iloc[-1])
        now_time = pd.to_datetime('now')
        if not (force or now_time >= last_time + pd.Timedelta(maxage, 'd')):
            print('Not updating RIVM Rt data; seems recent enough')
            return
        local_file_data = fpath.read_bytes()
    else:
        local_file_data = b'dummy'

    url = 'https://data.rivm.nl/covid-19/COVID-19_reproductiegetal.json'
    print(f'Getting latest R data from RIVM...')
    with urllib.request.urlopen(url) as response:
        json_bytes = response.read()
        f = io.BytesIO(json_bytes)
        df = pd.read_json(f) # Columns Date, Rt_low, Rt_avg Rt_up, ...
        df.set_index('Date', inplace=True)

        f = io.StringIO()
        df.to_csv(f, float_format='%.4g')
        f.seek(0)
        data_bytes = f.read().encode('utf-8')

        if data_bytes == local_file_data:
            print(f'{fpath}: already latest version.')
        else:
            fpath.write_bytes(data_bytes)
            print(f'Wrote {fpath} .')
            ymd = df.index[-1].strftime('-%Y-%m-%d')
            fpath_arch = Path(fname_tpl.format(ymd))
            fpath_arch.write_bytes(data_bytes)
            print(f'Wrote {fpath_arch} .')


def load_Rt_rivm(autoupdate=True, source='rivm'):
    """Return Rt DataFrame, with Date index (12:00), columns R, Rmax, Rmin.

    Source can be 'rivm' or 'coronawatchnl'.
    """

    if source == 'coronawatchnl':
        if autoupdate:
            download_Rt_rivm_coronawatchNL()

        df_full = pd.read_csv('data/RIVM_NL_reproduction_index.csv')
        df_full['Datum'] = pd.to_datetime(df_full['Datum']) + pd.Timedelta(12, 'h')
        df = df_full[df_full['Type'] == ('Reproductie index')][['Datum', 'Waarde']].copy()
        df.set_index('Datum', inplace=True)
        df.rename(columns={'Waarde': 'R'}, inplace=True)
        df['Rmax'] = df_full[df_full['Type'] == ('Maximum')][['Datum', 'Waarde']].set_index('Datum')
        df['Rmin'] = df_full[df_full['Type'] == ('Minimum')][['Datum', 'Waarde']].set_index('Datum')
        return df

    if source == 'rivm':
        if autoupdate:
            download_Rt_rivm()

        df = pd.read_csv('data/rivm_reproductiegetal.csv')

        df2 = pd.DataFrame(
            {'Datum': pd.to_datetime(df['Date']) + pd.Timedelta(12, 'h')}
            )
        df2['R'] = df['Rt_avg']
        df2['Rmin'] = df['Rt_low']
        df2['Rmax'] = df['Rt_up']
        df2.set_index('Datum', inplace=True)

        # last row may be all-NaN; eliminate such rows.
        df2 = df2.loc[~df2['Rmin'].isna()]

        return df2


    raise ValueError(f'source={source!r}')

def update_cum_cases_csv(force=False):
    """Update 'cumulative data' csv file (if not recently updated)."""

    fpath = DATA_PATH / 'COVID-19_aantallen_gemeente_cumulatief.csv'
    if fpath.is_file():
        local_file_data = fpath.read_bytes()
    else:
        local_file_data = None

    if not force:
        if fpath.is_file():
            # estimated last update
            tm = time.time()
            loc_time = time.localtime(tm)
            day_seconds = loc_time[3]*3600 + loc_time[4]*60 + loc_time[5]
            tm_latest = tm - day_seconds + 14*3600
            if tm_latest > tm:
                tm_latest -= 86400

            tm_file = fpath.stat().st_mtime
            if tm_file > tm_latest + 1800: # after 14:30
                print('Not updating cumulative case file; seems to be recent enough.')
                return
            if tm_file > tm_latest:
                print('Cumulative case data file may or may not be the latest version.')
                print('Use update_cum_cases_csv(force=True) to be sure.')
                return

    url = 'https://data.rivm.nl/covid-19/COVID-19_aantallen_gemeente_cumulatief.csv'
    print(f'Getting new daily case statistics file...')
    with urllib.request.urlopen(url) as response:
        data_bytes = response.read()
        if data_bytes == local_file_data:
            print(f'{fpath}: already latest version.')
        else:
            fpath.write_bytes(data_bytes)
            print(f'Wrote {fpath} .')



def load_cumulative_cases(autoupdate=True):
    """Return df with cumulative cases by municipality. Retrieve from internet if needed.

    - autoupdate: whether to retrieve latest data from internet.
    """

    if autoupdate:
        update_cum_cases_csv()

    df = pd.read_csv('data/COVID-19_aantallen_gemeente_cumulatief.csv', sep=';')
    # Removing 'municipality unknown' records.
    # Not clear; including these, the daily numbers are higher than the official
    # report. With them removed, they are lower.
    # Examples:
    # date: incl NA, w/o NA, nos.nl, allecijfers.nl
    # 2020-11-08: 5807 5651 5703 5664
    # 2020-11-06: 7638 7206 7272 7242
    df = df.loc[~df.Municipality_code.isna()] # Remove NA records.
    df['Date_of_report'] = pd.to_datetime(df['Date_of_report'])

    return df


def get_municipalities_by_pop(minpop, maxpop, sort='size'):
    """Return list of municipalities with populations in specified range.

    sort by 'size' or 'alpha'.
    """

    df = DFS['mun']
    pops = df['Population']
    df = df.loc[(pops >= minpop) & (pops < maxpop)]

    if sort == 'alpha':
        return sorted(df.index)

    if sort == 'size':
        return list(df.sort_values(by='Population', ascending=False).index)

    raise ValueError(f'sort={sort!r}')

def get_region_data(region, lastday=-1, printrows=0, correct_anomalies=True):
    """Get case counts and population for one municipality.

    It uses the global DFS['mun'], DFS['cases'] dataframe.

    Parameters:

    - region: region name (see below)
    - lastday: last day to include.
    - printrows: print this many of the most recent rows
    - correct_anomalies: correct known anomalies (hiccups in reporting)
      by reassigning cases to earlier dates.

    Special municipalities:

    - 'Nederland': all
    - 'HR:Zuid', 'HR:Noord', 'HR:Midden', 'HR:Midden+Zuid': holiday regions.
    - 'MS:xx-yy': municipalities with population xx <= pop/1000 < yy'
    - 'P:xx': province

    Use data up to lastday.

    Return:

    - df: dataframe with added columns:

        - Delta: daily increase in case count (per capita).
        - Delta7r: daily increase as 7-day rolling average
          (last 3 days are estimated).
        - DeltaSG: daily increase, smoothed with (15, 2) Savitsky-Golay filter.Region selec
    - pop: population.
    """

    df1, npop = nl_regions.select_cases_region(DFS['cases'], region)

    # df1 will have index 'Date_of_report', columns:
    # 'Total_reported', 'Hospital_admission', 'Deceased'

    if lastday < -1 or lastday > 0:
        df1 = df1.iloc[:lastday+1]

    if len(df1) == 0:
        raise ValueError(f'No data for region={region!r}.')

    # nc: number of cases
    nc = df1['Total_reported'].diff()
    if printrows > 0:
        print(nc[-printrows:])

    nc.iat[0] = 0
    df1['Delta'] = nc/npop
    if correct_anomalies:
        _correct_delta_anomalies(df1)
        nc = df1['Delta'] * npop

    nc7 = nc.rolling(7, center=True).mean()
    nc7[np.abs(nc7) < 1e-10] = 0.0 # otherwise +/-1e-15 issues.
    nc7a = nc7.to_numpy()

    # last 3 elements are NaN, use mean of last 4 raw entries to
    # get an estimated trend and use exponential growth or decay
    # for filling the data.

    nc1 = nc.iloc[-4:].mean() # mean number at t=-1.5 days
    log_slope = (np.log(nc1) - np.log(nc7a[-4]))/1.5
    nc7.iloc[-3:] = nc7a[-4] * np.exp(np.arange(1, 4)*log_slope)

    # 1st 3 elements are NaN
    nc7.iloc[:3] = np.linspace(0, nc7.iloc[3], 3, endpoint=False)

    df1['Delta7r'] = nc7/npop
    df1['DeltaSG'] = scipy.signal.savgol_filter(
        nc/npop, 15, 2, mode='interp')

    return df1, npop

def _correct_delta_anomalies(df):
    """Apply anomaly correction to 'Delta' column.

    Store original values to 'Delta_orig' column.
    Pull data from DFS['anomalies']
    """

    dfa = DFS['anomalies']
    df['Delta_orig'] = df['Delta'].copy()

    dt_tol = pd.Timedelta(12, 'h') # tolerance on date matching
    match_date = lambda dt: abs(df.index - dt) < dt_tol

    for (date, data) in dfa.iterrows():
        f = data['fraction']
        dt = data['days_back']
        dn = df.loc[match_date(date), 'Delta_orig'] * f
        assert len(dn) == 1
        dn = dn[0]
        df.loc[match_date(date), 'Delta'] -= dn
        df.loc[match_date(date + pd.Timedelta(dt, 'd')), 'Delta'] += dn

    assert np.isclose(df["Delta"].sum(), df["Delta_orig"].sum(), rtol=1e-6, atol=0)



def construct_Dfunc(delays, plot=False):
    """Return interpolation functions fD(t) and fdD(t).

    Parameter:

    - delays: tuples (time_report, delay_days)
    - plot: whether to generate a plot.

    Return:

    - fD: interpolation function for D(t) with t in nanoseconds.
    - fdD: interpolation function for dD/dt.
      (taking time in ns but returning dD per day.)
    - delay_str: delay string e.g. '7' or '7-9'
    """

    ts0 = [float(pd.to_datetime(x[0]).to_datetime64()) for x in delays]
    Ds0 = [float(x[1]) for x in delays]
    if len(delays) == 1:
        # prevent interp1d complaining.
        ts0 = [ts0[0], ts0[0]+1e9]
        Ds0 = np.concatenate([Ds0, Ds0])

    # delay function as linear interpolation;
    # nanosecond timestamps as t value.
    fD0 = scipy.interpolate.interp1d(
        ts0, Ds0, kind='linear', bounds_error=False,
        fill_value=(Ds0[0], Ds0[-1])
    )

    # construct derivative dD/dt, smoothen out
    day = 1e9*86400 # one day in nanoseconds
    ts = np.arange(ts0[0]-3*day, ts0[-1]+3.01*day, day)
    dDs = (fD0(ts+3*day) - fD0(ts-3*day))/6
    fdD = scipy.interpolate.interp1d(
        ts, dDs, 'linear', bounds_error=False,
        fill_value=(dDs[0], dDs[-1]))

    # reconstruct D(t) to be consistent with the smoothened derivative.
    Ds = scipy.integrate.cumtrapz(dDs, ts/day, initial=0) + Ds0[0]
    fD = scipy.interpolate.interp1d(
        ts, Ds, 'linear', bounds_error=False,
        fill_value=(Ds[0], Ds[-1]))

    Dmin, Dmax = np.min(Ds0), np.max(Ds0)
    if Dmin == Dmax:
        delay_str = f'{Dmin:.0f}'
    else:
        delay_str = f'{Dmin:.0f}-{Dmax:.0f}'

    if plot:
        fig, ax = plt.subplots(1, 1, figsize=(7, 3), tight_layout=True)
        tsx = np.linspace(
            ts[0],
            int(pd.to_datetime('now').to_datetime64())
            )
        ax.plot(pd.to_datetime(tsx.astype(int)), fD(tsx))
        plt.xticks(rotation=-20)
        ax.set_xlabel('Rapportagedatum')
        ax.set_ylabel('Vertraging (dagen)')
        for tl in ax.get_xticklabels():
            tl.set_ha('left')
        ax.grid()
        fig.canvas.set_window_title('Vertraging infectiedatum - rapportage')
        fig.show()

    return fD, fdD, delay_str


def estimate_Rt_series(r, delay=9, Tc=4.0):
    """Return Rt data, assuming delay infection-reporting.q

    - r: Series with smoothed new reported cases.
      (e.g. 7-day rolling average or other smoothed data).
    - delay: assume delay days from infection to positive report.
      alternatively: list of (timestamp, delay) tuples if the delay varies over time.
      The timestamps refer to the date of report.
    - Tc: assume generation interval.

    Return:

    - Series with name 'Rt' (shorter than r by delay+1).
    - delay_str: delay as string (e.g. '9' or '7-9')
    """

    if not hasattr(delay, '__getitem__'):
        # simple delay - attach data to index with proper offset
        log_r = np.log(r.to_numpy()) # shape (n,)
        assert len(log_r.shape) == 1

        log_slope = (log_r[2:] - log_r[:-2])/2 # (n-2,)
        Rt = np.exp(Tc*log_slope) # (n-2,)

        index = r.index[1:-1] - pd.Timedelta(delay, unit='days')
        return pd.Series(index=index, data=Rt, name='Rt'), f'{delay}'

    # the hard case: delay varies over time.
    # if ri is the rate of infections, tr the reporting date, and D
    # the delay, then:
    # ri(tr-D(tr)) = r(tr) / (1 - dD/dt)
    fD, fdD, delay_str = construct_Dfunc(delay)

    # note: timestamps in nanoseconds, rates in 'per day' units.
    day_ns = 86400e9
    tr = r.index.astype(int)
    ti = tr - fD(tr) * day_ns
    ri = r.to_numpy() / (1 - fdD(tr))

    # now get log-derivative the same way as above
    log_ri = np.log(ri)
    log_slope = (log_ri[2:] - log_ri[:-2])/2 # (n-2,)
    Rt = np.exp(Tc*log_slope) # (n-2,)

    # build series with timestamp index
    Rt_series = pd.Series(
        data=Rt, name='Rt',
        index=pd.to_datetime(ti[1:-1].astype(int))
    )

    return Rt_series, delay_str





def get_t2_Rt(ncs, delta_t, i0=-3):
    """Return most recent doubling time and Rt, from case series"""

    # exponential fit
    t_gen = 4.0 # generation time (d)
    t_double = delta_t / np.log2(ncs.iloc[i0]/ncs.iloc[i0-delta_t])
    Rt = 2**(t_gen / t_double)
    return t_double, Rt

def add_labels(ax, labels, xpos, mindist_scale=1.0, logscale=True):
    """Add labels, try to have them avoid bumping.


    - labels: list of tuples (y, txt)
    - mindist_scale: set to >1 or <1 to tweak label spacing.
    """
    from scipy.optimize import fmin_cobyla

    ymin, ymax = ax.get_ylim()
    mindist = np.log10(ymax/ymin)*0.025*mindist_scale


    labels = sorted(labels)

    # log positions and sorted
    if logscale:
        Ys = np.log10([l[0] for l in labels])
    else:
        Ys = np.array([l[0] for l in labels])
    n = len(Ys)

    # Distance matrix: D @ y = distances between adjacent y values
    D = np.zeros((n-1, n))
    for i in range(n-1):
        D[i, i] = -1
        D[i, i+1] = 1

    def cons(Y):
        ds = D @ Y
        errs = np.array([ds - mindist, ds])
        #print(f'{np.around(errs, 2)}')
        return errs.reshape(-1)

    # optimization function
    def func(Y):
        return ((Y - Ys)**2).sum()

    new_Ys = fmin_cobyla(func, Ys, cons, catol=mindist*0.05)

    for Y, (_, txt) in zip(new_Ys, labels):
        y = 10**Y if logscale else Y1
        ax.text(xpos, y, txt, verticalalignment='center')


def _zero2nan(s):
    """Return copy of array/series s, negative/zeros replaced by NaN."""

    sc = s.copy()
    sc[s <= 0] = np.nan
    return sc


def plot_daily_trends(ndays=100, lastday=-1, mun_regexp=None, region_list=None,
                      source='r7', subtitle=None):
    """Plot daily-case trends (pull data from global DFS dict).

    - lastday: up to this day.
    - source: 'r7' (7-day rolling average), 'raw' (no smoothing), 'sg'
      (Savitsky-Golay smoothed).
    - mun_regexp: regular expression matching municipalities.
    - region_list: list of municipalities (including e.g. 'HR:Zuid',
      'POP:100-200', 'JSON:{...}'.
      if mun_regexp and mun_list are both specified, then concatenate.
      If neither are specified, assume 'Nederland'.

      JSON is a json-encoded dict with:

      - 'label': short label string
      - 'color': for plotting, optional.
      - 'fmt': format for plotting, e.g. 'o--', optional.
      - 'muns': list of municipality names

    - subtitle: second title line (optional)
    """

    df_restrictions = DFS['restrictions']
    df_mun = DFS['mun']

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.subplots_adjust(top=0.945-0.03*(subtitle is not None),
                        bottom=0.085, left=0.09, right=0.83)


    if region_list is None:
        region_list = []

    if mun_regexp:
        region_list = [m for m in df_mun.index if re.match(mun_regexp, m)] + region_list

    if region_list == []:
        region_list = ['Nederland']

    labels = [] # tuples (y, txt)f
    citystats = [] # tuples (Rt, T2, cp100k, cwk, popk, city_name)
    for region in region_list:
        df1, n_inw = get_region_data(region, lastday=lastday)
        df1 = df1.iloc[-ndays:]
        fmt = 'o-' if ndays < 70 else '-'
        psize = 5 if ndays < 30 else 3

        dnc_column = dict(r7='Delta7r', raw='Delta', sg='DeltaSG')[source]

        if region.startswith('JSON:'):
            reg_dict = json.loads(region[5:])
            reg_label = reg_dict['label']
            if 'fmt' in reg_dict:
                fmt = reg_dict['fmt']
            color = reg_dict['color'] if 'color' in reg_dict else None
        else:
            reg_label = re.sub(r'POP:(.*)-(.*)', r'\1k-\2k inw.', region)
            reg_label = re.sub(r'^[A-Z]+:', '', reg_label)
            color = None

        ax.semilogy(df1[dnc_column]*1e5, fmt, color=color, label=reg_label, markersize=psize)
        delta_t = 7
        i0 = dict(raw=-1, r7=-3, sg=-3)[source]
        t_double, Rt = get_t2_Rt(df1[dnc_column], delta_t, i0=i0)
        citystats.append((np.around(Rt, 2), np.around(t_double, 2),
                          np.around(df1['Delta'][-1]*1e5, 2),
                          int(df1['Delta7r'][-4] * n_inw * 7 + 0.5),
                          int(n_inw/1e3 + .5), reg_label))

        if abs(t_double) > 60:
            texp = f'Stabiel'
        elif t_double > 0:
            texp = f'×2: {t_double:.3g} d'
        elif t_double < 0:
            texp = f'×½: {-t_double:.2g} d'

        ax.semilogy(
            df1.index[[i0-delta_t, i0]], df1[dnc_column].iloc[[i0-delta_t, i0]]*1e5,
            'k--', zorder=-10)

        labels.append((df1[dnc_column][-1]*1e5, f' {reg_label} ({texp})'))


    y_lab = ax.get_ylim()[0]

    if df_restrictions is not None:
        for res_t, res_d in df_restrictions['Description'].iteritems():
            if res_t >= df1.index[0]:
                ax.text(res_t, y_lab, f'  {res_d}', rotation=90, horizontalalignment='center')


    dfc = pd.DataFrame.from_records(
        sorted(citystats), columns=['Rt', 'T2', 'C/100k', 'C/wk', 'Pop/k', 'Region'])
    dfc.set_index('Region', inplace=True)
    print(dfc)


    lab_x = df1.index[-1] + pd.Timedelta('1.2 d')
    add_labels(ax, labels, lab_x)


    ax.grid(which='both')

    if source == 'r7':
        ax.axvline(df1.index[-4], color='gray')
        # ax.text(df1.index[-4], 0.3, '3 dagen geleden - extrapolatie', rotation=90)
        title = '7-daags voortschrijdend gemiddelde; laatste 3 dagen zijn een schatting'
    elif source == 'sg':
        ax.axvline(df1.index[-8], color='gray')
        # ax.text(df1.index[-4], 0.3, '3 dagen geleden - extrapolatie', rotation=90)
        title = 'Gefilterde data; laatste 7 dagen zijn minder nauwkeurig'
    else:
        title = 'Dagcijfers'

    ax.set_ylabel('Nieuwe gevallen per 100k per dag')

    #ax.set_ylim(0.05, None)
    ax.set_xlim(None, df1.index[-1] + pd.Timedelta('1 d'))
    from matplotlib.ticker import LogFormatter, FormatStrFormatter
    ax.yaxis.set_major_formatter(FormatStrFormatter('%g'))
    # Monkey-patch to prevent '%e' formatting.
    LogFormatter._num_to_string = lambda _0, x, _1, _2: ('%g' % x)
    ax.yaxis.set_minor_formatter(LogFormatter(minor_thresholds=(3, 1)))
    #plt.xticks(pd.to_dateTime(['2020-0{i}-01' for i in range(1, 9)]))
    ax.legend() # loc='lower left')

    for tl in ax.get_xticklabels():
        tl.set_ha('left')

    if subtitle:
        title += f'\n{subtitle}'
        win_xtitle = f', {subtitle}'
    else:
        win_xtitle = ''

    ax.set_title(title)
    fig.canvas.set_window_title(f'Case trends (ndays={ndays}){win_xtitle}')
    fig.show()


def plot_cumulative_trends(ndays=100, regions=None,
                      source='r7'):
    """Plot cumulative trends per capita (pull data from global DFS dict).

    - lastday: up to this day.
    - source: 'r7' (7-day rolling average), 'raw' (no smoothing), 'sg'
      (Savitsky-Golay smoothed).
    - region_list: list of municipalities (including e.g. 'HR:Zuid',
      'POP:100-200').
    """

    fig, ax = plt.subplots(figsize=(12, 6))
    # fig.subplots_adjust(top=0.945, bottom=0.085, left=0.09, right=0.83)


    for region in regions:
        df, npop = nl_regions.select_cases_region(DFS['cases'], region)
        df = df.iloc[-ndays:]
        ax.semilogy(df['Total_reported'] * (1e5/npop), label=region)

    ax.set_ylabel('Cumulatieve Covid-19 gevallen per 100k')
    ax.grid(which='both')
    for tl in ax.get_xticklabels():
        tl.set_ha('left')
    ax.legend()
    fig.show()





def plot_anomalies_deltas(ndays=120):
    """Show effect of anomaly correction."""

    df, _npop = get_region_data('Nederland', correct_anomalies=True)
    fig, ax = plt.subplots(tight_layout=True, figsize=(8, 5))

    col_labs = [('Delta_orig', 'Raw'), ('Delta', 'Anomalies corrected')]
    for col, lab in col_labs:
        ax.semilogy(df.iloc[-ndays:][col], label=lab)
    ax.legend()
    ax.grid()
    title = 'Anomaly correction'
    ax.set_title(title)
    fig.canvas.set_window_title(title)
    fig.show()


def plot_Rt(ndays=100, lastday=-1, delay=9,
            regions='Nederland', source='r7',
            Tc=4.0, correct_anomalies=True):
    """Plot daily-case trends.

    - lastday: use case data up to this day.
    - delay: assume delay days from infection to positive report.
      alternatively: list of (timestamp, delay) tuples if the delay varies over time.
      The timestamps refer to the date of report. See doc of estimeate_Rt_series.
    - source: 'r7' or 'sg' for rolling 7-day average or Savitsky-Golay-
      filtered data.
    - Tc: generation interval time
    - regions: comma-separated string (or list of str);
      'Nederland', 'V:xx' (holiday region), 'P:xx' (province), 'M:xx'
      (municipality).
    - correct_anomalies: whether to correct for known reporting anomalies.
    """

    Rt_rivm = DFS['Rt_rivm']

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.subplots_adjust(top=0.90, bottom=0.085, left=0.09, right=0.92)
    plt.xticks(rotation=-20)
    # dict: municitpality -> population

    labels = [] # tuples (y, txt)
    if isinstance(regions, str):
        regions = regions.split(',')

    for region in regions:

        df1, _npop = get_region_data(region, lastday=lastday, correct_anomalies=correct_anomalies)
        source_col = dict(r7='Delta7r', sg='DeltaSG')[source]

        # skip the first 10 days because of zeros
        Rt, delay_str = estimate_Rt_series(df1[source_col].iloc[10:], delay=delay, Tc=Tc)
        Rt = Rt.iloc[-ndays:]
        fmt = 'o-' if ndays < 70 else '-'
        psize = 5 if ndays < 30 else 3

        if region.startswith('POP:'):
            label = region[4:] + ' k inw.'
        else:
            label = re.sub('^[A-Z]+:', '', region)
        ax.plot(Rt, fmt, label=label, markersize=psize)

        labels.append((Rt[-1], f' {label}'))

    if len(labels) == 0:
        fig.close()
        raise ValueError(f'No data to plot.')

    if Rt_rivm is not None:
        tm_lo, tm_hi = Rt.index[[0, -1]] # lowest timestamp
        tm_rivm_est = Rt_rivm[Rt_rivm['R'].isna()].index[0] # 1st index with NaN
        # final values
        Rt_rivm_final = Rt_rivm.loc[tm_lo:tm_rivm_est, 'R']
        ax.plot(Rt_rivm_final.iloc[:-1], 'k-', label='RIVM')
        ax.plot(Rt_rivm_final.iloc[-2::-7], 'ko', markersize=4)
        # estimates
        Rt_rivm_est = Rt_rivm.loc[tm_rivm_est-pd.Timedelta(1, 'd'):tm_hi+pd.Timedelta(12, 'h')]
        # print(Rt_rivm_est)
        ax.fill_between(Rt_rivm_est.index, Rt_rivm_est['Rmin'], Rt_rivm_est['Rmax'],
                        color='#bbbbbb', label='RIVM prognose')



    iex = dict(r7=3, sg=7)[source] # days of extrapolation
    y_lab = ax.get_ylim()[0]

    # add_labels(ax, labels, lab_x)
    ax.grid(which='both')
    ax.axvline(Rt.index[-iex-1], color='gray')
    ax.axhline(1, color='k', linestyle='--')
    ax.text(Rt.index[-4], ax.get_ylim()[1], Rt.index[-4].strftime("%d %b "),
            rotation=90, horizontalalignment='right', verticalalignment='top')
    ax.set_title(f'Reproductiegetal o.b.v. positieve tests; laatste {iex} dagen zijn een extrapolatie\n'
                 f'(Generatie-interval: {Tc:.3g} dg, rapportagevertraging {delay_str} dg) '
                 f'[{source}]')
    ax.set_ylabel('Reproductiegetal $R_t$')

    # get second y axis
    ax2 = ax.twinx()
    T2s = np.array([-2, -4,-7, -10, -14, -21, -60, 9999, 60, 21, 14, 10, 7, 4, 2])
    y2ticks = 2**(Tc/T2s)
    y2labels = [f'{t2 if t2 != 9999 else "∞"}' for t2 in T2s]
    ax2.set_yticks(y2ticks)
    ax2.set_yticklabels(y2labels)
    ax2.set_ylim(*ax.get_ylim())
    ax2.set_ylabel('Halverings-/verdubbelingstijd (dagen)')



    xlim = (Rt.index[0] - pd.Timedelta('12 h'), Rt.index[-1] + pd.Timedelta('3 d'))
    ax.set_xlim(*xlim)
    df_restrictions = DFS['restrictions']
    for res_t, res_d in df_restrictions['Description'].iteritems():
        if res_t >= xlim[0] and res_t <= xlim[1]:
            ax.text(res_t, y_lab, f'  {res_d}', rotation=90, horizontalalignment='center')

    ax.text(0.99, 0.98, '@hk_nien', transform=ax.transAxes,
            verticalAlignment='top', horizontalAlignment='right',
            rotation=90)

    ax.legend() # (loc='upper center')
    for tl in ax.get_xticklabels():
        tl.set_ha('left')

    fig.canvas.set_window_title(f'Rt ({", ".join(regions)[:30]}, ndays={ndays})')
    fig.show()

def plot_Rt_oscillation():
    """Uses global DFS['Rt_rivm'] variable."""


    fig, axs = plt.subplots(2, 1, tight_layout=True)

    df_Rt_rivm = DFS['Rt_rivm']

    Rr = df_Rt_rivm['R'][~df_Rt_rivm['R'].isna()].to_numpy()
    Rr = Rr[-120:]
    Rr_smooth = scipy.signal.savgol_filter(Rr, 15, 2)

    ax = axs[0]
    n = len(Rr)
    ts = np.arange(n)/7
    ax.plot(ts, Rr, label='Rt (RIVM)')
    ax.plot(ts, Rr_smooth, label='Rt smooth', zorder=-1)
    ax.plot(ts, Rr - Rr_smooth, label='Difference')
    ax.set_xlabel('Time (wk)')
    ax.set_ylabel('R')
    ax.set_xlim(ts[0], ts[-1])
    ax.legend()
    ax.grid()
    ax = axs[1]
    # window = 1 - np.linspace(-1, 1, len(Rr))**2


    window = scipy.signal.windows.tukey(n, alpha=(n-14)/n)
    spectrum = np.fft.rfft((Rr-Rr_smooth) * window)
    freqs = 7/len(Rr) * np.arange(len(spectrum))
    ax.plot(freqs, np.abs(spectrum)**2)
    ax.set_xlabel('Frequency (1/wk)')
    ax.set_ylabel('Power')
    ax.grid()

    fig.canvas.set_window_title('Rt oscillation')

    fig.show()

def init_data(autoupdate=True, Rt_source='rivm'):
    """Init global dict DFS with 'mun', 'Rt_rivm', 'cases', 'restrictions'.

    Parameters:

    - autoupdate: whether to attempt to receive recent data from online
      sources.
    - Rt_source: 'rivm' or 'coronawatchnl' (where to download Rt data).
    """

    DFS['cases'] = df = load_cumulative_cases(autoupdate=autoupdate)
    DFS['mun'] = nl_regions.get_municipality_data()
    DFS['Rt_rivm'] = load_Rt_rivm(autoupdate=autoupdate, source=Rt_source)
    DFS['restrictions'] = load_restrictions()
    dfa = pd.read_csv('data/daily_numbers_anomalies.csv', comment='#')
    dfa['Date_report'] = pd.to_datetime(dfa['Date_report']) + pd.Timedelta('10 h')
    DFS['anomalies'] = dfa.set_index('Date_report')

    print(f'Case data most recent date: {df["Date_of_report"].iat[-1]}')
    # get_mun_data('Nederland', 5e6, printrows=5)



def reset_plots():
    """Close plots and adjust default matplotlib settings."""

    # Note: need to run this twice before NL locale takes effect.
    try:
        locale.setlocale(locale.LC_ALL, 'nl_NL.UTF-8')
    except locale.Error as e:
        print(f'Warning: cannot set language: {e.args[0]}')
    plt.rcParams["date.autoformatter.day"] = "%d %b"
    plt.close('all')



if __name__ == '__main__':

    print('Please run nlcovidstats_show.py or plot_R_from_daily_cases.py')
