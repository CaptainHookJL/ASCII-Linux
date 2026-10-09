import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import unittest
from unittest.mock import patch

from desktop.apps.web_browser import (BrowserError, Link, MAX_BODY_BYTES, Page,
                                      WebBrowser, fetch_page, normalize_url,
                                      render_html)


class _Pages(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', '/pages/index')
            self.end_headers()
            return
        if self.path == '/bad-redirect':
            self.send_response(302)
            self.send_header('Location', 'file:///etc/passwd')
            self.end_headers()
            return
        if self.path == '/missing':
            self.send_error(404)
            return
        headers = {}
        if self.path == '/pages/index':
            content = b'<title>Local page</title><p>Welcome <a href="next#part">next page</a>.</p>'
            mime = 'text/html; charset=utf-8'
        elif self.path == '/base':
            content = b'<head><base href="/elsewhere/"></head><a href="next">Base link</a>'
            mime = 'application/xhtml+xml'
        elif self.path == '/plain':
            content = 'caf\xe9\r\n\tindent\x1b[31m\x00'.encode('latin-1')
            mime = 'text/plain; charset=iso-8859-1'
        elif self.path == '/unknown-charset':
            content = 'caf\xe9'.encode()
            mime = 'text/plain; charset=not-a-real-charset'
        elif self.path == '/binary':
            content = b'%PDF fixture'
            mime = 'application/pdf'
        elif self.path == '/large-header':
            content = b''
            mime = 'text/html'
            headers['Content-Length'] = str(MAX_BODY_BYTES + 1)
        elif self.path == '/large-body':
            content = b'a' * (MAX_BODY_BYTES + 1)
            mime = 'text/plain'
        elif self.path == '/compressed':
            content = b'compressed fixture'
            mime = 'text/plain'
            headers['Content-Encoding'] = 'gzip'
        elif self.path == '/set-cookie':
            content = b'<p>Cookie set</p>'
            mime = 'text/html'
            headers['Set-Cookie'] = 'ascii_session=local; Path=/'
        elif self.path == '/read-cookie':
            content = self.headers.get('Cookie', 'none').encode()
            mime = 'text/plain'
        elif self.path == '/slow':
            content = b'<p>Old slow page</p>'
            mime = 'text/html'
        elif self.path == '/trickle':
            content = b'abcde'
            mime = 'text/plain'
        else:
            content = b'<p>Destination</p>'
            mime = 'text/html'
        self.send_response(200)
        self.send_header('Content-Type', mime)
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if self.path == '/slow':
            self.server.slow_started.set()
            self.server.slow_release.wait(3)
        try:
            if self.path == '/trickle':
                for byte in content:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(.025)
            else:
                self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass


@contextlib.contextmanager
def local_pages():
    server = ThreadingHTTPServer(('127.0.0.1', 0), _Pages)
    server.daemon_threads = True
    server.slow_started = threading.Event()
    server.slow_release = threading.Event()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Fixtures bypass machine proxy configuration; production respects it.
    with patch.dict('os.environ', {'no_proxy': '127.0.0.1', 'NO_PROXY': '127.0.0.1'}):
        try:
            yield server, f'http://127.0.0.1:{server.server_port}'
        finally:
            server.slow_release.set()
            server.shutdown()
            server.server_close()
            thread.join(2)


def wait_page(browser, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if browser.poll():
            return
        time.sleep(.005)
    raise AssertionError('Browser did not complete its request.')


def fixture_page(url, text='fixture'):
    return Page(url, text, (text,))


class URLTests(unittest.TestCase):
    def test_addresses_and_relative_unicode_links(self):
        self.assertEqual(normalize_url('example.com'), 'https://example.com/')
        self.assertEqual(normalize_url('localhost:8080/test'), 'https://localhost:8080/test')
        self.assertEqual(normalize_url('//example.com/a'), 'https://example.com/a')
        self.assertEqual(normalize_url('../next?q=1#part', 'https://example.com/one/two'),
                         'https://example.com/next?q=1#part')
        self.assertEqual(normalize_url('https://m\xfcnich.example/\xe9t\xe9'),
                         'https://xn--mnich-kva.example/%C3%A9t%C3%A9')
        self.assertEqual(normalize_url('https://[::1]:8443/'), 'https://[::1]:8443/')

    def test_invalid_or_non_web_addresses(self):
        for value in ('', 'file:///etc/passwd', 'javascript:alert(1)', 'data:text/plain,no',
                      'mailto:a@example.com', 'https://a:0/', 'https://a:65536/',
                      'https://a:word/', 'https:///', 'https://user:secret@example.com/',
                      'https://a:/', 'https://[::1]suffix/', 'https://[::1]:/',
                      'https://user@example.com/', 'https://bad host/',
                      'https://example.com/\x1b[31m', 'https://example.com/\npath',
                      'https://example.com/\u202eabc', 'http://[broken/',
                      'https://a\\b/', 'https://a/%xy', 'https://a/' + 'x' * 8192):
            with self.subTest(value=value), self.assertRaises(BrowserError):
                normalize_url(value)


class RenderingTests(unittest.TestCase):
    def test_html_blocks_links_base_alt_and_ascii(self):
        page = render_html('''<head><title>Caf&eacute; &amp; docs</title>
            <base href="/manual/"><style>SECRET STYLE</style></head>
            <h1>Welcome</h1><p>Hello\nworld <a href="one?q=1#part">read <b>more</b></a>.</p>
            <ul><li>First<li>Second</ul><table><tr><th>Name</th><th>Value</th></tr>
            <tr><td>A</td><td>1</td></tr></table><img src="no-fetch.png" alt="Logo">
            <pre>first\n  second\n\tthird</pre><script>SECRET SCRIPT</script>
            <div hidden><b>SECRET HIDDEN</b></div><div aria-hidden="true">SECRET ARIA</div>
            <p style="display: none">SECRET DISPLAY</p><a href="javascript:no()">Unsupported</a>
            <a href="../last">Last</a><input type="text"><input type="hidden">''',
                           'https://example.com/articles/index')
        self.assertEqual(page.title, 'Cafe & docs')
        self.assertIn('# Welcome', page.lines)
        self.assertIn('Hello world read more [1].', page.lines)
        self.assertIn('* First', page.lines)
        self.assertIn('* Second', page.lines)
        self.assertIn('Name | Value', page.lines)
        self.assertIn('A | 1', page.lines)
        self.assertIn('  second', page.lines)
        self.assertIn('    third', page.lines)
        self.assertIn('[image: Logo]', page.text)
        self.assertNotIn('SECRET', page.text)
        self.assertNotIn('javascript:', page.text)
        self.assertEqual(page.links, (
            Link(1, 'read more', 'https://example.com/manual/one?q=1#part'),
            Link(2, 'Last', 'https://example.com/last')))
        self.assertTrue(page.text.isascii())

    def test_terminal_controls_and_incomplete_or_valueless_html(self):
        page = render_html('<p style aria-hidden>Safe\x1b[31m\x00\u202e <a href="/x"><img alt></a><a href="/y">Open',
                           'https://example.com/')
        self.assertNotIn('\x1b', page.text)
        self.assertNotIn('\x00', page.text)
        self.assertNotIn('\u202e', page.text)
        self.assertEqual(len(page.links), 2)
        self.assertIn('Open [2]', page.text)

    def test_optional_head_body_endings_and_multiline_link_labels(self):
        for body in ('<body><h1>Visible heading</h1><p>Visible paragraph</p>',
                     '<h1>Visible heading</h1><p>Visible paragraph</p>',
                     '<p>Visible paragraph</p>'):
            page = render_html('<head><title>Example</title>' + body
                               + '<a href="/next">First<br>Second</a>',
                               'https://example.com/')
            self.assertEqual(page.title, 'Example')
            self.assertIn('Visible paragraph', page.text)
            self.assertEqual(page.links[0].label, 'First Second')
        page = render_html('<head><title>Title</title>Plain body without tags',
                           'https://example.com/')
        self.assertIn('Plain body without tags', page.text)

    def test_relative_base_invalid_links_and_marker_limit(self):
        with patch('desktop.apps.web_browser.MAX_LINKS', 2):
            page = render_html('<base href="file:///tmp/"><a href="a">A</a>'
                               '<a href="https://user:pass@example.com">Secret</a>'
                               '<a href="#section">Section</a><a href="b">B</a>',
                               'https://example.com/docs/index')
        self.assertEqual([link.url for link in page.links],
                         ['https://example.com/docs/a', 'https://example.com/docs/index#section'])
        self.assertNotIn('[3]', page.text)


class FetchTests(unittest.TestCase):
    def test_redirect_relative_links_base_and_http_charsets(self):
        with local_pages() as (_, base):
            page = fetch_page(base + '/redirect')
            self.assertEqual(page.url, base + '/pages/index')
            self.assertEqual(page.title, 'Local page')
            self.assertEqual(page.links[0].url, base + '/pages/next#part')
            self.assertEqual(fetch_page(base + '/base').links[0].url, base + '/elsewhere/next')
            plain = fetch_page(base + '/plain')
            self.assertEqual(plain.lines, ('cafe', '    indent[31m'))
            self.assertTrue(plain.text.isascii())
            self.assertEqual(fetch_page(base + '/unknown-charset').text, 'cafe')

    def test_http_failure_unsupported_types_and_bounded_body(self):
        with local_pages() as (_, base):
            for path, expected in (('/missing', 'HTTP 404'), ('/binary', 'application/pdf'),
                                   ('/large-header', '2 MiB'), ('/large-body', '2 MiB'),
                                   ('/compressed', 'compressed'), ('/bad-redirect', 'HTTP')):
                with self.subTest(path=path), self.assertRaisesRegex(BrowserError, expected):
                    fetch_page(base + path)

    def test_deadline_handles_slow_drip_body(self):
        with local_pages() as (_, base), patch('desktop.apps.web_browser.FETCH_DEADLINE', .04):
            with self.assertRaisesRegex(BrowserError, 'too long'):
                fetch_page(base + '/trickle')

    def test_browser_session_cookies_are_not_shared(self):
        with local_pages() as (_, base):
            first, second = WebBrowser(), WebBrowser()
            try:
                first.navigate(base + '/set-cookie')
                wait_page(first)
                first.navigate(base + '/read-cookie')
                wait_page(first)
                self.assertEqual(first.page.text, 'ascii_session=local')
                second.navigate(base + '/read-cookie')
                wait_page(second)
                self.assertEqual(second.page.text, 'none')
            finally:
                first.close()
                second.close()


class NavigationTests(unittest.TestCase):
    def test_history_failure_reload_and_navigation_branch(self):
        calls = []

        def fetch(url, cancel):
            calls.append(url)
            if url.endswith('/failure'):
                raise BrowserError('HTTP 404: fixture')
            return fixture_page(url, str(len(calls)))

        browser = WebBrowser(fetch)
        self.addCleanup(browser.close)
        for path in ('one', 'two', 'three'):
            browser.navigate('https://example.com/' + path)
            wait_page(browser)
        self.assertTrue(browser.back())
        self.assertEqual(browser.page.url, 'https://example.com/two')
        self.assertTrue(browser.can_forward)
        browser.navigate('https://example.com/failure')
        wait_page(browser)
        self.assertIn('404', browser.error)
        self.assertEqual(browser.page.url, 'https://example.com/two')
        self.assertTrue(browser.can_forward)
        browser.reload()
        wait_page(browser)
        self.assertEqual(browser.page.text, '5')
        self.assertEqual(len(browser._history), 3)
        self.assertTrue(browser.forward())
        self.assertEqual(browser.page.text, '3')
        browser.back()
        browser.navigate('https://example.com/branch')
        wait_page(browser)
        self.assertFalse(browser.can_forward)
        self.assertEqual(len(browser._history), 3)

    def test_real_slow_cancel_and_latest_request_never_overwrite_page(self):
        with local_pages() as (server, base):
            browser = WebBrowser()
            try:
                browser.navigate(base + '/pages/index')
                wait_page(browser)
                saved = browser.page
                browser.navigate(base + '/slow')
                self.assertTrue(server.slow_started.wait(2))
                self.assertTrue(browser.busy)
                started = time.monotonic()
                self.assertTrue(browser.cancel())
                self.assertLess(time.monotonic() - started, .1)
                self.assertFalse(browser.busy)
                self.assertIs(browser.page, saved)
                browser.navigate(base + '/plain')
                server.slow_release.set()
                wait_page(browser)
                self.assertEqual(browser.page.url, base + '/plain')
                self.assertEqual(len(browser._history), 2)
                self.assertFalse(browser.poll())
            finally:
                browser.close()

    def test_only_latest_pending_request_runs_on_one_worker(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        threads = []

        def fetch(url, cancel):
            calls.append(url)
            threads.append(threading.get_ident())
            if url.endswith('/first'):
                started.set()
                release.wait(2)
            return fixture_page(url)

        browser = WebBrowser(fetch)
        self.addCleanup(browser.close)
        browser.navigate('https://example.com/first')
        self.assertTrue(started.wait(1))
        for path in ('second', 'third', 'latest'):
            browser.navigate('https://example.com/' + path)
        release.set()
        wait_page(browser)
        self.assertEqual(calls, ['https://example.com/first', 'https://example.com/latest'])
        self.assertEqual(len(set(threads)), 1)
        self.assertEqual(browser.page.url, 'https://example.com/latest')

    def test_cached_back_cancels_pending_and_links_follow(self):
        started, release = threading.Event(), threading.Event()

        def fetch(url, cancel):
            if url.endswith('/slow'):
                started.set()
                release.wait(2)
            return Page(url, 'fixture', ('fixture',), (Link(1, 'next', 'https://example.com/next'),))

        browser = WebBrowser(fetch)
        self.addCleanup(browser.close)
        browser.navigate('https://example.com/one')
        wait_page(browser)
        browser.follow(1)
        wait_page(browser)
        with self.assertRaisesRegex(BrowserError, 'link number'):
            browser.follow(99)
        browser.navigate('https://example.com/slow')
        self.assertTrue(started.wait(1))
        self.assertTrue(browser.back())
        release.set()
        time.sleep(.02)
        self.assertFalse(browser.poll())
        self.assertFalse(browser.busy)
        self.assertEqual(browser.page.url, 'https://example.com/one')

    def test_history_entry_and_byte_budgets(self):
        with patch('desktop.apps.web_browser.MAX_HISTORY', 3):
            browser = WebBrowser(lambda url, cancel: fixture_page(url))
            self.addCleanup(browser.close)
            for number in range(5):
                browser.navigate(f'https://example.com/{number}')
                wait_page(browser)
            self.assertEqual(len(browser._history), 3)
            self.assertEqual(browser._index, 2)
            self.assertEqual(browser._history[0].url, 'https://example.com/2')
        with patch('desktop.apps.web_browser.MAX_HISTORY_BYTES', 250):
            browser = WebBrowser(lambda url, cancel: fixture_page(url, 'x' * 100))
            self.addCleanup(browser.close)
            browser.navigate('https://example.com/one')
            wait_page(browser)
            browser.navigate('https://example.com/two')
            wait_page(browser)
            self.assertEqual(len(browser._history), 1)
            self.assertEqual(browser.page.url, 'https://example.com/two')

    def test_invalid_input_preserves_current_request_and_closed_browser(self):
        browser = WebBrowser(lambda url, cancel: fixture_page(url))
        browser.navigate('https://example.com/one')
        with self.assertRaises(BrowserError):
            browser.navigate('file:///etc/passwd')
        wait_page(browser)
        self.assertEqual(browser.page.url, 'https://example.com/one')
        browser.close()
        with self.assertRaisesRegex(BrowserError, 'closed'):
            browser.navigate('https://example.com/two')


if __name__ == '__main__':
    unittest.main()
