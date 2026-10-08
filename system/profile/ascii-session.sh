# Only tty1 launches the desktop; other TTYs and remote shells remain standard.
if [ -z "${ASCII_SESSION_ACTIVE:-}" ] && [ "$(tty 2>/dev/null)" = /dev/tty1 ]; then
    case " $(cat /proc/cmdline) " in
        *' ascii.safe '*) printf 'ASCII Linux safe mode: console shell.\n' ;;
        *) export ASCII_SESSION_ACTIVE=1; exec /usr/local/bin/ascii-session ;;
    esac
fi
