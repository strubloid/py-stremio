"""AppService — the one-file flow orchestrator for py-stremio.

Usage:
    from py_stremio.app import AppService
    AppService().run()          # interactive or CLI
    AppService().run_pipeline() # scan → metadata → download

This is the single entry point. It instantiates services, calls their run()
methods in order, and handles the interactive menu / CLI argument dispatch.
"""
import sys
import time

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
        cli_overrides: dict[str, str] | None = None,
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
                cli_overrides=cli_overrides or {},
            )
        except KeyboardInterrupt:
            self._interrupted()

    def _run(
        self,
        interactive: bool | None = None,
        default_max_workers: int | None = None,
        default_speed_percent: int | None = None,
        cli_overrides: dict[str, str] | None = None,
    ) -> None:
        raw_args = sys.argv[1:]
        args = set(raw_args)
        positional = [arg for arg in raw_args if not arg.startswith("--")]
        action = positional[0] if positional else None
        max_workers = max(1, default_max_workers if default_max_workers is not None else 2)
        speed_percent = default_speed_percent
        self.cli_overrides = dict(cli_overrides or {})

        if "--run" in args or "--all" in args or "--download-all" in args:
            max_workers = int(positional[0]) if positional and positional[0].isdigit() else max_workers
            speed_percent = int(positional[1]) if len(positional) > 1 and positional[1].isdigit() else speed_percent
        else:
            speed_percent = int(positional[1]) if len(positional) > 1 and positional[1].isdigit() else speed_percent

        # ── Library refresh (menu option 2) ──
        # New name: --library. Legacy names (--scan, --metadata, --config)
        # still work for backward compat.
        if (
            "--library" in args
            or "--scan" in args
            or "--metadata" in args
            or "--config" in args
            or action == "2"
        ):
            self._banner()
            print(_c("\n📚 Update library", ACCENT))
            library_start = time.monotonic()
            folders = self.scanner.run()
            self.metadata.run(folders=folders, quiet=False)
            self._print_library_elapsed(library_start, len(folders))
            print_error_summary()
            return

        # ── Full pipeline (menu option 1 = download + everything) ──
        # `--run`/`--all` and the new `--download-all` both run the
        # full pipeline: library refresh + addon validation + download.
        if "--run" in args or "--all" in args or "--download-all" in args:
            self._banner()
            self.run_pipeline(download=True, quiet=True, max_workers=max_workers, speed_percent=speed_percent)
            return

        # ── Download only (menu option 1, without library refresh) ──
        if "--download-only" in args or action == "1":
            self._banner()
            self.downloader.run(quiet=True, max_workers=max_workers, speed_percent=speed_percent)
            print_error_summary()
            return

        # ── Addons submenu (menu option 3) ──
        if "--validate-addons" in args or "--validate" in args:
            self._banner()
            print(_c("\n🛠  Validate addons", ACCENT))
            validate_and_update()
            print_error_summary()
            return

        if "--discover-addons" in args or "--discover" in args or "--find-addons" in args:
            self._banner()
            print(_c("\n🔍 Find more addons", ACCENT))
            discover_new_addons()
            print_error_summary()
            return

        if "--ai-find-addons" in args or "--ai-addons" in args:
            self._banner()
            print(_c("\n🤖 AI find addons", ACCENT))
            self._index_update(ai=True)
            print_error_summary()
            return

        # ── Index operations (advanced) ──
        if "--index-status" in args or "--idx-status" in args:
            self._index_status()
            return

        if "--index-update" in args or "--idx-update" in args:
            self._index_update(ai=args.intersection({"--ai", "--ai-discovery"}))
            return

        if "--index-save" in args or "--idx-save" in args:
            self._index_save()
            return

        if "--index-load" in args or "--idx-load" in args:
            self._index_load()
            return

        # ── Legacy backward compat (used by old cron.sh) ──
        if "--discover-official" in args:
            self._banner()
            print(_c("\n🔍 Official Stremio Addon Discovery", ACCENT))
            discover_official_stremio_addons()
            print_error_summary()
            return

        if "--update-and-download" in args:
            self._banner()
            print(_c("\n📚 Update library", ACCENT))
            folders = self.scanner.run()
            self.metadata.run(folders=folders, quiet=False)
            self.downloader.run(folders=folders, quiet=True, max_workers=max_workers, speed_percent=speed_percent)
            print_error_summary()
            return

        if interactive is None:
            interactive = sys.stdin.isatty()
        if interactive:
            self.run_menu()
        else:
            # Non-interactive default: run the full pipeline.
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
        library_start = time.monotonic()
        folders = self.scanner.run_with_metadata(self.metadata, quiet=False)
        self._phase("", f"found {len(folders)} managed folder(s)")
        self._print_library_elapsed(library_start, len(folders))

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
            choice = input(_c("Select 1-5 › ", ACCENT)).strip()

            if choice == "5" or choice == "":
                cleanup_terminal()
                print("Bye.")
                break

            if choice not in ("1", "2", "3", "4"):
                print(_c("Unknown option. Choose 1-5.", RED))
                continue

            if choice == "1":
                # The main "do everything" action: scan, fetch metadata, find
                # any new addons, then download missing episodes/movies.
                max_workers, speed_percent = self._ask_download_options()
                self._phase("\n🔎 Library sync", "scanning folders and refreshing metadata...")
                library_start = time.monotonic()
                folders = self.scanner.run_with_metadata(self.metadata, quiet=False)
                self._phase("", f"found {len(folders)} managed folder(s)")
                self._print_library_elapsed(library_start, len(folders))
                self._phase("\n⬇ Downloads", f"starting with {max_workers} thread(s) at {speed_percent}% speed...")
                self.downloader.run(folders=folders, quiet=True, max_workers=max_workers, speed_percent=speed_percent)

            elif choice == "2":
                # Update library only (no downloads).
                self._phase("\n📚 Update library", "scanning and refreshing metadata...")
                library_start = time.monotonic()
                folders = self.scanner.run()
                self.metadata.run(folders=folders, quiet=False)
                self._print_library_elapsed(library_start, len(folders))

            elif choice == "3":
                # Addons: validate what we have, find more, manage.
                self._menu_addons()

            elif choice == "4":
                # Settings: threads, speed, debrid services, experimental.
                self._menu_settings()

            # After the action completes, print the menu again below the output
            # so the user can immediately choose the next step without any
            # show/hide or "Press Enter" ceremony.
            print()
            self._menu()

    def _menu_addons(self) -> None:
        """Submenu for addon management — single place for all addon operations."""
        while True:
            print()
            print(_c("  Addons", ACCENT))
            print("    1  🛠  Validate addons (test all URLs, remove dead ones)")
            print("    2  🔍  Find more addons (scrape + validate)")
            print("    3  🤖  AI find (predict + validate new addons)")
            print("    4  🧪  Experimental addons")
            print("    5  ←   Back to main menu")
            sub = input(_c("  Select 1-5 › ", ACCENT)).strip()

            if sub == "5" or sub == "":
                break

            if sub == "1":
                self._phase("\n🛠  Validate addons", "testing every URL in addons.txt...")
                validate_and_update()
            elif sub == "2":
                self._phase("\n🔍 Find more addons", "scraping sources + validating...")
                discover_new_addons()
            elif sub == "3":
                # AI find: predict addon URLs from known patterns, then
                # validate them. Only checks patterns that are known to
                # exist (ElfHosted, baby-beamup, cloud platforms) — does
                # not invent random combinations.
                self._phase("\n🤖 AI find", "predicting addon URLs from known patterns...")
                self._index_update(ai=True)
            elif sub == "4":
                self._phase("\n🧪 Experimental addons", "managing experimental addons...")
                self._menu_experimental_addons()
            else:
                print(_c("Unknown option.", RED))

    def _menu_settings(self) -> None:
        """Submenu for settings — debrid services, threads, experimental."""
        from py_stremio.components.debrid import (
            get_default_chain,
            is_any_debrid_available,
            create_all_providers,
        )

        while True:
            providers = create_all_providers()
            available = [p for p in providers if p.is_available()]
            chain = get_default_chain()

            print()
            print(_c("  Settings", ACCENT))
            print(f"    Threads: {settings.DOWNLOAD_THREADS}    Speed: {settings.INTERNET_SPEED_LIMIT}%    Root: {settings.ROOT_FOLDER}")
            print()
            print("    1  ⚡  Show debrid services")
            print("    2  📊  Show resolved config")
            print("    3  ←   Back to main menu")
            sub = input(_c("  Select 1-3 › ", ACCENT)).strip()

            if sub == "3" or sub == "":
                break

            if sub == "1":
                print()
                print(_c("  Debrid Services", ACCENT))
                print(f"    Active chain: {chain if chain else 'none'}")
                print(f"    Available providers: {len(available)}")
                print()
                for p in providers:
                    status = "✓" if p.is_available() else "✗"
                    info = p.get_info()
                    configured = "configured" if info.is_configured else "not configured"
                    print(f"    {status}  {info.display_name} — {configured}")
            elif sub == "2":
                from py_stremio.main import _print_resolved_config
                _print_resolved_config()
            else:
                print(_c("Unknown option.", RED))

    def _quick_validate(self) -> None:
        """Fast validation using the index if available."""
        from py_stremio.components.collect.addon_index import get_addon_index
        from py_stremio.components.addons.addon_validator import check_addon_url
        from py_stremio.components.configs.app_settings import settings

        index = get_addon_index()
        status = index.quick_status()

        if status['total'] == 0:
            print("  Index is empty. Run full discovery first.")
            return

        print(f"  Quick checking {status['untested']} untested addons...")

        api_key = settings.REAL_DEBRID_API_KEY
        checked = 0
        working = 0
        failed = 0

        for url in index.get_untested_urls()[:20]:
            result = check_addon_url(url, api_key)
            checked += 1
            if result["manifest_ok"] or result["streams_found"] > 0:
                index.mark_working(url)
                working += 1
            else:
                index.mark_failed(url, result.get("error"))
                failed += 1

            if checked >= 20:
                break

        status = index.quick_status()
        print(f"  Quick check complete: {working} working, {failed} failed")
        print(f"  Index: {status['working']} working, {status['failed']} failed, {status['untested']} untested")

    def _index_merge(self) -> None:
        """Merge index with addons.txt file."""
        from py_stremio.components.collect.addon_index import get_addon_index
        from py_stremio.components.collect.addon_index import AddonIndex

        index = get_addon_index()
        print(f"  Merging index ({len(index)} addons) with addons.txt...")

        count = index.load_from_file("addons/addons.txt")
        print(f"  Loaded {count} new URLs from addons.txt")

        status = index.quick_status()
        print(f"  Index now: {status['total']} total, {status['working']} working, {status['failed']} failed")

        index.save_to_json_file(".addon_index.json")
        print("  Saved merged index to .addon_index.json")

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
        # Echo any --root / --key overrides so a network-share user
        # can see at a glance that their override actually took effect
        # (vs being silently ignored by a stale ``.env``).
        overrides = getattr(self, "cli_overrides", None) or {}
        if overrides:
            pretty = ", ".join(f"{k}={v!r}" for k, v in overrides.items())
            print(_c(f"  Overrides: {pretty}", YELLOW))

    def _menu(self) -> None:
        print()
        print(_c("Choose a step", ACCENT))
        print("  1  ⬇   Download missing episodes/movies")
        print("  2  📚  Update library (scan + metadata)")
        print("  3  📦  Addons (validate, find more)")
        print("  4  ⚙   Settings (debrid, threads)")
        print("  5  🚪  Exit")

    def _phase(self, title: str, detail: str | None = None) -> None:
        if title:
            print(_c(title, ACCENT), flush=True)
        if detail:
            print(f"  {detail}", flush=True)

    def _format_duration(self, seconds: float) -> str:
        """Format a duration in seconds into a human-readable string."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes, secs = divmod(int(seconds), 60)
        if minutes < 60:
            return f"{minutes}m {secs}s"
        hours, mins = divmod(minutes, 60)
        return f"{hours}h {mins}m {secs}s"

    def _print_library_elapsed(self, start_time: float, folder_count: int) -> None:
        """Print the elapsed time for the full library sync (scan + metadata).

        Called by the menu and CLI handlers right after ``metadata.run()``
        finishes so the user can see how long the entire "Update library"
        step took.  Skipped silently when the duration is negligible
        (< 0.05s) so callers running with ``quiet=True`` still get a clean
        output.
        """
        elapsed = time.monotonic() - start_time
        if elapsed < 0.05:
            return
        duration = self._format_duration(elapsed)
        print(_c(
            f"  ⏱  Update library finished in {duration} ({folder_count} folder(s))",
            DIM,
        ))

    def _index_status(self) -> None:
        """Show quick status of the addon index (instant, no I/O)."""
        from py_stremio.components.collect.addon_index import get_addon_index
        index = get_addon_index()
        status = index.quick_status()
        self._banner()
        print(_c("\n📊 Addon Index Status", ACCENT))
        print(f"  Total indexed:    {status['total']}")
        print(f"  Working:          {status['working']}")
        print(f"  Failed:           {status['failed']}")
        print(f"  Untested:        {status['untested']}")
        print()
        if status['total'] == 0:
            print("  Index is empty. Run `--index-update` to discover addons.")
        elif status['untested'] > 0:
            print(f"  {status['untested']} untested addons. Run `--index-update` to validate.")
        else:
            print("  All indexed addons have been validated.")

    def _index_update(self, ai: bool | set | None = False) -> None:
        """Update index: discover new addons and optionally use AI prediction."""
        from py_stremio.components.collect.addon_index import get_addon_index
        from py_stremio.components.collect.ai_discovery import IncrementalDiscovery, AIDiscovery
        use_ai = bool(ai) if isinstance(ai, (bool, set)) else False

        self._banner()
        print(_c("\n🔄 Updating Addon Index", ACCENT))

        index = get_addon_index()
        inc_discovery = IncrementalDiscovery(index)

        print("  Loading existing addons from addons.txt...")
        new_from_file = inc_discovery.sync_from_file("addons/addons.txt")
        if new_from_file > 0:
            print(f"  Loaded {new_from_file} new URLs from addons.txt")

        print("  Running source discovery...")
        new_from_sources = inc_discovery.discover_new_addons()
        if new_from_sources:
            print(f"  Discovered {len(new_from_sources)} new URLs from sources")
        else:
            print("  No new URLs from sources (all already indexed)")

        if use_ai:
            print("  Running AI pattern discovery...")
            ai_discovery = AIDiscovery(index)
            ai_found = ai_discovery.discover_and_add()
            if ai_found:
                print(f"  AI found {len(ai_found)} new URLs via pattern prediction")

        status = index.quick_status()
        print()
        print(f"  Index now has {status['total']} total URLs:")
        print(f"    - {status['working']} working")
        print(f"    - {status['failed']} failed")
        print(f"    - {status['untested']} untested")

        if status['untested'] > 0:
            print()
            print(f"  Validating {status['untested']} untested addons...")
            working, failed = inc_discovery.validate_only_untested()
            print(f"  Validation complete: {len(working)} working, {len(failed)} failed")
            status = index.quick_status()
            print(f"  Updated: {status['working']} working, {status['failed']} failed")

        print()
        print("  Saving index to .addon_index.json...")
        index.save_to_json_file(".addon_index.json")
        print("  Done.")

    def _index_save(self) -> None:
        """Save the addon index to .addon_index.json."""
        from py_stremio.components.collect.addon_index import get_addon_index
        index = get_addon_index()
        self._banner()
        print(_c("\n💾 Saving Addon Index", ACCENT))
        print(f"  Saving {len(index)} addons to .addon_index.json...")
        index.save_to_json_file(".addon_index.json")
        print(f"  Saved {len(index)} addons.")

    def _index_load(self) -> None:
        """Load the addon index from .addon_index.json."""
        from py_stremio.components.collect.addon_index import AddonIndex, set_addon_index
        self._banner()
        print(_c("\n📂 Loading Addon Index", ACCENT))
        print("  Loading from .addon_index.json...")
        index = AddonIndex.load_from_json_file(".addon_index.json")
        set_addon_index(index)
        status = index.quick_status()
        print(f"  Loaded {status['total']} addons:")
        print(f"    - {status['working']} working")
        print(f"    - {status['failed']} failed")
        print(f"    - {status['untested']} untested")

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
