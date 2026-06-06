"""Console entry point for the full py-stremio workflow."""
from .app import AppService

__all__ = ["run", "update_config_imdb_ids"]


def run() -> None:
    AppService().run()


def update_config_imdb_ids(quiet: bool = False) -> int:
    """Backward-compat alias — delegates to MetadataService."""
    from py_stremio.services.metadata import MetadataService
    return MetadataService().run(quiet=quiet)


if __name__ == "__main__":
    run()
