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
from py_stremio.components.collect import discover_new_addons, discover_official_stremio_addons
from py_stremio.components.configs.app_settings import settings
from py_stremio.components.download.control_panel import cleanup_terminal
from py_stremio.components.errors import print_error_summary
from py_stremio.components.library.library_scanner import ScannedFolder
from py_stremio.services.download import DownloadService
from py_stremio.services.metadata import MetadataService
from py_stremio.services.progress import ACCENT, GREEN, YELLOW, RED, DIM, RESET
from py_stremio.services.scanner import ScanService
from py_stremio.utils.cancellation import clear_shutdown, request_shutdown


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

    def run(
        self,
        interactive: bool | None = None,
        default_max_workers: int | None = None,
        default_speed_percent: int | None = None,
    ) -> None:
        """CLI entry point.

        Interactive terminals show a menu. Non-interactive runs keep the historical
        scan → metadata → download behavior so tests/scripts do not block on input.
        `py-stremio-cron` uses this same method with cron-friendly defaults.
        """
        clear_shutdown()
        try:
            return self._run(
                interactive=interactive,
                default_max_workers=default_max_workers,
                default_speed_percent=default_speed_percent,
            )
        except KeyboardInterrupt:
            self._interrupted()

    def _run(
        self,
        interactive: bool | None = None,
        default_max_workers: int | None = None,
        default_speed_percent: int | None = None,
    ) -> None:
        raw_args = sys.argv[1:]
        args = set(raw_args)
        positional = [arg for arg in raw_args if not arg.startswith("--")]
        action = positional[0] if positional else None
        max_workers = max(1, default_max_workers if default_max_workers is not None else 2)
        speed_percent = default_speed_percent

        if "--run" in args or "--all" in args:
            max_workers = int(positional[0]) if positional and positional[0].isdigit() else max_workers
            speed_percent = int(positional[1]) if len(positional) > 1 and positional[1].isdigit() else speed_percent
        else:
            speed_percent = int(positional[1]) if len(positional) > 1 and positional[1].isdigit() else speed_percent

        if "--scan" in args or "--metadata" in args or "--config" in args or action == "3":
            self._banner()
            print(_c("\n📚 Update library", ACCENT))
            folders = self.scanner.run()
            self.metadata.run(folders=folders, quiet=False)
            print_error_summary()
            return

        if "--download" in args or action == "4":
            self._banner()
            self.downloader.run(quiet=True, max_workers=max_workers, speed_percent=speed_percent)
            print_error_summary()
            return

        if "--discover-official" in args:
            self._banner()
            print(_c("\n🔍 Official Stremio Addon Discovery", ACCENT))
            discover_official_stremio_addons()
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

        if "--update-and-download" in args or action == "2":
            self._banner()
            print(_c("\n📚 Update library", ACCENT))
            folders = self.scanner.run()
            self.metadata.run(folders=folders, quiet=False)
            self.downloader.run(folders=folders, quiet=True, max_workers=max_workers, speed_percent=speed_percent)
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
        clear_shutdown()
        try:
            self._run_pipeline(download=download, quiet=quiet, max_workers=max_workers, speed_percent=speed_percent)
        except KeyboardInterrupt:
            self._interrupted()

    def _run_pipeline(
        self,
        download: bool = True,
        quiet: bool = True,
        max_workers: int = 1,
        speed_percent: int | None = None,
    ) -> None:
        self._banner()

        # 1. Combined library sync for full runs: scan + metadata together.
        self._phase("\n🔎 Library sync", "scanning folders and refreshing metadata...")
        folders = self.scanner.run_with_metadata(self.metadata, quiet=False)
        self._phase("", f"found {len(folders)} managed folder(s)")

        # 2. Validate addon URLs
        self._phase("\n🛠  Validate addon URLs", "testing addons before download...")
        validate_and_update()

        # 3. Download missing items
        if download:
            self.downloader.run(folders, quiet=quiet, max_workers=max_workers, speed_percent=speed_percent)

        print_error_summary()

    # ------------------------------------------------------------------
    # Interactive menu
    # ------------------------------------------------------------------

    def run_menu(self) -> None:
        """Interactive terminal menu for py-stremio."""
        clear_shutdown()
        try:
            self._run_menu()
        except KeyboardInterrupt:
            self._interrupted()

    def _run_menu(self) -> None:
        # Banner + menu printed ONCE at the top, never cleared.
        self._banner()
        self._menu()

        while True:
            choice = input(_c("Select 1-8 › ", ACCENT)).strip()

            if choice == "8" or choice == "":
                cleanup_terminal()
                print("Bye.")
                break

            if choice not in ("1", "2", "3", "4", "5", "6", "7"):
                print(_c("Unknown option. Choose 1-8.", RED))
                continue

            if choice == "1":
                max_workers, speed_percent = self._ask_download_options()
                self._phase("\n🔎 Library sync", "scanning folders and refreshing metadata...")
                folders = self.scanner.run_with_metadata(self.metadata, quiet=False)
                self._phase("", f"found {len(folders)} managed folder(s)")
                self._phase("\n⬇ Downloads", f"starting with {max_workers} thread(s) at {speed_percent}% speed...")
                self.downloader.run(folders=folders, quiet=True, max_workers=max_workers, speed_percent=speed_percent)

            elif choice == "2":
                max_workers, speed_percent = self._ask_download_options()
                self._phase("\n📚 Update library", "scanning and refreshing metadata...")
                folders = self.scanner.run()
                self.metadata.run(folders=folders, quiet=False)
                self._phase("\n⬇ Downloads", f"starting with {max_workers} thread(s) at {speed_percent}% speed...")
                self.downloader.run(folders=folders, quiet=True, max_workers=max_workers, speed_percent=speed_percent)

            elif choice == "3":
                self._phase("\n📚 Update library", "scanning and refreshing metadata...")
                folders = self.scanner.run()
                self.metadata.run(folders=folders, quiet=False)

            elif choice == "4":
                max_workers, speed_percent = self._ask_download_options()
                self._phase("\n⬇ Downloads", f"starting with {max_workers} thread(s) at {speed_percent}% speed...")
                self.downloader.run(quiet=True, max_workers=max_workers, speed_percent=speed_percent)

            elif choice == "5":
                self._phase("\n🔍 Addon Discovery", "scraping and testing addon URLs...")
                discover_new_addons()

            elif choice == "6":
                self._phase("\n🛠  Validate addon URLs", "testing addons before download...")
                validate_and_update()

            elif choice == "7":
                self._phase("\n🧪 Experimental Addons", "managing experimental addons...")
                self._menu_experimental_addons()

            # After the action completes, print the menu again below the output
            # so the user can immediately choose the next step without any
            # show/hide or "Press Enter" ceremony.
            print()
            self._menu()

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
        print("  2  📚⬇  Update library + download missing")
        print("  3  📚  Update library (configs)")
        print("  4  ⬇   Download missing episodes/movies")
        print("  5  🔍  Discover new addon URLs")
        print("  6  🛠  Validate addon URLs")
        print("  7  🧪  Experimental addons")
        print("  8  🚪  Exit")

    def _phase(self, title: str, detail: str | None = None) -> None:
        if title:
            print(_c(title, ACCENT), flush=True)
        if detail:
            print(f"  {detail}", flush=True)

    def _interrupted(self) -> None:
        request_shutdown()
        print(_c("\nInterrupted — shutting down workers and exiting.", YELLOW), flush=True)

    def _ask_download_options(self) -> tuple[int, int]:
        """Ask interactive py-stremio users for download threads and speed."""
        return self._ask_int("Download threads", default=2, minimum=1), self._ask_int(
            "Download speed percent",
            default=100,
            minimum=1,
            maximum=100,
        )

    def _ask_int(
        self,
        label: str,
        *,
        default: int,
        minimum: int,
        maximum: int | None = None,
    ) -> int:
        suffix = f" [{default}] › "
        raw = input(_c(f"{label}{suffix}", ACCENT)).strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print(_c(f"Invalid number; using {default}.", YELLOW))
            return default
        if value < minimum:
            print(_c(f"Minimum is {minimum}; using {minimum}.", YELLOW))
            return minimum
        if maximum is not None and value > maximum:
            print(_c(f"Maximum is {maximum}; using {maximum}.", YELLOW))
            return maximum
        return value

    def _menu_experimental_addons(self) -> None:
        """Submenu for experimental addon management."""
        from py_stremio.components.addons.experimental import (
            EXPERIMENTAL_FILE,
            generate_experimental_urls,
            load_experimental_urls,
        )

        print(_c("\n🧪 Experimental Addons", ACCENT))
        print("  Discovering and validating broad addon candidates...")
        urls = generate_experimental_urls()
        if urls:
            print(_c(f"  Generated {len(urls)} URL(s) in {EXPERIMENTAL_FILE}", GREEN))
        else:
            print(_c("  No reachable experimental addons found", YELLOW))
