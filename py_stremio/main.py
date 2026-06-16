"""Console entry point for the full py-stremio workflow."""
from .app import AppService

__all__ = ["run", "run_cron", "update_config_imdb_ids"]


CRON_DOWNLOAD_THREADS = 5
CRON_SPEED_PERCENT = 80


def run() -> None:
    AppService().run()


def run_cron() -> None:
    """Cron-friendly entry point using the same AppService path as py-stremio."""
    AppService().run(
        interactive=False,
        default_max_workers=CRON_DOWNLOAD_THREADS,
        default_speed_percent=CRON_SPEED_PERCENT,
    )


def update_config_imdb_ids(quiet: bool = False) -> int:
    """Backward-compat alias — delegates to MetadataService."""
    from py_stremio.services.metadata import MetadataService
    return MetadataService().run(quiet=quiet)


if __name__ == "__main__":
    run()
