# Current validation — 2026-10-09

Source checks ran in a Debian 13 amd64 cloud container. They establish desktop
and browser behavior, not a bootable ISO release.

## ASCII browser update

- All **227 unittest tests passed**, with no skips: the 178-test desktop/session
  baseline plus 16 browser backend tests, 17 bookmark-store tests, 11 browser-view
  tests and five real-terminal browser workflows.
- Local HTTP fixtures cover HTML and plain text, headings/lists/preformatted
  content, entities and Unicode-to-ASCII text, omitted scripts/styles, numbered
  links, redirects and relative/base URLs, encodings, HTTP errors, unsupported
  MIME types and both declared and streamed 2 MiB limits. Slow-response tests
  check deadlines, cancellation and rejection of obsolete results. Cached
  history and browser-session cookie isolation are covered.
- Actual curses workflows load and follow pages, use back/forward and find/next,
  recover from a 404, cancel a delayed request and preserve an unsaved editor
  buffer across application switches. They run the standalone browser, reopen
  saved bookmarks after a fresh session, scroll at 60 columns by 16 rows,
  resize below the supported size and cancel a prompt. All test pages are served
  by an in-process localhost server. A real Apps launch from the temporary home
  runs the source wrapper, loads a page, then restores the parent desktop when
  the standalone browser exits. Bookmark/filesystem changes use temporary
  homes. These checks do not install software or change host network settings.
- Bookmark checks cover an empty store, XDG paths, duplicates, limits, malformed
  records, unsafe files, external changes, failed atomic writes and cleanup.
  View checks cover wrapping without lost text, selection, find results,
  bookmark navigation/removal and ASCII rendering, including when the rest of
  the desktop uses optional Unicode mode. Opening the built-in browser leaves
  the user Apps catalog empty.
- Real HTTPS requests through the browser backend succeeded with normal
  certificate verification: `https://pypi.org/help/` rendered 651 logical ASCII
  lines and 251 links, and GitHub raw repository files displayed as ASCII plain
  text. The cloud proxy returned HTTP 403 for example.com and Wikipedia; access
  to every external site is not established. Browser `--check` passed without
  making a network request.
- Desktop and browser module checks, the source wrapper's `--check`, all build
  and session shell syntax checks, and `git diff --check` passed.

The browser does not execute JavaScript, render CSS, fetch images, submit forms
or download files. Image alt text uses placeholders. Those capabilities, and
JavaScript-dependent sites, require a graphical browser or future browser work.

## Previously verified desktop and native windows

The earlier 178-test baseline passed on 2026-10-08. It covers file operations,
UTF-8 editing and bounded undo/redo, process inspection and confirmed SIGTERM to
disposable test children, read-only network data, user app registration,
reviewed local installers, terminal/graphical launch modes, session fallback and
QEMU command construction. QEMU argument-capture tests do not boot a VM.

The actual Openbox/xterm session also ran on a headless Xorg dummy display.
Its frameless ASCII terminal filled the display; a native `xmessage` window
opened above it. Alt+Tab switched both ways, and Super+D returned to the ASCII
desktop. The real Apps UI registered and launched that graphical window while
the desktop remained usable and saved a temporary editor document. App close
left the desktop running; confirmed desktop logout cleaned up its own terminal
and window manager while preserving the independent X server and unrelated
test window. This verifies native X11 windows separately from ISO startup.

## Release checks still required

Brave installation, repository/package setup and actual Brave startup remain
unverified. The official website and installer URL previously returned HTTP 403
in this cloud environment; no remote installer was run.

An earlier ISO build attempt stopped at the root prerequisite. No ISO artifact
has been produced or boot-tested here. live-build execution, chroot hooks,
BIOS/UEFI boot, live autologin, firmware, physical hardware and persistent storage
remain unverified. Use a Debian amd64 VM with root and mount/chroot support to
finish the checks in [testing.md](testing.md). Rebuild earlier images to include
the new browser; source and native-window checks do not establish that an image
boots or that hardware networking works.
