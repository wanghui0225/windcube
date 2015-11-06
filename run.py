import datetime as dt
import os
import pandas as pd
from glob import glob
import pdb

# contains all constants:
import config_lidar as cl

# contains all functions:
import windcube_tools as wt
import windcube_extras as we
import windcube_plotting as wp

if cl.SWITCH_TIMER:
    import time


def main(sDate,p):
    STARTTIME = time.time()
    AllF=pd.DataFrame()
    InNC=sorted(glob(cl.DataPath + sDate[0:4] + os.sep + sDate + '_' + cl.VarDict[p]['cols'][cl.VarDict[p]['N']] + '.nc'))
    InTXT=sorted(glob(cl.DataPath + sDate[0:4] + os.sep + sDate + '-*' + cl.VarDict[p]['fend'] + '.txt'))
#   if len(InNC)>=1:
#       os.remove(InNC[0])
    if len(InNC)>=1 and cl.SWITCH_NC=='append':
        wt.printif('... nc found')
        AllF = AllF.append(wt.open_existing_nc(InNC[0]))
        wt.printif('... appending latest txt file')
        AllF = AllF.append(wt.get_data(InTXT[-1],p))
        wt.printif('... sorting')
        AllF = AllF.sort_index()
#           if p=='beta' or p=='cnr':
        os.remove(InTXT[-1])
    elif len(InNC)>=1 and cl.SWITCH_NC:
        AllF = AllF.append(wt.open_existing_nc(InNC[0]))
    else:
        # loop over all files and append data to one data frame
        wt.printif('... loop over txt files')
        for f in InTXT:
            wt.printif('... reading file ' + f)
            AllF = AllF.append(wt.get_data(f,p))
    INPUTTIME = wt.timer(STARTTIME)

    # export content of data frame to netcdf
    if p<>'cnr':
        wt.printif('... export nc')
        wt.export_to_netcdf(AllF,p,sDate,'')
        EXPORTTIME = wt.timer(STARTTIME)

    # plot time series (vertical line-of-sight only, 24h)
    if cl.SWITCH_MODE=='LOS90' or cl.SWITCH_MODE=='all':
        wp.plot_ts(AllF,p,sDate,['dummy'])
        TSTIME = wt.timer(STARTTIME)
        if p=='wind':
            wp.plot_ts(AllF,'cnr',sDate,['dummy'])
            TSTIME = wt.timer(STARTTIME)

    if p<>'dbs':
        # plot low level scans (polar)
        if cl.SWITCH_MODE=='LOW' or cl.SWITCH_MODE=='all':
            wp.plot_low_scan(AllF, p, sDate)
            if p=='wind':
                wp.plot_low_scan(AllF,'cnr',sDate)
            LOWTIME = wt.timer(STARTTIME)

        # plot line-of-sight scans (scan duration)
        if cl.SWITCH_MODE=='LOS' or cl.SWITCH_MODE=='all':
            wp.plot_los(AllF, p, sDate)
            if p=='wind':
                wp.plot_los(AllF,'cnr',sDate)
            LOSTIME = wt.timer(STARTTIME)

        # calculate horizontal wind speed and direction
        if cl.SWITCH_MODE=='VAD' or cl.SWITCH_MODE=='all':
            if p=='wind':
                wt.printif('... fitting radial wind')
                wt.wind_fit(AllF, p, sDate)

    else:
        # compare DBS wind components to VAD scan results (75 degrees elevation VAD scan only)
        we.compare_dbs(AllF, p, sDate)

    ENDTIME = wt.timer(STARTTIME)


for p in cl.proplist:
    main(cl.sDate,p)

if cl.SWITCH_HDCP2:
    we.create_hdcp2_output(cl.sDate)

