from __future__ import print_function, division, absolute_import, unicode_literals
from builtins import bytes, dict, object, range, map, input, str
from future.utils import itervalues, viewitems, iteritems, listvalues, listitems
from io import open

import rfpipe
import pytest
from astropy import time
from numpy import ndarray

# simulate no flag, transient/no flag, transient/flag
inprefs = [({'flaglist': [], 'npix_max': 512, 'chans': range(32), 'spw': [0],
            'savenoise': True}, 1),
           ({'simulated_transient': [(0, 30, 25, 10e-3, 1., 0.001, 0.001)],
            'dmarr': [0, 100], 'dtarr': [1, 2], 'npix_max': 512,
            'savecands': True, 'savenoise': True, 'timesub': 'mean'}, 2)]
#TODO:      support arbitrary channel selection and
#           {'read_tdownsample': 2, 'read_fdownsample': 2, 'npix_max': 512},


@pytest.fixture(scope="module", params=inprefs)
def mockstate(request):
    inprefs, scan = request.param
    t0 = time.Time.now().mjd
    meta = rfpipe.metadata.mock_metadata(t0, t0+0.5/(24*3600), 27, 4, 32*4, 4,
                                         5e3, scan=scan, datasource='sim')
    return rfpipe.state.State(inmeta=meta, inprefs=inprefs)


# simulate two DMs
@pytest.fixture(scope="module")
def mockdata(mockstate):
    segment = 0
    data = rfpipe.source.read_segment(mockstate, segment)
    return rfpipe.source.data_prep(mockstate, segment, data)


@pytest.fixture(scope="module")
def wisdom(mockstate):
    return rfpipe.search.set_wisdom(mockstate.npixx, mockstate.npixy)


def test_dataprep(mockstate, mockdata):
    assert mockdata.shape == mockstate.datashape


@pytest.fixture(scope="module")
def test_search(mockstate, mockdata, wisdom, params=[0, 1]):
    segment = 0
    dtind = 0
    uvw = rfpipe.util.get_uvw_segment(mockstate, segment)

    delay = rfpipe.util.calc_delay(mockstate.freq, mockstate.freq.max(),
                                   mockstate.dmarr[request.param],
                                   mockstate.inttime)
    datadm = rfpipe.search.dedisperse(mockdata, delay)

    canddatalist = rfpipe.search.search_thresh_fftw(mockstate, segment, datadm,
                                                    request.param, dtind,
                                                    wisdom=wisdom)

    candcollection = rfpipe.candidates.calc_features(canddatalist)
    assert type(candcollection.array) == ndarray

    if mockstate.prefs.simulated_transient:
        assert len(candcollection.array)


def test_noise(mockstate, mockdata):
    for noises in rfpipe.candidates.iter_noise(mockstate.noisefile):
        assert len(noises)


def test_pipeline(mockstate):
    res = rfpipe.pipeline.pipeline_seg(mockstate, 0)

#    assert len(res) == len(mockstate.dmarr)*len(mockstate.dtarr)
