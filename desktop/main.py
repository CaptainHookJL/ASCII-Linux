#!/usr/bin/env python3
"""Run with python3 -m desktop.main from the repository root."""
import argparse
import curses
import locale
import sys
from desktop.core.desktop import Desktop
from desktop.utils.system import information


def main():
    parser = argparse.ArgumentParser(description='ASCII Linux desktop')
    rendering = parser.add_mutually_exclusive_group()
    rendering.add_argument('--ascii', dest='ascii_only', action='store_true',
                           help='use ASCII-only rendering (default)')
    rendering.add_argument('--unicode', dest='ascii_only', action='store_false',
                           help='allow Unicode borders and text in the terminal')
    parser.set_defaults(ascii_only=True)
    parser.add_argument('--check', action='store_true', help='check Linux interfaces without a terminal')
    args = parser.parse_args()
    if args.check:
        print('\n'.join(information()))
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error('an interactive terminal is required (or use --check)')
    locale.setlocale(locale.LC_ALL, '')
    try:
        curses.wrapper(lambda screen: Desktop(screen, args.ascii_only).run())
    except curses.error as error:
        print(f'Terminal initialization failed: {error}. Check TERM and terminal size.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
