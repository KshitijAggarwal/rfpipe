from future.utils import itervalues, viewitems, iteritems, listvalues, listitems
from io import open

import logging
logger = logging.getLogger(__name__)

import os.path, attr

import numpy as np
from . import util, source

import pwkit.environments.casa.util as casautil
qa = casautil.tools.quanta()
me = casautil.tools.measures()


@attr.s
class Metadata(object):
    """ Metadata we need to translate parameters into a pipeline state.
    Called from a function defined for a given source (e.g., an sdm file).
    Built from *nominally* immutable attributes and properties.
    To modify metadata, use attr.assoc(inst, key=newval)

    TODO: can we freeze attributes while still having cached values?
    """

    # basics
    filename = attr.ib(default=None)
    scan = attr.ib(default=None)
    bdfdir = attr.ib(default=None)
    bdfstr = attr.ib(default=None)
#    configid = attr.ib(default=None)

    # data structure and source properties
    source = attr.ib(default=None)
    radec = attr.ib(default=None)
    inttime = attr.ib(default=None)
    nints = attr.ib(default=None)
    telescope = attr.ib(default=None)

    # array/antenna info
    starttime_mjd = attr.ib(default=None)
# **TODO: need to think about which of nints and endditme is more fundamental. make other a derived property
#    endtime_mjd = attr.ib(default=None)
    dishdiameter = attr.ib(default=None)
    intent = attr.ib(default=None)
    antids = attr.ib(default=None)
#    stationids = attr.ib(default=None) # needed?
    xyz = attr.ib(default=None) # in m, geocentric

    # spectral info
    spw_orig = attr.ib(default=None) # indexes for spw
    spw_nchan = attr.ib(default=None) # channesl per spw
    spw_reffreq = attr.ib(default=None) # reference frequency in Hz
    spw_chansize = attr.ib(default=None) # channel size in Hz
    pols_orig = attr.ib(default=None)


    def atdefaults(self):
        """ Is metadata still set at default values? """
        return not any([self.__dict__[ab] for ab in self.__dict__])


    @property
    def workdir(self):
        return os.path.dirname(os.path.abspath(self.filename))


#    @property
#    def spw_chanr(self):
#        chanr = []
#        i0 = 0
#        for nch in self.spw_nchan:
#            chanr.append((i0, i0+nch))
#            i0 = nch
#        return chanr

    @property
    def freq_orig(self):
        """Spacing of channel centers in GHz"""

        return np.array([np.linspace(self.spw_reffreq[ii], self.spw_reffreq[ii] +
                                     (self.spw_nchan[ii]-1) * self.spw_chansize[ii], self.spw_nchan[ii])
                        for ii in range(len((self.spw_reffreq)))], dtype='float32').flatten()/1e9


    @property
    def nchan_orig(self):
        return len(self.freq_orig)


    @property
    def nants_orig(self):
#        return len(self.ants_orig)
        return len(self.antids)


    @property
    def nbl_orig(self):
        return int(self.nants_orig*(self.nants_orig-1)/2)


    @property
    def antpos(self):
        x = self.xyz[:, 0].tolist()
        y = self.xyz[:, 1].tolist()
        z = self.xyz[:, 2].tolist()
        return me.position('itrf', qa.quantity(x, 'm'), qa.quantity(y, 'm'), qa.quantity(z, 'm'))


    @property
    def starttime_string(self):
        return qa.time(qa.quantity(self.starttime_mjd,'d'), form="ymd", prec=8)[0]


    @property
    def endtime_mjd(self):
        if self.nints:
            return self.starttime_mjd + (self.nints*self.inttime)/(24*3600)
        else:
            return None


    @property
    def uvrange_orig(self):
        if not hasattr(self, '_uvrange_orig'):
            (u, v, w) = util.calc_uvw(datetime=self.starttime_string, radec=self.radec, antpos=self.antpos, telescope=self.telescope)
            u = u * self.freq_orig[0] * (1e9/3e8) * (-1)
            v = v * self.freq_orig[0] * (1e9/3e8) * (-1)
            self._uvrange_orig = (u.max() - u.min(), v.max() - v.min())

        return self._uvrange_orig


    @property
    def npol_orig(self):
        return len(self.pols_orig)


def config_metadata(config):
    """ Wraps Metadata call to provide immutable, attribute-filled class instance.
    Parallel structure to sdm_metadata, so this inherits some of its nomenclature.
    """

    logger.info('Reading metadata from config object')

    meta = {}
    meta['filename'] = config.datasetId
    meta['scan'] = config.scanNo
#    meta['configid'] = config.Id

    meta['starttime_mjd'] = config.startTime
# **TODO: need to think about which of these two is more fundamental. make other a derived property
#    meta['endtime_mjd'] =  # no such thing, yet
#    meta['nints'] = # no such thing, yet
    meta['source'] = config.source
    meta['intent'] = config.scan_intent
    meta['telescope'] = config.telescope
    antennas = config.get_antennas()
    meta['antids'] = [ant.name for ant in antennas]
#    meta['stationids'] = config.listOfStations
    meta['xyz'] = np.array([ant.xyz for ant in antennas])

    meta['radec'] = (config.ra_deg, config.dec_deg)
    meta['dishdiameter'] = 25.  # ?

    subbands = config.get_subbands()
    subband0 = subbands[0]  # **parsing single subband for now
    meta['inttime'] = subband0.hw_time_res  # assumes that vys stream comes after hw integration
    meta['pols_orig'] = subband0.pp
    meta['spw_nchan'] = [sb.spectralChannels for sb in subbands]
    meta['spw_chansize'] = [sb.bw/subband0.spectralChannels for sb in subbands]
    meta['spw_orig'] = [sb.sbid for sb in subbands]
    meta['spw_reffreq'] = [sb.sky_center_freq*1e6 for sb in subbands]

    return meta


def sdm_metadata(sdmfile, scan, bdfdir=None):
    """ Wraps Metadata call to provide immutable, attribute-filled class instance.
    """

    logger.info('Reading metadata from {0}, scan {1}'.format(sdmfile, scan))

    sdm = source.getsdm(sdmfile, bdfdir=bdfdir)
    scanobj = sdm.scan(scan)

    meta = {}
    meta['filename'] = sdmfile
    meta['scan'] = scan
    meta['bdfdir'] = bdfdir
#    meta['configid'] = scanobj.configDescriptionId
    bdfstr = scanobj.bdf.fname
    if (not os.path.exists(bdfstr)) or ('X1' in bdfstr):
        meta['bdfstr'] = None
    else:
        meta['bdfstr'] = bdfstr

    starttime_mjd = scanobj.bdf.startTime
    meta['starttime_mjd'] = starttime_mjd
    nints = scanobj.bdf.numIntegration
    inttime = scanobj.bdf.get_integration(0).interval
    meta['inttime'] = inttime
    meta['nints'] = nints
    meta['source'] = str(scanobj.source)
    meta['intent'] = ' '.join(scanobj.intents)
    meta['telescope'] = str(sdm['ExecBlock'][0]['telescopeName']).strip()
    meta['antids'] = scanobj.antennas  # ** test that these are the same as what we expected with rtpipe **
#    meta['stationids'] = scanobj.stations
    meta['xyz'] = np.array(scanobj.positions)

    sources = source.sdm_sources(sdmfile)
    meta['radec'] = [(prop['ra'], prop['dec']) for (sr, prop) in sources.iteritems() if str(prop['source']) == str(scanobj.source)][0]
    meta['dishdiameter'] = float(str(sdm['Antenna'][0].dishDiameter).strip())
    meta['spw_orig'] = [int(str(row.spectralWindowId).split('_')[1]) for row in sdm['SpectralWindow']]
    meta['spw_nchan'] = [int(row.numChan) for row in sdm['SpectralWindow']]
    meta['spw_reffreq'] = [float(row.chanFreqStart) for row in sdm['SpectralWindow']]
    meta['spw_chansize'] = [float(row.chanFreqStep) for row in sdm['SpectralWindow']]

    meta['pols_orig'] = [pol for pol in (str(sdm['Polarization'][0]
                                               .corrType).strip()
                                           .split(' '))
                           if pol in ['XX', 'YY', 'XY', 'YX',
                                      'RR', 'LL', 'RL', 'LR',
                                      'A*A', 'B*B', 'A*B', 'B*A']]

    return meta


def mock_metadata(t0, nants, nspw, nchan, npol, inttime_micros, **kwargs):
    """ Wraps Metadata call to provide immutable, attribute-filled class instance.
    Parallel structure to sdm_metadata, so this inherits some of its nomenclature.
    t0, t1 are times in mjd.
    Supports up to nant=27, npol=4, and nspw=8.
    """

    logger.info('Generating mock metadata')

    meta = {}
    meta['filename'] = 'test'
    meta['scan'] = 1
    meta['bdfdir'] = ''
#    meta['configid'] = 0
    meta['bdfstr'] = ''

    meta['starttime_mjd'] = t0
#    meta['endtime_mjd'] =  t1
    meta['inttime'] = inttime_micros/1e6
#    meta['nints'] = (t1-t0)*24*3600/meta['inttime']
    meta['source'] = 'testsource'
    meta['intent'] = 'OBSERVE_TARGET'
    meta['telescope'] = 'VLA'
    meta['antids'] = range(nants)
#    meta['stationids'] = range(nants)
    meta['xyz'] = np.array([[-1604008.7444 , -5042135.8251 ,  3553403.7108 ],
        [-1601315.9005 , -5041985.30747,  3554808.311  ],
        [-1604865.6575 , -5042190.032  ,  3552962.3635 ],
        [-1601068.806  , -5042051.9327 ,  3554824.8388 ],
        [-1596127.7308 , -5045193.7421 ,  3552652.4197 ],
        [-1601110.022  , -5041488.0826 ,  3555597.4446 ],
        [-1601061.9544 , -5041175.8753 ,  3556058.0267 ],
        [-1602044.9123 , -5042025.8014 ,  3554427.8357 ],
        [-1600863.6922 , -5039885.3167 ,  3557965.3178 ],
        [-1599340.8001 , -5043150.963  ,  3554065.2315 ],
        [-1601004.6988 , -5040802.801  ,  3556610.1493 ],
        [-1597899.8959 , -5044068.6847 ,  3553432.4502 ],
        [-1600801.9314 , -5042219.3826 ,  3554706.4294 ],
        [-1600930.0836 , -5040316.3864 ,  3557330.39   ],
        [-1603249.6721 , -5042091.4281 ,  3553797.7842 ],
        [-1601173.9647 , -5041902.6458 ,  3554987.5342 ],
        [-1606841.961  , -5042279.6752 ,  3551913.0214 ],
        [-1602592.8535 , -5042054.9924 ,  3554140.7028 ],
        [-1599926.1041 , -5042772.9772 ,  3554319.8011 ],
        [-1598663.082  , -5043581.3912 ,  3553767.0141 ],
        [-1605808.6341 , -5042230.084  ,  3552459.1978 ],
        [-1600416.518  , -5042462.4305 ,  3554536.0417 ],
        [-1601614.0832 , -5042001.6569 ,  3554652.5059 ],
        [-1601147.9425 , -5041733.8336 ,  3555235.947  ],
        [-1597053.1244 , -5044604.675  ,  3553058.9927 ],
        [-1600690.6125 , -5038758.7161 ,  3559632.0571 ],
        [-1600781.0607 , -5039347.4391 ,  3558761.5271 ]])[:nants]
    meta['radec'] = [0., 0.]
    meta['dishdiameter'] = 25
    meta['spw_orig'] = range(nspw)
    meta['spw_nchan'] = [nchan for _ in range(nspw)]
    meta['spw_reffreq'] = [2.488E9, 2.616E9, 2.744E9, 2.872E9, 3.0E9, 3.128E9, 3.256E9, 3.384E9][:nspw]
    meta['spw_chansize'] = [4000000]*8
    meta['pols_orig'] = ['RR', 'LL', 'RL', 'LR'][:npol]

    return meta


