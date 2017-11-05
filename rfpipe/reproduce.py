from __future__ import print_function, division, absolute_import #, unicode_literals # not casa compatible
from builtins import bytes, dict, object, range, map, input#, str # not casa compatible
from future.utils import itervalues, viewitems, iteritems, listvalues, listitems
from io import open

import pickle
import os.path
import numpy as np
from rfpipe import preferences, state, util, search, source, metadata, candidates

import logging
logger = logging.getLogger(__name__)


def oldcands_read(candsfile, sdmscan=None):
    """ Read old-style candfile and create new-style DataFrame
    Returns a list of tuples (state, dataframe) per scan.
    """

    with open(candsfile, 'rb') as pkl:
        d = pickle.load(pkl)
        loc, prop = pickle.load(pkl)

    if not sdmscan:
        scanind = d['featureind'].index('scan')
        scans = np.unique(loc[:, scanind])
    else:
        scans = [sdmscan]

    ll = []
    for scan in scans:
        try:
            st, cc = oldcands_readone(candsfile, scan)
            ll.append((st, cc))
        except AttributeError:
            pass

    return ll


def oldcands_readone(candsfile, scan=None):
    """ For old-style merged candidate file, create new state and candidate
    dataframe for a given scan.
    Requires sdm locally with bdf for given scan.
    If no scan provided, assumes candsfile is from single scan not merged.
    """

    with open(candsfile, 'rb') as pkl:
        d = pickle.load(pkl)
        loc, prop = pickle.load(pkl)

    inprefs = preferences.oldstate_preferences(d, scan=scan)
    inprefs.pop('gainfile')
    sdmfile = os.path.basename(d['filename'])

    if os.path.exists(sdmfile):
        logger.info('Parsing metadata from sdmfile {0}'.format(sdmfile))
        st = state.State(sdmfile=sdmfile, sdmscan=scan, inprefs=inprefs)
    else:
        logger.info('Parsing metadata from cands file')
        meta = metadata.oldstate_metadata(d, scan=scan)
        st = state.State(inmeta=meta, inprefs=inprefs, showsummary=False)

    if 'rtpipe_version' in d:
        st.rtpipe_version = float(d['rtpipe_version'])  # TODO test this
        if st.rtpipe_version <= 1.54:
            logger.info('Candidates detected with rtpipe version {0}. All '
                        'versions <=1.54 used incorrect DM scaling.'
                        .format(st.rtpipe_version))

    if scan is None:
        scan = d['scan']

    logger.info('Calculating candidate properties for scan {0}'.format(scan))

    dtype = zip(st.search_dimensions + st.features,
               len(st.search_dimensions)*['<i4'] + len(st.features)*['<f4'])
#    features = np.concatenate((loc.transpose(), prop.transpose()))
    features = np.zeros(len(loc), dtype=dtype)
    for i in range(len(loc)):
        features[i] = tuple(list(loc[i]) + list(prop[i]))
    cc = candidates.CandCollection(features, st.prefs, st.metadata)

    return st, cc


def pipeline_dataprep(st, candloc):
    """ Prepare (read, cal, flag) data for a given state and candloc.
    """

    segment, candint, dmind, dtind, beamnum = candloc.astype(int)

    # prep data
    data = source.read_segment(st, segment)
    data_prep = source.data_prep(st, data)

    return data_prep


def pipeline_datacorrect(st, candloc, data_prep=None):
    """ Prepare and correct for dm and dt sampling of a given candloc
    Can optionally pass in prepared (flagged, calibrated) data, if available.
    """

    if data_prep is None:
        data_prep = pipeline_dataprep(st, candloc)

    segment, candint, dmind, dtind, beamnum = candloc.astype(int)
    dt = st.dtarr[dtind]
    dm = st.dmarr[dmind]

    scale = None
    if hasattr(st, "rtpipe_version"):
        scale = 4.2e-3 if st.rtpipe_version <= 1.54 else None
    delay = util.calc_delay(st.freq, st.freq.max(), dm, st.inttime,
                            scale=scale)

    data_dm = search.dedisperse(data_prep, delay)
    data_dmdt = search.resample(data_dm, dt)

    return data_dmdt


def pipeline_imdata(st, candloc, data_dmdt=None):
    """ Generate image and phased visibility data for candloc.
    Phases to peak pixel in image of candidate.
    Can optionally pass in corrected data, if available.
    """

    segment, candint, dmind, dtind, beamnum = candloc.astype(int)
    dt = st.dtarr[dtind]
    dm = st.dmarr[dmind]

    uvw = st.get_uvw_segment(segment)
    wisdom = search.set_wisdom(st.npixx, st.npixy)

    if data_dmdt is None:
        data_dmdt = pipeline_datacorrect(st, candloc)

    i = candint//dt
    image = search.image(data_dmdt, uvw, st.npixx, st.npixy, st.uvres,
                         st.fftmode, st.prefs.nthread, wisdom=wisdom,
                         integrations=[i])[0]
    dl, dm = st.pixtolm(np.where(image == image.max()))
    util.phase_shift(data_dmdt, uvw, dl, dm)
    dataph = data_dmdt[i-st.prefs.timewindow//2:i+st.prefs.timewindow//2].mean(axis=1)
    util.phase_shift(data_dmdt, uvw, -dl, -dm)

    canddata = candidates.CandData(state=st, loc=tuple(candloc), image=image,
                               data=dataph)

    # output is as from search.image_thresh
    return [canddata]


def pipeline_candidate(st, candloc, canddata=None):
    """ End-to-end pipeline to reproduce candidate plot and calculate features.
    Can optionally pass in image and corrected data, if available.
    """

    segment, candint, dmind, dtind, beamnum = candloc.astype(int)

    if canddata is None:
        canddatalist = pipeline_imdata(st, candloc)

    candcollection = candidates.calc_features(canddatalist)

    return candcollection
