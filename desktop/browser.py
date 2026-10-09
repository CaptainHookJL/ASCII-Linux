#!/usr/bin/env python3
"""Standalone ASCII browser: python3 -m desktop.browser [URL]."""
import argparse
import curses
import locale
import sys

from desktop.apps.web_browser import normalize_url
from desktop.core.desktop import Desktop


def main():
    parser = argparse.ArgumentParser(description='ASCII Browser for HTML and plain-text web pages')
    parser.add_argument('url', nargs='?', help='HTTP or HTTPS page to open')
    parser.add_argument('--ascii', action='store_true', help='ASCII rendering (always enabled)')
    parser.add_argument('--check', action='store_true', help='check browser imports and URL parsing without a terminal')
    args = parser.parse_args()
    try:
        url = normalize_url(args.url) if args.url else None
    except ValueError as error:
        parser.error(str(error))
    if args.check:
        print('ASCII Browser: Python HTTP/HTTPS, verified TLS, HTML/text rendering.')
        if url:
            print('URL: ' + url)
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error('an interactive terminal is required (or use --check)')
    locale.setlocale(locale.LC_ALL, '')

    def run(screen):
        desktop = Desktop(screen, ascii_only=True, browser_only=True)
        desktop.open_page('web')
        if url:
            desktop.web_browser_view.browser.navigate(url)
        desktop.run()

    try:
        curses.wrapper(run)
    except curses.error as error:
        print(f'Terminal initialization failed: {error}. Check TERM and terminal size.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
