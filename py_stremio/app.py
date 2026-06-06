"""AppService — the one-file flow orchestrator for py-stremio.

Usage:
    from py_stremio.app import AppService
    AppService().run()          # interactive or CLI
    AppService().run_pipeline() # scan → metadata → download

This is the single entry point. It instantiates services, calls their run()
methods in order, and handles the interactive menu / CLI argument dispatch.
"""
import sys

from py_stremio.components.addons.addon_validator import validate_and_update
from py_stremio.components.collect import discover_new_addons
from py_stremio.components.configs.app_settings import settings
from py_stremio.components.errors import print_error_summary
from py_stremio.components.library.library_scanner import ScannedFolder
from py_stremio.services.download import DownloadService
from py_stremio.services.metadata import MetadataService
from py_stremio.services.progress import ACCENT, GREEN, YELLOW, RED, RESET
from py_stremio.services.scanner import ScanService


def _c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


def _supports_color() -> bool:
    return sys.stdout.isatty()


# Re-export for backward compatibility (tests, third-party imports)
from py_stremio.services.metadata import MetadataService as _ms
update_config_imdb_ids = _ms().run


class AppService:
    """Single entry point for the py-stremio download manager.

    The run() method parses CLI arguments and dispatches to the right flow.
    The run_pipeline() method runs the full scan → metadata → download pipeline.
    The run_menu() method shows the interactive terminal menu.

    Each method reads like a story: instantiate a service, call .run().
    """

    def __init__(self):
        self.scanner = ScanService()
        self.metadata = MetadataService()
        self.downloader = DownloadService()

    # ------------------------------------------------------------------
    # CLI entry point
    # ------------------------------------------------------------------

    def run(self, interactive: bool | None = None) -> None:
        """CLI entry point.

        Interactive terminals show a menu. Non-interactive runs keep the historical
        scan → metadata → download behavior so tests/scripts do not block on input.
        """
        raw_args = sys.argv[1:]
        args = set(raw_args)
        positional = [arg for arg in raw_args if not arg.startswith("--")]
        action = positional[0] if positional else None

        if "--run" in args or "--all" in args:
            max_workers = int(positional[0]) if positional and positional[0].isdigit() else max(1, getattr(settings, "DOWNLOAD_THREADS", 1))
            speed_percent = int(positional[1]) if len(positional) > 1 and positional[1].isdigit() else None
        else:
            speed_percent = int(positional[1]) if len(positional) > 1 and positional[1].isdigit() else None
            max_workers = max(1, getattr(settings, "DOWNLOAD_THREADS", 1))

        if "--scan" in args or action == "2":
            self._banner()
            self.scanner.run()
            print_error_summary()
            return

        if "--metadata" in args or "--config" in args or action == "3":
            self._banner()
            print(_c("\n🧠 Metadata", ACCENT))
            self.metadata.run(quiet=False)
            print_error_summary()
            return

        if "--download" in args or action == "4":
            self._banner()
            self.downloader.run(quiet=True, max_workers=max_workers, speed_percent=speed_percent)
            print_error_summary()
            return

        if "--discover" in args or "--find-addons" in args or action == "5":
            self._banner()
            print(_c("\n🔍 Addon Discovery", ACCENT))
            discover_new_addons()
            print_error_summary()
            return

        if "--validate" in args or "--validate-addons" in args or action == "6":
            validate_and_update()
            print_error_summary()
            return

        if "--run" in args or "--all" in args or action == "1":
            self.run_pipeline(download=True, quiet=True, max_workers=max_workers, speed_percent=speed_percent)
            return

        if interactive is None:
            interactive = sys.stdin.isatty()
        if interactive:
            self.run_menu()
        else:
            self.run_pipeline(download=True, quiet=True, max_workers=max_workers, speed_percent=speed_percent)

    # ------------------------------------------------------------------
    # Pipeline — scan → metadata → download
    # ------------------------------------------------------------------

    def run_pipeline(
        self,
        download: bool = True,
        quiet: bool = True,
        max_workers: int = 1,
        speed_percent: int | None = None,
    ) -> None:
        """Run the standard scan → metadata → validate addons → optional download pipeline."""
        self._banner()

        # 1. Scan folders
        folders = self.scanner.run()

        # 2. Enrich metadata
        print(_c("\n🧠 Metadata", ACCENT))
        self.metadata.run(quiet=False)

        # 3. Validate addon URLs
        print(_c("\n🛠  Validate addon URLs", ACCENT))
        validate_and_update()

        # 4. Download missing items
        if download:
            self.downloader.run(folders, quiet=quiet, max_workers=max_workers, speed_percent=speed_percent)

        print_error_summary()

    # ------------------------------------------------------------------
    # Interactive menu
    # ------------------------------------------------------------------

    def run_menu(self) -> None:
        """Interactive terminal menu for py-stremio."""
        self._banner()
        self._menu()
        choice = input(_c("Select 1-7 › ", ACCENT)).strip()

        if choice == "1" or choice == "":
            max_workers = self._ask_download_threads()
            folders = self.scanner.run()
            print(_c("\n🧠 Metadata", ACCENT))
            self.metadata.run(quiet=False)
            self.downloader.run(folders, quiet=True, max_workers=max_workers)

        elif choice == "2":
            self.scanner.run()

        elif choice == "3":
            print(_c("\n🧠 Metadata", ACCENT))
            self.metadata.run(quiet=False)

        elif choice == "4":
            self.downloader.run(quiet=True, max_workers=self._ask_download_threads())

        elif choice == "5":
            print(_c("\n🔍 Addon Discovery", ACCENT))
            discover_new_addons()

        elif choice == "6":
            validate_and_update()

        elif choice == "7":
            print("Bye.")

        else:
            print(_c("Unknown option. Choose 1-7.", RED))

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _banner(self) -> None:
        mode = "DRY RUN" if settings.DRY_RUN else "LIVE"
        print()
        print(_c("╭────────────────────────────────────╮", ACCENT))
        print(_c("│  ✦ Py-Stremio Download Manager ✦   │", ACCENT))
        print(_c("╰────────────────────────────────────╯", ACCENT))
        print(f"  Mode: {_c(mode, GREEN if settings.DRY_RUN else YELLOW)}")
        print(f"  Root: {settings.ROOT_FOLDER}")

    def _menu(self) -> None:
        print()
        print(_c("Choose a step", ACCENT))
        print("  1  ✨  Run: scan → metadata → download")
        print("  2  🔎  Scan library")
        print("  3  🧠  Refresh configs + metadata")
        print("  4  ⬇   Download missing episodes/movies")
        print("  5  🔍  Discover new addon URLs")
        print("  6  🛠  Validate addon URLs")
        print("  7  🚪  Exit")

    def _ask_download_threads(self) -> int:
        default = max(1, getattr(settings, "DOWNLOAD_THREADS", 1))
        answer = input(_c(f"Download threads [{default}] › ", ACCENT)).strip()
        if not answer:
            return default
        try:
            return max(1, int(answer))
        except ValueError:
            return default
