import datetime as dt
import time
import os

import matplotlib
matplotlib.rcParams['backend'] = "Qt4Agg"
#matplotlib.use("Agg")

import numpy as np
import pandas as pd
import xray
import pdb

import config_lidar as cl                               # contains all constants
import windcube_tools as wt
import windcube_plotting as wp



# replaces outliers in data set with NaN (used before wind fit)
def set_outliers_to_nan(data_points):
    margin=40
    try:
        nd = np.abs(data_points - np.median(data_points))
        s = nd/np.median(nd)
        data_points[s>margin]=np.nan
    except IndexError:
        dummy = data_points

    return data_points


# compares DBS wind to VAD scan fit results
def compare_dbs(DBSdf, p, sDate):
    # get VAD data (requires existing VAD netcdf file)
    VADfile = cl.OutPath + sDate[0:4] + os.sep + sDate + '_VAD' + '_45.nc'
    VADdf = wt.open_existing_nc(VADfile)
    VADdfix = VADdf.reset_index()
    DBSdfix = DBSdf.reset_index()
    df = pd.merge(VADdfix, DBSdfix, how='outer')
    df = df.set_index( ['time', 'range'] )

    # obtain horizontal wind speed and direction from xwind and ywind
    df['hwind'] = np.sqrt( df.xwind**2 + df.ywind**2 )
    df['hdir'] = np.degrees( np.arctan2( df.xwind, df.xwind ) ) + 180

    # test different averaging
    df1min = df.unstack('range').resample('1T', fill_method='bfill').stack('range')
    df2min = df.unstack('range').resample('2T', fill_method='bfill').stack('range')
    df3min = df.unstack('range').resample('3T', fill_method='bfill').stack('range')
    df5min = df.unstack('range').resample('5T', fill_method='bfill').stack('range')

    if cl.SWITCH_PLOT:
        # plot correlation of horizontal wind speed
        wp.plot_correlation( df1min, p, sDate, 'wspeed', 'hwind', 'Horizontal wind speed, ', '1 minute', [0, 30] )
        wp.plot_correlation( df2min, p, sDate, 'wspeed', 'hwind', 'Horizontal wind speed, ', '2 minutes', [0, 30] )
        wp.plot_correlation( df3min, p, sDate, 'wspeed', 'hwind', 'Horizontal wind speed, ', '3 minutes', [0, 30] )
        wp.plot_correlation( df5min, p, sDate, 'wspeed', 'hwind', 'Horizontal wind speed, ', '5 minutes', [0, 30] )

        # plot correlation of horizontal wind direction
        wp.plot_correlation( df1min, p, sDate, 'wdir', 'hdir', 'Horizontal wind direction, ', '1 minute', [0, 360] )
        wp.plot_correlation( df3min, p, sDate, 'wdir', 'hdir', 'Horizontal wind direction, ', '3 minutes', [0, 360] )

        # plot correlation of vertical velocity
        wp.plot_correlation( df1min, p, sDate, 'w', 'zwind', 'Vertical velocity, ', '1 minute', [-2.5, 2.5] )
        wp.plot_correlation( df3min, p, sDate, 'w', 'zwind', 'Vertical velocity, ', '3 minutes', [-2.5, 2.5] )


def create_hdcp2_output(sDate):
    # level 1 data
    winddf = wt.open_existing_nc( cl.DataPath + sDate[0:4] + os.sep + sDate + '_radial_wind_speed.nc' )
    betadf = wt.open_existing_nc( cl.DataPath + sDate[0:4] + os.sep + sDate + '_beta.nc' )
    for var in winddf:
        if var in betadf:
            betadf.drop( var, axis=1, inplace=True )
    # convert pandas data frame to xray data set, merge both and convert back to data frame
    windds = xray.Dataset.from_dataframe(winddf)
    betads = xray.Dataset.from_dataframe(betadf)
    lvl1ds = windds.merge(betads, compat='broadcast_equals')
    windds.close()
    betads.close()
    # remove data not needed for HDCP2 files
    for key in lvl1ds:
        if key not in cl.AttDict or cl.AttDict[key][7] is False:
            lvl1ds = lvl1ds.drop( key )
    lvl1df = lvl1ds.to_dataframe()
    lvl1ds.close()
    # create output
    wt.export_to_netcdf( lvl1df, 'hdcp2', sDate, 'level1' )

    # level 2 data
    VADdf = wt.open_existing_nc( cl.DataPath + sDate[0:4] + os.sep + sDate + '_VAD_75.nc' )
    for key in VADdf:
        if key not in cl.AttDict or cl.AttDict[key][7] is False:
            VADdf = VADdf.drop( key, axis=1 )
    wt.export_to_netcdf( VADdf, 'hdcp2', sDate, 'level2' )

