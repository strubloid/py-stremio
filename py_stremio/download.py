"""Console entry point for config/state driven downloads."""

from .components.download_manager import main, run_downloads

__all__ = ["main", "run_downloads"]


if __name__ == "__main__":
    main()
