# Current validation — 2026-10-09

Source checks ran in a Debian 13 amd64 cloud container. They establish desktop
and browser behavior, not a bootable ISO release.

## ASCII layout prototype

- All **263 unittest tests passed**, with no skips: the prior 227-test baseline
  plus 19 layout-renderer tests, 11 document-model tests, three real-terminal
  layout workflows and three browser-view tests.
- Model and renderer checks cover semantic regions, embedded/inline CSS hints,
  hidden content, weighted grid/flex columns, narrow reflow, cards, table cells
  and spans, preformatted content, malformed/deep structure, resource limits
  and lossless flowing-text fallback. Link numbering and history-size accounting
  retain the existing bounds.
  Cumulative output checks stop rendering sibling boxes before excessive
  padded content can accumulate, including wide and narrow grid layouts.
- Real curses workflows draw wide columns and aligned tables, toggle L without
  refetching, follow selected links, reflow search results at 60 columns and
  preserve an unsaved editor draft across desktop tools. View tests preserve
  the selected search occurrence across layout/text mode changes and report a
  text fallback when a layout is too complex. A tiny-terminal regression loads
  HTML and plain text at 5 columns by 7 rows, bounds reflow to the minimum usable
  width, then restores normal display at 60 columns by 16 rows. These checks use
  disposable local HTTP fixtures and temporary homes.
- Desktop/browser `--check`, shell syntax checks and `git diff --check` passed.

The browser now defaults to an approximate ASCII layout for HTML pages, with L
switching to flowing text from the same cached page. Semantic HTML regions,
basic embedded/inline grid/flex hints, bordered cards and aligned tables shape
the output. Most CSS and all external stylesheets remain unsupported.

The included [browser-layout-demo.html](browser-layout-demo.html) parsed with
seven valid numbered links and an immutable layout tree. Its text was ASCII,
and retained page data counted toward the existing history budget. Rendering
at widths of 100 and 54 cells produced 51 and 75 ASCII-only rows, respectively,
within the requested widths. The wider output put aside/main regions and the
two cards side by side; the narrower output stacked them. Both preserved
headings, card content, table cells and the footer. This establishes the
included fixture's approximate layout; it does
not establish fidelity to arbitrary sites or a full CSS rendering engine.

A real HTTPS fetch of `https://pypi.org/help/` succeeded with normal certificate
verification. It retained layout structure, 251 links and 276,730 bytes charged
to page history. Layout rendering produced 1,020 rows at 100 cells and 1,454
rows at 54 cells, with ASCII-only output bounded to those widths. This verifies
one external page alongside the local fixture; it does not establish every
site's accessibility or layout fidelity. Layout search works within rendered
rows; phrases split across rows can be searched using the flowing text view.

## Previously verified ASCII browser baseline

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

The current browser approximates HTML layout using semantic structure and a
small subset of embedded/inline CSS hints. It does not fetch external
stylesheets, execute JavaScript, fetch images, submit forms or download files.
Image alt text uses placeholders. Full CSS rendering and JavaScript-dependent
sites require a graphical browser or future browser work.

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
