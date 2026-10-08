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
replacement/logout prompts. All filesystem changes use temporary directories. They do not invoke power actions, format disks, or change host network configuration.
Process termination tests create their own disposable child, cancel a signal first,
then send confirmed SIGTERM only to that child. They never signal pre-existing host
processes. Backend fixtures cover races, permissions, unavailable data and rate resets.
Editor history tests cover saved baselines, cursor/content restoration and memory caps.

Check the Apps section in both a 60-column terminal and one at least 86 columns
wide: the desktop should show an Apps strip or panel, respectively, and selection
should remain visible after resizing. Use arrows and Tab to select each built-in
app, then Enter to open it. Open the full Apps page with A from the desktop and
F1 menu, and through the Apps menu entry. Search for an app name, description or
shortcut, clear the search, and check an unmatched query. Esc returns to the
desktop. Confirm that app descriptions and the search/keyboard hints fit at the
supported minimum size of 60 columns by 16 rows.

After building, boot **both** QEMU firmware modes. Check that the bootloader loads,
the live user reaches the desktop on tty1, F2 shows Welcome.txt, F3 returns after
`exit`, F4 reports sensible data, and power-menu cancellation does nothing.
Check Apps navigation and launching from the desktop and full Apps page.
Test F9 and E from Files: edit and save Welcome.txt, create a new document,
search, switch applications and return, and cancel an unsaved close. Test copy,
rename, move, mkdir and confirmed deletion on disposable files in the live user's
home directory. Test Ctrl+Z/Ctrl+Y across edits and saves. Open Processes through F1/F11, check
sorting/search/inspection, and cancel termination. Only test a confirmed signal on
a disposable process you launched for that check. Open Network through F1/F12,
compare addresses with `ip address`, verify routes/DNS and scroll the detail view.
Wi-Fi interface detection is implemented; Wi-Fi connection changes are deferred.
Re-run both firmware modes after desktop changes before releasing
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
