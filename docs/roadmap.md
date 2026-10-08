# Milestones

0.1 source and next desktop milestone: keyboard desktop, file browsing/preview,
copy/move/rename/mkdir/name filtering and confirmed deletion; built-in UTF-8 editor
with open/save/search, bounded undo/redo, line numbers, conflict checks and
unsaved-work confirmation; process listing/inspection/search/sorting and confirmed
SIGTERM; read-only network addresses/routes/DNS/traffic;
shell, Linux system information, confirmed power controls, live-build configuration,
console session, branding, BIOS/UEFI test commands. ISO release readiness requires actual build
and both firmware boot checks; see validation.md.

Next: validate the ISO on BIOS/UEFI, editor selection/clipboard support, Wi-Fi
connection management through NetworkManager, disk and battery views, settings,
and an apt frontend with privileged operation review.

After live boot is validated: normal authenticated installed sessions, first-boot
configuration, and a text installer using normal Linux account/password mechanisms.
Disk selection and partitioning must require explicit destructive-operation confirmation.

Later: multiwindow focus/movement/resizing/workspaces, package infrastructure,
snapshot-pinned releases, automated ISO builds, broader hardware testing and ARM64.
The installer, multiple windows, package frontend and remaining system apps are
not yet implemented. Files, Text editor, Processes and read-only Network are available now.
