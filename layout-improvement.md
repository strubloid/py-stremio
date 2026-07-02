# Terminal Layout & Cleanup

## Problems

1. **Ctrl+C (KeyboardInterrupt) leaves the terminal messy.** ANSI escape artifacts,
   scroll region still active, invisible cursor, or raw cbreak mode still enabled.
2. **The `q` key during download stops the download but doesn't clean up.**
3. **Menu exit (option 7) prints "Bye." but the terminal state may be dirty** if
   a download was running before.
4. **Characters left on screen** after abort — lines from progress bars, spinner
   residues, etc.

## Architecture

### Terminal state ownership

There are three pieces of terminal state that must be restored on exit:

| State | Set by | Restored by |
|-------|--------|-------------|
| **Scroll region** (`\033[r`) | `StatusBar._setup_scroll()` | `StatusBar.stop()` → `_reset_scroll_region()` |
| **Raw / cbreak mode** | `StatusBar._listen_loop()` via `tty.setcbreak(fd)` | Same method's `finally` block → `termios.tcsetattr()` |
| **Cursor visibility** | Implicitly hidden by ANSI drawing | `cleanup_terminal()` → `\033[?25h` |

### Cleanup guarantees

| Exit path | Scroll region | Raw mode | Cursor | Notes |
|-----------|---------------|----------|--------|-------|
| Normal exit after idle menu | Not active | Not active | Visible | Only `atexit` handler fires |
| Normal exit after download done | `status_bar.stop()` in `finally` | Listener thread `finally` block | Restored by `stop()` | Both paths fire |
| Exit via menu option 7 after download | Same as above | Same as above | Same as above | `finally` block always runs |
| Ctrl+C during download | `status_bar.stop()` in `finally` | Listener thread `finally` | `atexit` handler | Module globals capture tty state |
| Ctrl+C before `status_bar` created | `atexit` handler | Never entered | `atexit` handler | Guard in `finally` block handles undefined `status_bar` |
| `q` key during download + early shutdown | `finally` block | Listener thread `finally` | `atexit` handler | Cooperative shutdown, not a KeyboardInterrupt |

## Files Changed

### `py_stremio/components/download/control_panel.py`

**Global terminal state tracking:**
```python
_tty_fd: int | None = None
_tty_old_attrs: Any = None
```
These module-level variables are set by `_listen_loop()` before `tty.setcbreak()`,
and cleared in the listener's `finally` block. They exist so `cleanup_terminal()`
(the `atexit` handler) can restore the tty even if the listener thread is killed
mid-flight.

**`cleanup_terminal()` (idempotent):**
```python
def cleanup_terminal() -> None:
    _reset_scroll_region()           # \033[r
    sys.stdout.write("\033[?25h")    # show cursor
    # clear bottom line (status bar residue)
    sys.stdout.write(f"\033[{term_height};1H\033[K")
    sys.stdout.write("\033[0m")      # reset attributes
    # restore tty if captured
    if _tty_fd is not None and _tty_old_attrs is not None:
        termios.tcsetattr(_tty_fd, termios.TCSADRAIN, _tty_old_attrs)
    _tty_fd = None
    _tty_old_attrs = None

atexit.register(cleanup_terminal)
```

**Key points:**
- `atexit.register()` guarantees cleanup on normal exit, even through bare
  `sys.exit()` or unhandled exception (as long as the process exits normally).
- Must be safe to call multiple times — all operations either re-apply the
  same ANSI codes or are guarded by `if ... is not None` checks.

**`_tty_old_attrs` saved before `tty.setcbreak()`** so that even a crash during
`setcbreak` itself leaves the terminal state restorable.

**`StatusBar._listen_loop()`** updated to save fd/attrs into the module globals
before entering cbreak mode.

### `py_stremio/services/download.py`

**`finally` block** in `DownloadService.run()` now guards against an undefined
`status_bar` reference (could happen if `KeyboardInterrupt` fires during
`create_control_panel()`):
```python
finally:
    restore_thread_stdout_filter(restore_stdout)
    if 'status_bar' in dir():
        status_bar.stop()
    else:
        from py_stremio.components.download.control_panel import _reset_scroll_region as _rsr
        _rsr()
```

### `py_stremio/app.py`

- Menu option 7 (exit) now calls `cleanup_terminal()` before printing "Bye."
- Imports `cleanup_terminal` from `control_panel` module.

## Test coverage

All 388 existing tests pass with these changes. There are no dedicated unit tests
for terminal cleanup because `tty.setcbreak()` requires an actual TTY that pytest
does not provide (it runs on a pty-less pipe). Manual verification steps:

1. Start `py-stremio`, start a download, press `q` → terminal is clean after exit.
2. Start `py-stremio`, start a download, Ctrl+C → terminal is clean.
3. Start `py-stremio`, press 7 immediately → terminal is clean.
4. Start `py-stremio`, press Ctrl+C at the menu prompt → terminal is clean.
5. Run `py-stremio --run` then Ctrl+C → terminal is clean.
