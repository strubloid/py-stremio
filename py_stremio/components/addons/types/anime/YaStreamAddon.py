"""YaStream – Asian drama streaming with subtitles and debrid support."""

from ...base import HttpAddon


class YaStreamAddon(HttpAddon):
    """YaStream – streams Asian dramas, series and movies with subtitles. Supports Korean, Chinese, Japanese, Philippine, Thai, Hongkong, Taiwanese, US, Khmer catalogs with debrid integration."""

    name = "yastream"
    base_url = "https://yastream.tamthai.de"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
