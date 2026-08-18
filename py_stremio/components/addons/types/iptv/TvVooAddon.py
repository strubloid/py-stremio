"""TvVoo – live TV channels (Italia / UK / France) via VAVOO."""

from ...base import HttpAddon


class TvVooAddon(HttpAddon):
    """TvVoo – Italian/UK/French live TV channels resolved through VAVOO HLS.

    The configured ``cfg-it-uk-fr`` path exposes three regional catalogs
    (Italia, United Kingdom, France).  Streams are HLS-only and resolve
    against the viewer's IP via the addon's resolver endpoint — the same
    shape that ``_is_downloadable_stream_candidate`` already filters out
    for ``behaviorHints.notWebReady``.  This addon therefore contributes
    catalogs/IPTV listings but no directly-downloadable streams for the
    series/movie workflow.
    """

    name = "TvVoo"
    base_url = "https://tvvoo.hayd.uk/cfg-it-uk-fr"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
