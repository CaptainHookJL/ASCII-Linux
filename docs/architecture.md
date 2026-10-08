# Architecture and source map

`desktop/main.py` parses options and owns terminal initialization/restoration.
`desktop/core/desktop.py` renders the status bar, framed views, launcher, keyboard
controls, confirmation dialogs, and shell suspension/resumption.
`desktop/apps/file_manager.py` implements directory navigation and safe previews.
`desktop/utils/system.py` reads `/proc` and `/sys` with the logged-in user's rights.
`tests/test_desktop.py` exercises data access and the real curses UI in a pseudo-TTY.
A pseudo-TTY is a terminal pair used to automate keyboard input and screen output.

`build/build-iso.sh` configures Debian live-build, stages source and integration
files into its temporary tree, builds the ISO, and generates a SHA-256 checksum.
`build/clean.sh` removes temporary state through live-build's cleanup path.
`build/test-qemu.sh` launches the artifact with BIOS or OVMF UEFI firmware.
`live-build/config/package-lists/ascii.list.chroot` selects runtime packages.
`live-build/config/hooks/live/0100-branding.hook.chroot` sets release identity,
hostname, and console target, and checks the power sudoers syntax.

`system/ascii-session` launches the desktop and offers a recovery Bash on error.
`system/profile/ascii-session.sh` activates that session only on tty1 and supports
an `ascii.safe` kernel command-line override. `system/ascii-power` is the narrow
power-command sudo policy. `branding/` contains issue, MOTD, and ASCII logo.
`docs/live-welcome.txt` is copied into the live user's Documents directory.

Boot flow: firmware → Debian live bootloader → kernel/live-boot → systemd →
getty/live-config autologin → login profile → ascii-session → curses desktop.
A getty handles a Linux terminal and login; it is not a graphical display manager.
`multi-user.target` is systemd's normal non-graphical service target.
`/etc/os-release` identifies ASCII Linux while retaining `ID_LIKE=debian`.

Debian live-build supplies BIOS and UEFI bootloader templates. ISO application
and volume names identify ASCII Linux; an elaborate custom boot menu is future
work. Source and application logic remain separate from the rootfs integration.
