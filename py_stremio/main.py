"""Console entry point for the full py-stremio workflow."""

from .components.application import run, update_config_imdb_ids

__all__ = ["run", "update_config_imdb_ids"]


if __name__ == "__main__":
    run()
