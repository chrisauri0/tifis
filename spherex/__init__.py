"""Tifis: a player for the SPHEREx infrared sky (NASA Space Apps 2026).

The package is organised like the original Go code it replaces:

    spherex.fits     FITS files at the HDU level
    spherex.wcs      TAN-SIP celestial WCS and the WAVE-TAB spectral WCS
    spherex.sky      field model, simulation, reprojection, photometry, tracking
    spherex.irsa     IRSA client (SIA, TAP, cutouts, CatWISE) and the disk cache
    spherex.gaia     Gaia DR3 from the ESA CDN: HEALPix, range downloads, tiles
    spherex.engine   per-browser-tab engine: loading, composition, selection
    spherex.server   HTTP server: web app, /api/* proxy and the engine API
"""

__version__ = "1.0.0"
