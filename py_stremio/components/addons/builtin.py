"""Built-in Stremio addon definitions.

Each addon knows how to construct its stream-query URL, optionally embedding
a debrid-service API key that the factory sets at runtime via .api_key.
"""

from .base import HttpAddon

COMET_CONFIG = "eyJtYX...ZX19"
HDHUB_CONFIG = "eyJ0b3...YyJ9"


# ── Torrentio family ──────────────────────────────────────────────────────────

class TorrentioAddon(HttpAddon):
    """Torrentio – the most popular Stremio addon (scrapes 1337x, TPB, RARBG,
    YTS, EZTV, Kickass, etc.)."""

    name = "Torrentio"
    base_url = "https://torrentio.strem.fun"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/realdebrid={api_key}/"
        return self.base_url


class TorrentioSortSeedersAddon(TorrentioAddon):
    """Torrentio sorted by seeders."""

    name = "Torrentio-SortSeeders"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/sort=seeders|realdebrid={api_key}/"
        return self.base_url


class TorrentioPortugueseAddon(TorrentioAddon):
    """Torrentio with Portuguese language filter."""

    name = "Torrentio-PT"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/language=portuguese|realdebrid={api_key}/"
        return self.base_url


class TorrentioSpanishAddon(TorrentioAddon):
    """Torrentio with Spanish language filter."""

    name = "Torrentio-ES"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/language=spanish|realdebrid={api_key}/"
        return self.base_url


class TorrentioHindiAddon(TorrentioAddon):
    """Torrentio with Hindi language filter."""

    name = "Torrentio-HI"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/language=hindi|realdebrid={api_key}/"
        return self.base_url


class TorrentioLiteAddon(TorrentioAddon):
    """Torrentio Lite – same scrapers, simpler UI output."""

    name = "Torrentio-Lite"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/lite|realdebrid={api_key}/"
        return f"{self.base_url}/lite/"


# ── Major torrent / debrid aggregators ────────────────────────────────────────

class MediaFusionAddon(HttpAddon):
    """MediaFusion – scrapes public & semi-private trackers plus free hosters.
    Supports Trakt, Live TV, and configurable metadata."""

    name = "MediaFusion"
    base_url = "https://mediafusion.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class KnightCrawlerAddon(HttpAddon):
    """KnightCrawler – [DEPRECATED] Ceased development in 2024.
    The public instance (knightcrawler.elfhosted.com) redirects to a
    deprecation notice.  Use MediaFusion, Comet, or CometNet instead."""

    name = "KnightCrawler"
    base_url = "https://knightcrawler.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class CometAddon(HttpAddon):
    """Comet – modern lightweight torrent scraper. Actively maintained."""

    name = "Comet"
    base_url = "https://comet.feels.legal"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/{COMET_CONFIG}/manifest.json"
        return self.base_url


class CometElfHostedAddon(HttpAddon):
    """Comet running on ElfHosted infrastructure."""

    name = "Comet-ElfHosted"
    base_url = "https://comet.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class CometNetAddon(HttpAddon):
    """CometNet – Comet's next-gen, actively maintained by the Comet
    team.  Supports movie, series, anime + other.  Hosted on ElfHosted."""

    name = "CometNet"
    base_url = "https://cometnet.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class EasyNewsPlusAddon(HttpAddon):
    """Easynews+ – streams from the Easynews usenet binary retention
    service, cached via ElfHosted.  Supports movie + series."""

    name = "EasyNews+"
    base_url = "https://easynewsplus.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class PeerflixAddon(HttpAddon):
    """Peerflix – simple torrent scraper addon."""

    name = "Peerflix"
    base_url = "https://peerflix.mov"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class NucleusAddon(HttpAddon):
    """Nucleus – feature-rich scraper with Clamor integration."""

    name = "Nucleus"
    base_url = "https://nucleus.stremio.tech"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class OrionAddon(HttpAddon):
    """Orion – premium scraper with vast cached-stream database."""

    name = "Orion"
    base_url = "https://5a0d1888fa64-orion.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class DebridSearchAddon(HttpAddon):
    """Debrid Search – search cached content across debrid services."""

    name = "DebridSearch"
    base_url = "https://68d69db7dc40-debrid-search.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class StremifyAddon(HttpAddon):
    """Stremify – multi-scraper addon hosted on ElfHosted."""

    name = "Stremify"
    base_url = "https://stremify.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class JackettioAddon(HttpAddon):
    """Jackettio – connects to a Jackett instance for private/public tracker access."""

    name = "Jackettio"
    base_url = "https://jackettio.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class AIOStreamsAddon(HttpAddon):
    """AIOStreams – all-in-one stream aggregator."""

    name = "AIOStreams"
    base_url = "https://aiostreams.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class CineTorrentAddon(HttpAddon):
    """CineTorrent – torrent-based stream provider."""

    name = "CineTorrent"
    base_url = "https://150203dd784e-cinetorrent-addon.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class TorrinAddon(HttpAddon):
    """Torrin – open-source debrid-aware streaming addon."""

    name = "Torrin"
    base_url = "https://torrin.app"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


# ── Existing addons kept for backward compat ──────────────────────────────────

class ThePirateBayPlusAddon(HttpAddon):
    """ThePirateBay+ – dedicated TPB scraper."""

    name = "ThePirateBay+"
    base_url = "https://thepiratebay-plus.strem.fun"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class HDHubAddon(HttpAddon):
    """HDHub – Brazilian addon with free hosters and torrent support."""

    name = "HDHub"
    base_url = "https://hdhub.thevolecitor.qzz.io"

    def get_url(self, api_key: str | None = None) -> str:
        return f"{self.base_url}/{HDHUB_CONFIG}/manifest.json"


class BrazucaTorrentsAddon(HttpAddon):
    """Brazuca Torrents – Brazilian Portuguese content."""

    name = "Brazuca-Torrents"
    base_url = "https://94c8cb9f702d-brazuca-torrents.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/sort=size|realdebrid={api_key}/"
        return self.base_url


class AnimeKitsuAddon(HttpAddon):
    """Anime Kitsu – metadata + stream links for anime."""

    name = "Anime-Kitsu"
    base_url = "https://anime-kitsu.strem.fun"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


# ── Free / no-debrid providers ────────────────────────────────────────────────

class WatchHubAddon(HttpAddon):
    """WatchHub – scrapes multiple free video hosters."""

    name = "WatchHub"
    base_url = "https://watchhub.strem.fun"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class AkumaAddon(HttpAddon):
    """Akuma – free anime streams from Gogoanime, Zoro, AnimePahe."""

    name = "Akuma"
    base_url = "https://akuma-delta.vercel.app"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class AnimepaheAddon(HttpAddon):
    """Animepahe – free anime streams from animepahe.com."""

    name = "Animepahe"
    base_url = "https://animepahe-addon.stremio.tech"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class AnimeoAddon(HttpAddon):
    """Animeo – anime stream aggregator."""

    name = "Animeo"
    base_url = "https://7a625ac658ec-animeo.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class OnePaceAddon(HttpAddon):
    """One Pace – fan-edit of One Piece that follows the manga pacing."""

    name = "OnePace"
    base_url = "https://onepaceaddon-zoropogger.koyeb.app"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class HanimeAddon(HttpAddon):
    """Hanime – hentai anime streams."""

    name = "Hanime"
    base_url = "https://86f0740f37f6-hanime-stremio.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


# ── IPTV / Live TV ────────────────────────────────────────────────────────────

class SkyflixAddon(HttpAddon):
    """Skyflix – free IPTV channels."""

    name = "Skyflix"
    base_url = "https://skyflix.onrender.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class ArgentinaTVAddon(HttpAddon):
    """Argentina TV – free Argentine IPTV channels."""

    name = "ArgentinaTV"
    base_url = "https://848b3516657c-argentinatv.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class GreekTVAddon(HttpAddon):
    """Stremio Greek TV – free Greek television channels."""

    name = "GreekTV"
    base_url = "https://stremio-greek-tv-latest.onrender.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class XtreamProAddon(HttpAddon):
    """XtreamPro – IPTV stream aggregator."""

    name = "XtreamPro"
    base_url = "https://xtreampro.onrender.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class AIOStreamingAddon(HttpAddon):
    """AIO Streaming – all-in-one IPTV and VOD aggregator."""

    name = "AIOStreaming"
    base_url = "https://3b4bbf5252c4-aio-streaming.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


# ── Regional / Language-specific ──────────────────────────────────────────────

class NoTorrentAddon(HttpAddon):
    """NoTorrent – lightweight torrent stream provider."""

    name = "NoTorrent"
    base_url = "https://addon.notorrent2.workers.dev"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class StremThruAddon(HttpAddon):
    """StremThru – multi-debrid proxy aggregator (RD, AD, PM, TB)."""

    name = "StremThru"
    base_url = "https://stremthru.13377001.xyz"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class GuindexAddon(HttpAddon):
    """Guindex – community-maintained index of cached debrid streams."""

    name = "Guindex"
    base_url = "https://guindex-stremio.vercel.app"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/realdebrid/{api_key}/"
        return self.base_url


class LatinMoviesAddon(HttpAddon):
    """Latin Movies – Spanish/Latino movie streams."""

    name = "LatinMovies"
    base_url = "https://latinmovies.vercel.app"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class RicosStremioAddon(HttpAddon):
    """Rico's Stremio – Spanish-language content addon."""

    name = "RicosStremio"
    base_url = "https://zoreu.github.io/ricosstremio"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class KinopubAddon(HttpAddon):
    """DEPRECATED – Kinopub (Russian/Eastern European content).

    Removed from active registration in 2026 — Russian-only content source.
    Class kept for import backward compatibility only; not registered.
    """

    name = "Kinopub"
    base_url = "https://0a5433015240-stremio-kinopub.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class FTVStremioAddon(HttpAddon):
    """FTV Stremio – French television catch-up and streaming."""

    name = "FTVStremio"
    base_url = "https://ftv-stremio.surge.sh"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class FigaroCorsoAddon(HttpAddon):
    """FigaroCorso – Italian content addon."""

    name = "FigaroCorso"
    base_url = "https://www.figarocorso.info/stremio"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class EinthusanAddon(HttpAddon):
    """Einthusan – South Asian movies & shows (Hindi, Tamil, Telugu, etc.)."""

    name = "Einthusan"
    base_url = "https://einthusan.asaddon.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class VStremioAddon(HttpAddon):
    """VStremio – Vietnamese-language movies and shows."""

    name = "VStremio"
    base_url = "https://vstremio.vercel.app"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class DubbindoAddon(HttpAddon):
    """Dubbindo – dubbed content in multiple languages."""

    name = "Dubbindo"
    base_url = "https://f7094476a780-dubbindo.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class MainelocalnewsAddon(HttpAddon):
    """Maine Local News – local news streams."""

    name = "MaineLocalNews"
    base_url = "https://a0da031547f5-stremio-mainelocalnews.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class AnimesSeasonAddon(HttpAddon):
    """Animes Season – seasonal anime tracker with stream links."""

    name = "AnimesSeason"
    base_url = "https://victorgveloso.github.io/animes-season-addon"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


# ── Miscellaneous ─────────────────────────────────────────────────────────────

class YouTubeProAddon(HttpAddon):
    """YouTube PRO – browse and stream YouTube content inside Stremio."""

    name = "YouTubePRO"
    base_url = "https://youtubepro-macu.onrender.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class FShareAddon(HttpAddon):
    """FShare – Vietnamese file-sharing hoster streams."""

    name = "FShare"
    base_url = "https://fshare.gaixixon.workers.dev"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url


class ConsumetAddon(HttpAddon):
    """Consumet – multi-source anime and movie API."""

    name = "Consumet"
    base_url = "https://b89262c192b0-stremio-consumet-addon.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
