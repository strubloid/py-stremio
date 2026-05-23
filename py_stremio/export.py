"""Console entry point for exporting Stremio addons."""

import sys

from .components.stremio_exporter import export_addons_to_file, main

__all__ = ["export_addons_to_file", "main"]


if __name__ == "__main__":
    sys.exit(main())
