import datetime as dt
import os

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.dates as dates

import numpy as np
from scipy import optimize
import pandas as pd
import seaborn as sns
import pdb
import xray

import config_lidar as cl                               # contains all constants

if cl.SWITCH_TIMER:
    import time


sns.set(font_scale=1.3)
sns.set_style("white")


# read text files from MySQL data base, returns pandas data frame
def get_data(file_path, sProp):
    _out = pd.read_csv(file_path, sep='\t',             # read file from csv
            header=None, 
            skiprows=1,
            names=cl.VarDict[sProp]['cols'],
            index_col=['time', 'range'],                # index are time and range
            parse_dates=[0],                            # feed the first column to the parser
            date_parser=lambda d: dt.datetime.strptime(d, '%Y-%m-%d %H:%M:%S.%f'), 
            squeeze=True                                # convert to `Series` object because we only have one column
            )

    return _out


# exports pandas data frame to netcdf file, including global attributes, long names and units
def export_to_netcdf(df,sProp,sDate,nameadd):
    printif('.... convert time from decimal hours to seconds since 1970')
    # change time
#   pdb.set_trace()
#   df['time'] = df.index.get_level_values('time').astype(float).map( lambda x: dt.datetime.fromtimestamp(x) )
    printif('.... convert from df to xray ds')
    xData=xray.Dataset.from_dataframe(df)
    # add variable attributes
    if 'VAD' in nameadd:
        pname='VAD'
    else:
        pname=sProp
    printif('.... add attributes to xray ds')
    for c in range(1,len(cl.VarDict[pname]['cols'])):
        xData[cl.VarDict[pname]['cols'][c]].attrs={'units':cl.VarDict[pname]['units'][c], 'long_name':cl.VarDict[pname]['longs'][c]}
    # add global attributes
    xData.attrs=cl.AttDict
    printif('.... write to file')
    pdb.set_trace()
    # export file
    xData.to_netcdf(path=cl.OutPath + sDate[0:4] + os.sep + sDate + '_' + cl.VarDict[pname]['cols'][cl.VarDict[pname]['N']] + nameadd + '.nc', mode='w')
    xData.close()


# opens existing netcdf and returns pandas data frame
def open_existing_nc(InFile):
    # open netcdf files
    xds = xray.open_dataset(InFile).transpose()
    # convert to pandas data frame
    dfnc = xds.to_dataframe()
    # swap order of indices (first time, then range)
    dfswap = dfnc.swaplevel('time','range')
    xds.close()

    return dfswap


# replaces outliers in data set with NaN (used before wind fit)
def set_outliers_to_nan(data_points):
    margin=40
    nd = np.abs(data_points - np.median(data_points))
    s = nd/np.median(nd)
    data_points[s>margin]=np.nan

    return data_points


# run loop over all VAD scans and fits sine function at all ranges
def wind_fit(AllW, sProp, sDate):
    for VADscan in cl.ScanID['VAD']:
        # select only VAD scans
        w = AllW[AllW.scan_ID==VADscan]
#       pdb.set_trace()
        if len(w.scan_ID)>0:
            # separate different scans
            t=[x[0] for x in w.index]
            r=[x[1] for x in w.index]
            newScanIx=np.where(np.diff(t)>dt.timedelta(seconds=120))
            newScanPlus=np.concatenate([[0],newScanIx[0][0:-1]])
            # repeat fitting procedure for each VAD scan
            s0=0
            onerange = w.index.get_level_values('range')[w.index.get_level_values('time')==w.index.get_level_values('time')[0]]
            windindex = pd.MultiIndex.from_product([w.index.get_level_values('time')[newScanPlus],onerange], names=['time', 'range'])
            wind = pd.DataFrame(data=np.empty( [len(newScanPlus)*len(onerange), 6] ).fill(np.nan), 
                    index=windindex, 
                    columns=[ 'speed', 'vertical', 'direction', 'confidence_index', 'rsquared', 'number_of_function_calls' ])
            for s in newScanIx[0]:
                ws = w[s0:s+1]
                meanconf = ws.confidence_index.mean(level=1)
                ws_out = pd.DataFrame( data=np.empty( [len(onerange),3] ).fill(np.nan), columns=['speed','vertical','direction'], index=onerange )
                # run fit for each height bin
                for rbin in onerange:
                    fitfunc = lambda p, x: p[0]+p[1]*np.cos(x-p[2]) # Target function
                    # p[0] ... a (offset), p[1] ... b (amplitude), p[2] ... theta_max (phase shift)
                    # x ... azimuth angle (theta)
                    # y ... radial wind 
                    errfunc = lambda p, x, y: fitfunc(p, x) - y # Distance to the target function
                    # set azimuth to range from 0 to 360 instead of 0 to -0
                    az = ws['azimuth'][ws.index.get_level_values('range')==rbin]
                    az[ az < 0 ] = az[ az < 0 ] + 360
                    theta = np.radians( az[az < max(az)] )
                    elevation = np.radians( ws['elevation'][0] )
                    radial_wind = ws[cl.VarDict[sProp]['cols'][cl.VarDict[sProp]['N']]][ws.index.get_level_values('range')==rbin][az < max(az)]
                    set_outliers_to_nan(radial_wind)
                    # initial guess
                    guess_a = np.median( radial_wind )
                    guess_b = 3*np.std( radial_wind )/(2**0.5)
                    guess_phase = theta[ radial_wind.argmax(axis=0) ]
                    p0 = [guess_a, guess_b, guess_phase] # Initial guess for the parameters
                    # least square fit
                    try:
                        p1, C, info, mes, success = optimize.leastsq(errfunc, p0[:], args=(theta, radial_wind), full_output=1)
                        # calculate R^2
                        ss_err=(info['fvec']**2).sum()
                        ss_tot=((radial_wind-radial_wind.mean())**2).sum()
                        rsquared=1-(ss_err/ss_tot)
                        ws_out.loc[rbin,'number_of_function_calls'] = info['nfev'] # number of function calls
                    except ValueError:
                        rsquared=-999
                        ws_out.loc[rbin,'number_of_function_calls'] = -999 # number of function calls
                    ws_out.loc[rbin,'rsquared'] = rsquared # R^2

                    if rsquared>=0.1:#0.2
                        # wind components
                        ws_out.loc[rbin,'speed'] = p1[1]/np.cos( elevation ) # horizontal wind
                        ws_out.loc[rbin,'vertical'] = -p1[0]/np.sin( elevation ) # vertical wind
                        ws_out.loc[rbin,'direction'] = np.degrees(p1[2]) # wind direction
                    else:
                        # plot fit
#                       pdb.set_trace()
#                       plt.figure(figsize=(6, 5))
#                       plt.scatter(theta,radial_wind)
#                       plt.plot(theta, p1[0]+p1[1]*np.cos(theta-p1[2]))
#                       plt.show()
                        ws_out.loc[rbin,'speed'] = np.nan
                        ws_out.loc[rbin,'vertical'] = np.nan
                        ws_out.loc[rbin,'direction'] = np.nan

                wind.loc[w.index.get_level_values('time')[s0], 'speed'] = ws_out.speed.values
                wind.loc[w.index.get_level_values('time')[s0], 'vertical'] = ws_out.vertical.values
                wind.loc[w.index.get_level_values('time')[s0], 'direction'] = ws_out.direction.values
                wind.loc[w.index.get_level_values('time')[s0], 'rsquared'] = ws_out.rsquared.values
                wind.loc[w.index.get_level_values('time')[s0], 'number_of_function_calls'] = ws_out.number_of_function_calls.values
                wind.loc[w.index.get_level_values('time')[s0], 'confidence_index'] = meanconf.values
                s0 = s

            elestr = str( int( round( ws['elevation'][0] ) ) )
            plot_ts(wind, sProp, sDate, ['speed', 'horizontal wind speed / m/s', elestr])
            plot_ts(wind, sProp, sDate, ['vertical', 'vertical wind speed / m/s (positive = updraft)', elestr])
            plot_ts(wind, sProp, sDate, ['direction', 'wind direction / degrees (0, 360 = North)', elestr])

            export_to_netcdf(wind, sProp, sDate, '_VAD' + '_' + elestr)


# calculates pivot of pandas data frame, returns also axes limits and color bar properties
def prepare_plotting(dfplot, sProp, pp):
    if pp[0]=='dummy' or pp[0]=='los':
        # for 'raw' data
        t=[x[0] for x in dfplot.index]
        r=[x[1] for x in dfplot.index]
        CM='jet'
        clim1, clim2, z, CBlabel = get_lims(dfplot, sProp)
    elif pp[0]=='low_scan':
        t=np.radians(dfplot.azimuth)
        r=[x[1] * np.cos( np.radians( dfplot.elevation[0] ) ) for x in dfplot.index] # distance from Mace Head (at ground)
        clim1, clim2, z, CBlabel = get_lims(dfplot, sProp)
        if sProp=='wind':
            clim1 = clim1 * 10.0
            clim2 = clim2 * 10.0
        CM='rainbow'
    else:
        # for wind components
        z=dfplot[pp[0]][dfplot['confidence_index']>=50]
        t=[x[0] for x in z.index]
        r=[x[1] for x in z.index]
        CBlabel=pp[1]
        if pp[0]=='vertical':
            CM='coolwarm'
            clim1=-2
            clim2=2
        elif pp[0]=='direction':
            CM='rainbow'
            clim1=0
            clim2=360
        else:
            CM='BuPu'
            clim1=0
            clim2=25

    # bring data from 1 dimension to a grid (2D)
    bpivot=pd.pivot(t,r,z)

    return bpivot, t, r, clim1, clim2, CBlabel, CM


def get_lims(dfplot, sProp):
    # get beta data on a logarithmic scale for plotting
    if sProp=='beta':
        z=np.log10(dfplot[cl.VarDict[sProp]['cols'][cl.VarDict[sProp]['N']]])
        CBlabel=cl.VarDict[sProp]['cols'][cl.VarDict[sProp]['N']] + ' / log10(' + cl.VarDict[sProp]['units'][cl.VarDict[sProp]['N']] + ')'
    else:
        z=dfplot[cl.VarDict[sProp]['cols'][cl.VarDict[sProp]['N']]]
        CBlabel=cl.VarDict[sProp]['cols'][cl.VarDict[sProp]['N']] + ' / ' + cl.VarDict[sProp]['units'][cl.VarDict[sProp]['N']]

    # change scale for vertical wind
    if sProp=='wind':
        clim1=cl.VarDict[sProp]['lims'][cl.VarDict[sProp]['N']][0]/10
        clim2=cl.VarDict[sProp]['lims'][cl.VarDict[sProp]['N']][1]/10
    else:
        clim1=cl.VarDict[sProp]['lims'][cl.VarDict[sProp]['N']][0]
        clim2=cl.VarDict[sProp]['lims'][cl.VarDict[sProp]['N']][1]

    return clim1, clim2, z, CBlabel


# plot time series
def plot_ts(AllB,sProp,sDate,plotprop):
    printif('... plot ts of ' + sProp + ', ' + plotprop[0])
    # select only vertical line of sight (elevation >= 89.5)
    if plotprop[0]=='dummy':
        b1 = AllB[AllB.elevation>=89.5]
        name = cl.VarDict[sProp]['cols'][cl.VarDict[sProp]['N']]
        title = cl.VarDict[sProp]['longs'][cl.VarDict[sProp]['N']] + ' (elevation >= 89.5), on ' + sDate
        # discard background (low confidence index)
        if 'confidence_index' in AllB and cl.SWITCH_REMOVE_BG:
            b = b1[b1.confidence_index>=30]
        else:
            b = b1
    else:
        b = AllB
        if plotprop[0]=='los':
            name = cl.VarDict[sProp]['cols'][cl.VarDict[sProp]['N']] + '_elev' + plotprop[2] + '_az' + plotprop[3] + '_scan' + plotprop[4]
            title = cl.VarDict[sProp]['longs'][cl.VarDict[sProp]['N']] + ' (' + plotprop[2] + ' degrees elevation), on ' + sDate
        else:
            name=plotprop[0] + '_' + plotprop[2]
            title=sProp + ' ' + plotprop[0] + ' (' + plotprop[2] + ' degrees elevation), on ' + sDate

    # separate time and range index arrays
    bpivot, t, r, clim1, clim2, CBlabel, CM = prepare_plotting(b, sProp, plotprop)
    if cl.SWITCH_ZOOM and (sProp=='cnr'):
        limdiff = clim2 - clim1
        clim2 = clim1 + limdiff/10.0
        clim1 = clim1 - limdiff/10.0
        print(clim1, clim2)
        pdb.set_trace()

    # plotting
    plt.figure(figsize=(10, 5))
    cp = plt.contourf(bpivot.index, bpivot.columns, bpivot.T, cmap=CM, 
            vmin=clim1, vmax=clim2,
            levels=np.arange(clim1, clim2, (clim2-clim1)/50.0)
            )
    cb = plt.colorbar(cp)
    cb.set_label(CBlabel)
    # set axes limits and format
    if plotprop[0]=='los':
        plt.xlim([bpivot.index[0], bpivot.index[-1]])
    else:
        plt.xlim([bpivot.index[0], bpivot.index[0]+dt.timedelta(hours=24)])
    ax=plt.gca()
    ax.xaxis.set_major_locator(dates.HourLocator(byhour=range(0,24,2)))
    ax.xaxis.set_major_formatter(dates.DateFormatter('%H:%M'))
    plt.title(title)
    if plotprop[0]=='dummy':
        plt.ylim([0,15000])
        plt.ylabel('altitude agl / m')
    elif plotprop[0]=='los' and plotprop[2]<>'90':
        if int(plotprop[4]) in cl.LOSzoom:
            plt.ylim(cl.LOSzoom[ int(plotprop[4]) ])
        else:
            plt.ylim([0,bpivot.columns[-1] * np.cos( np.radians( b.elevation[0] ) )])
        plt.ylabel('range / m')
    elif plotprop[0]=='los' and plotprop[2]=='90':
        plt.ylim([0,10000])
        plt.ylabel('altitude agl / m')
    else:
        plt.ylim([0,5000])
        plt.ylabel('altitude agl / m')
    plt.xlabel('time / UTC')
    plt.tight_layout()
    plt.grid(b=False)
    # save plot
    plt.savefig(cl.OutPath + sDate[0:4] + os.sep + name + '_latest.png', dpi=150)


# plots low level scan on polar grid
def plot_low_scan(AllB, sProp, sDate):
    for LOWscan in cl.ScanID['LOW']:
        # select only VAD scans
        toplot = AllB[AllB.scan_ID==LOWscan]
#       pdb.set_trace()
        if len(toplot.scan_ID)>0:
            newscan=np.where(np.diff(toplot.index.get_level_values('time')) > 59000000000) # 1 minute (in ns) time difference to identify two separate scans
            n=0
            for s in newscan[0]:
                fig=plt.figure(figsize=(6, 5))
                # plot horizontal scan from n to s
                thisscan=toplot[n:s]
        
                bpivot, a, r, clim1, clim2, CBlabel, CM = prepare_plotting(thisscan, sProp, ['low_scan'])

                bpivotsmooth=np.zeros(np.shape(bpivot))
                window_size=5
                window = np.ones(int(window_size))/float(window_size)
#               for z in range(0,len(bpivot.columns)):
#                   bpivotsmooth[:,z]=np.convolve(np.array(bpivot)[:,z], window, 'same')
#                   bpivotsmooth[0:2,z]=np.nan
#                   bpivotsmooth[-3:-1,z]=np.nan

                # plotting
                ax = plt.subplot(111, polar=True)
                cp = plt.contourf(bpivot.index, bpivot.columns, bpivot.T, cmap=CM, 
                        vmin=clim1, vmax=clim2,
                        levels=np.arange(clim1, clim2, (clim2-clim1)/50.0)
                        )
                cb = plt.colorbar(cp)
                cb.set_label(CBlabel)
                ax.set_theta_zero_location('N')
                ax.set_theta_direction(-1)
                plt.tight_layout()
                plt.grid(b=True, which='both')
                # save plot
                plt.savefig(cl.OutPath + sDate[0:4] + os.sep + sDate + '_' + 
                        cl.VarDict[sProp]['cols'][cl.VarDict[sProp]['N']] + 
                        '_elev_' + str( int( round(toplot.elevation[0]) ) ) + '_' + str(n) + '_low_scan.png', dpi=150)
                n=s


# plots LOS as time series
def plot_los(AllX, sProp, sDate):
    for LOSscan in cl.ScanID['LOS']:
        # select only VAD scans
        toplot = AllX[AllX.scan_ID==LOSscan]
#       pdb.set_trace()
        if len(toplot.scan_ID)>0:
            newscan=np.where(np.diff(toplot.index.get_level_values('time')) > 59000000000) # 1 minute (in ns) time difference to identify two separate scans
            n=0
            for s in newscan[0]:
                elestr = str( int( round( toplot['elevation'][0] ) ) )
                azstr = str( int( round( toplot['azimuth'][0] ) ) )
                scanstr = str( int( round( toplot['scan_ID'][0] ) ) )
                plot_ts(toplot,sProp,sDate,['los', '', elestr, azstr, scanstr])


# prints message if output option is set in config file
def printif(message):
    if cl.SWITCH_OUTPUT:
        print(message)


# calculates time since "oldtime" and prints if output option is set to True
def timer(oldtime):
    if cl.SWITCH_TIMER:
        newtime = time.time()
        printif(dt.timedelta(seconds=newtime - oldtime))
        return newtime
