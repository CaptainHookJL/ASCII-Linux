# Validation and recovery

Run from the repository root:

```sh
python3 -m desktop.main --check
python3 -m unittest discover -s tests -v
bash -n build/*.sh
sh -n system/ascii-session system/profile/ascii-session.sh
```

The tests use real Linux data and temporary files, and start the desktop inside
a pseudo-terminal. They navigate the launcher, files, previews, and system page;
launch and exit Bash; cancel a reboot; and confirm logout. The extended PTY suite
copies/moves/renames files, creates folders, filters names, cancels and confirms
deletion, opens/edits/saves documents, searches, saves under another name, preserves
buffers across application switches and terminal resizing, and cancels unsaved
replacement/logout prompts. All filesystem changes use temporary directories. They do not invoke
power actions, format disks, or change host configuration.

After building, boot **both** QEMU firmware modes. Check that the bootloader loads,
the live user reaches the desktop on tty1, F2 shows Welcome.txt, F3 returns after
`exit`, F4 reports sensible data, and power-menu cancellation does nothing.
Test F9 and E from Files: edit and save Welcome.txt, create a new document,
search, switch applications and return, and cancel an unsaved close. Test copy,
rename, move, mkdir and confirmed deletion on disposable files in the live user's
home directory. Re-run both firmware modes after desktop changes before releasing
an updated ISO; earlier images do not contain these changes.
Check `cat /etc/os-release`, `whoami`, and `tty` from F3: ASCII Linux, ascii, tty1.
Use Ctrl+Alt+F2 to confirm a recovery getty is reachable. Confirm reboot/shutdown
only in the disposable VM. Physical hardware, Wi-Fi, and VirtualBox/VMware/Boxes
require separate testing; QEMU alone does not establish those capabilities.

If the desktop fails, ascii-session starts a recovery shell. Inspect:

```sh
journalctl -b
systemctl status getty@tty1.service
python3 -m desktop.main --check  # from /usr/lib/ascii-linux
/usr/local/bin/ascii-session --ascii
```

For a boot-time bypass, edit the boot menu's kernel command line and append
`ascii.safe` before starting the live system. tty1 then remains a normal shell.
Other TTYs are unaffected. Avoid setting `ASCII_SESSION_ACTIVE` yourself unless
you intentionally want to bypass the profile hook. The desktop's F3 shell inherits
this flag so its login profile cannot recursively launch another desktop.

For build failure, retain the terminal output and inspect `build/work` before
cleaning. Never disable apt signature checking or TLS verification. Use a full
Debian VM if mounts/chroot are blocked. Run `sudo ./build/clean.sh` before retrying
a changed build; the source checkout and completed output artifacts are retained.
