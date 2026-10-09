# Milestones

0.1 source and next desktop milestone: keyboard desktop, file browsing/preview,
copy/move/rename/mkdir/name filtering and confirmed deletion; built-in UTF-8 editor
with open/save/search, bounded undo/redo, line numbers, conflict checks and
unsaved-work confirmation; process listing/inspection/search/sorting and confirmed
SIGTERM; read-only network addresses/routes/DNS/traffic; an ASCII text web browser
with HTTP/HTTPS, links, back/forward history, search and saved bookmarks;
ASCII layout and plain-text views, semantic regions, responsive columns/cards
from basic embedded/inline CSS grid/flex hints and aligned tables;
shell, Linux system information, confirmed power controls, live-build configuration,
ASCII interface by default, user-added terminal and graphical app launchers,
reviewed installation commands, minimal X11/Openbox/xterm session with native
graphical app windows, console recovery, branding, BIOS/UEFI test commands.
ISO release readiness requires actual build
and both firmware boot checks; see validation.md.

Next: validate the ISO on BIOS/UEFI, editor selection/clipboard support, Wi-Fi
connection management through NetworkManager, disk and battery views, settings,
and an apt frontend with privileged operation review.
Browser follow-ups include forms, a download workflow, broader layout rules and
external stylesheet handling. The current layout is an approximation using HTML
structure and a small CSS subset; JavaScript-dependent sites still need a
graphical browser.

After live boot is validated: normal authenticated installed sessions, first-boot
configuration, and a text installer using normal Linux account/password mechanisms.
Disk selection and partitioning must require explicit destructive-operation confirmation.

Later: ASCII controls for graphical-window focus/movement/resizing/workspaces,
package infrastructure,
snapshot-pinned releases, automated ISO builds, broader hardware testing and ARM64.
The disk installer, package frontend and remaining system apps are not yet
implemented. Native graphical windows use Openbox; custom ASCII window-management
controls are future work. Files, Text editor, Processes and read-only Network are
available now, alongside the ASCII browser. The browser draws pages with text
and character borders; native graphical browsers remain separate Apps launchers.
