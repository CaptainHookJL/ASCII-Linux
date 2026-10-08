# Validation and recovery

Run from the repository root. The installation workflow tests require `curl`
and download test payloads from a local HTTP server on `127.0.0.1`; they do not
contact external services. On Debian/Ubuntu, use `sudo apt install curl` if it
is missing:

```sh
python3 -m desktop.main --check
python3 -m unittest discover -s tests -v
bash -n build/*.sh
sh -n system/ascii-session system/ascii-console system/ascii-xsession \
  system/profile/ascii-session.sh
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
should remain visible after resizing. A fresh catalog should show an empty Apps
list, while Files, Text editor, Terminal, System information, Processes and
Network remain available through F1 and their function keys. Open full Apps with
A from the desktop and F1 menu, and through the Apps menu entry. Press N and
register a harmless command with a name, optional description and terminal mode;
for example, use `python3 /home/jacob/my-app/main.py` after creating that script. Use arrows
and Tab to select it, then Enter to launch and check the return to the desktop.
Confirm execution uses the user's home directory and that a path with spaces
works when quoted. Scripts must be executable or use an interpreter command.

Search for a name, description or command, clear the search, and check an
unmatched query. R reloads the catalog. Restart the desktop to check persistence
in `${XDG_DATA_HOME:-~/.local/share}/ascii-linux/apps.json`; relative XDG paths
should use the default under `~/.local/share`. D requests confirmed removal:
cancel once, then confirm and verify the launcher is gone while its program
remains. N registration must not install software or scan `.desktop` files.
Esc returns to the desktop. Confirm descriptions and keyboard hints fit at the
supported minimum size of 60 columns by 16 rows. Use a temporary catalog/home
when testing so existing user launchers are preserved.

Test I (Install from command) using a harmless local installer and a temporary
home. Enter a name, a Bash command that writes a disposable app script, a launch
command, optional description and terminal mode. The scrollable review must
display the complete install and launch commands, including quoted arguments. Cancel with
N or Esc and verify neither the command nor catalog changes ran. Confirm with
Y; verify the installer runs from the temporary home and the new launcher is
saved only after a zero exit status. Launch it and check its output. Invalid
launchers/catalogs must be rejected before the installer runs. Test nonzero
exit, pipeline failure and interruption: the desktop returns, no launcher is
added, and any files already written remain. Check that a pre-existing launcher
and an unsaved editor buffer survive the flow. Installation commands may
interactively ask for sudo, but automated checks should use local commands
without sudo, remote downloads or host package changes. The automated curl
download checks use only a local in-process HTTP server on `127.0.0.1`.

For a native-window check, start the dedicated session from a local login TTY
with `./system/ascii-session`, or run `python3 -m desktop.main` in an existing
graphical terminal. Add an installed graphical program with N and select `g`;
`xmessage 'ASCII Linux graphical app test'` is a simple example if `x11-utils`
is installed. Enter must open its window while the ASCII desktop remains usable.
Switch back with Alt+Tab, then navigate Files, open/edit a disposable document,
and return to Apps while the graphical program is still running. In the dedicated
session, Super+D must focus and raise the frameless ASCII desktop; Alt+Tab must
also return to the app. Closing the app must leave the desktop running, and
closing the desktop must end its dedicated session. Confirm a missing executable
or nonzero exit shows a status message without damaging the ASCII screen.
Switch a saved launcher's mode with M, restart the desktop and verify persistence;
records created before modes were added must retain terminal behavior. In a
console session without a display, graphical launching must show an error and
keep the desktop usable. No panel or graphical root menu should appear.

For a separate manual Brave check in that graphical session,
follow [Brave's official Linux installation page](https://brave.com/linux/).
Install `curl` first with `sudo apt install curl` if missing. In I, use name
`Brave`, installation command `curl -fsS https://dl.brave.com/install.sh | sh`,
launch command `brave-browser`, an optional description, and graphical mode `g`.
For a previously saved Brave launcher, use M to change it to graphical mode.
Review, then confirm; the official installer may ask for sudo. Run the ASCII desktop in a
terminal within the graphical session and launch Brave after successful
installation. The live-image configuration now includes X11, Openbox and xterm;
actual Brave installation and startup are unvalidated here.
The app installer workflow checks do not establish that Brave works on a host.

After building, boot **both** QEMU firmware modes in QEMU's graphical window.
Check that the bootloader loads, the live user reaches the frameless ASCII
desktop through the tty1 session, F2 shows Welcome.txt, F3 returns after
`exit`, F4 reports sensible data, and power-menu cancellation does nothing.
Check the initially empty Apps list, registration, navigation and launching from
the desktop and full Apps page. Saved launchers should survive a desktop restart;
the live image has no persistent storage by default and does not promise to
retain them after a reboot.
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
Check `cat /etc/os-release`, `whoami`, and `tty` from F3: ASCII Linux, ascii, and
an xterm pseudo-terminal such as `/dev/pts/0`. Verify native-window launching,
Alt+Tab and Super+D as above. Test `ascii.console` separately: it should reach
the ASCII interface directly on tty1 and reject graphical launchers without a
display. Use `./build/test-qemu.sh --console` for a terminal-only QEMU check,
then append `ascii.console` in the boot menu; the flag alone does not edit the
ISO's kernel command line. Append `ascii.safe` for a recovery shell instead.
Use Ctrl+Alt+F2 to confirm a recovery getty is reachable. Confirm reboot/shutdown
only in the disposable VM. Physical hardware, Wi-Fi, and VirtualBox/VMware/Boxes
require separate testing; QEMU alone does not establish those capabilities.

X11 startup failure falls back to the console interface. If the Python desktop
fails, ascii-console starts a recovery shell. Inspect:

```sh
journalctl -b
systemctl status getty@tty1.service
python3 -m desktop.main --check  # from /usr/lib/ascii-linux
/usr/local/bin/ascii-session --console
```

For a boot-time bypass, edit the boot menu's kernel command line and append
`ascii.safe` before starting the live system. tty1 then remains a normal shell.
Use `ascii.console` when you want the ASCII desktop without X11.
Other TTYs are unaffected. Avoid setting `ASCII_SESSION_ACTIVE` yourself unless
you intentionally want to bypass the profile hook. The desktop's F3 shell inherits
this flag so its login profile cannot recursively launch another desktop.

For build failure, retain the terminal output and inspect `build/work` before
cleaning. Never disable apt signature checking or TLS verification. Use a full
Debian VM if mounts/chroot are blocked. Run `sudo ./build/clean.sh` before retrying
a changed build; the source checkout and completed output artifacts are retained.
