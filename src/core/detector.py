"""Detect breaking changes and deprecations announced on an API's docs page.

Most modern documentation sites (Stripe, Twilio, Shopify...) are built with
JavaScript frameworks. If you download them with a plain HTTP request you get
an almost empty HTML shell, because the real text is added by JavaScript *after*
the page loads in a browser.

To handle that, this module drives a real (invisible) browser with Playwright:
    1. open a headless Chromium browser
    2. navigate to the docs URL
    3. wait until the JavaScript has finished rendering the content
    4. hand the finished HTML to BeautifulSoup for keyword scanning

If Playwright is unavailable or fails for any reason, we quietly fall back to
the old `requests` approach so the tool keeps working.
"""

from typing import Dict, List

import requests
from bs4 import BeautifulSoup

# Words that usually show up when an API provider announces something that can
# break your integration. Kept lowercase so we can compare case-insensitively.
CHANGE_KEYWORDS: List[str] = [
    "breaking change",
    "deprecated",
    "deprecation",
    "removed",
    "no longer supported",
    "sunset",
    "end of life",
    "migrate",
    "upgrade required",
]

# Keywords in this list are treated as the more urgent kind of change.
BREAKING_KEYWORDS: List[str] = [
    "breaking change",
    "removed",
    "no longer supported",
    "sunset",
    "end of life",
]

# Some docs sites reject requests that do not look like a real browser.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS: Dict[str, str] = {"User-Agent": BROWSER_USER_AGENT}

# Extra seconds we give JavaScript to draw the content after the page "loads".
# Some sites finish the network requests but render a moment later.
EXTRA_RENDER_WAIT_MS = 2000


class APIChangeDetector:
    """Fetches an API documentation page and looks for signs of changes.

    Example:
        detector = APIChangeDetector("https://stripe.com/docs/upgrades")
        changes = detector.detect()
    """

    def __init__(self, docs_url: str, timeout: int = 30) -> None:
        """Store the page we want to watch.

        Args:
            docs_url: URL of the changelog / upgrades / release-notes page.
            timeout: How many seconds to wait for the page before giving up.
                A browser needs more time than a plain HTTP request, so the
                default is higher than before.
        """
        self.docs_url = docs_url
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def fetch_documentation(self) -> str:
        """Download the documentation page and return its fully rendered HTML.

        We try the browser first (so JavaScript-generated text is included),
        and only fall back to a plain HTTP download if the browser cannot run.

        Returns:
            The HTML of the page as a string.

        Raises:
            Exception: Only if BOTH the browser and the plain HTTP request
                fail. The error raised is the one from the HTTP fallback.
        """
        try:
            return self._fetch_with_playwright()
        except Exception as error:
            # Typical reasons we land here: Playwright is not installed, the
            # browser binaries were never downloaded ("playwright install"),
            # or the page took too long to render.
            print(f"[detector] Browser fetch failed ({error}). Trying plain HTTP...")
            return self._fetch_with_requests()

    def _fetch_with_playwright(self) -> str:
        """Open the page in a headless browser and return the rendered HTML."""
        # Imported here (not at the top of the file) so that a missing
        # Playwright install turns into a handled error instead of stopping
        # the whole program from starting.
        from playwright.sync_api import sync_playwright

        # Playwright counts time in milliseconds, we store seconds.
        timeout_ms = self.timeout * 1000

        # `with` makes sure Playwright shuts down even if something goes wrong.
        with sync_playwright() as playwright:
            # headless=True means the browser window is never shown on screen.
            browser = playwright.chromium.launch(headless=True)
            try:
                # A "context" is like a fresh, private browser profile.
                context = browser.new_context(user_agent=BROWSER_USER_AGENT)
                page = context.new_page()

                # Step 1: go to the page and wait for the initial HTML + DOM.
                page.goto(
                    self.docs_url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )

                # Step 2: wait until the network goes quiet, which usually
                # means the JavaScript has finished fetching its content.
                # Some pages poll the server forever and never go quiet, so a
                # timeout here is not a real failure - we just move on.
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:
                    print("[detector] Page never went idle; using what loaded so far.")

                # Step 3: a short extra pause for content that renders late.
                page.wait_for_timeout(EXTRA_RENDER_WAIT_MS)

                # page.content() gives us the HTML *as it currently looks*,
                # including everything JavaScript added. This is the key
                # difference from requests.get(), which only sees the shell.
                return page.content()
            finally:
                # Always close the browser so we don't leak processes.
                browser.close()

    def _fetch_with_requests(self) -> str:
        """Plain HTTP download - the old behaviour, kept as a safety net.

        Raises:
            requests.RequestException: On a network problem, timeout, or a
                4xx/5xx status code.
        """
        response = requests.get(
            self.docs_url,
            headers=DEFAULT_HEADERS,
            timeout=self.timeout,
        )
        # Turn any 4xx/5xx status into an exception so callers notice it.
        response.raise_for_status()
        return response.text

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse_changes(self, html_content: str) -> List[Dict[str, str]]:
        """Look through the page text for sentences that mention a change.

        We only inspect elements that normally hold readable content
        (headings, paragraphs, list items) so we skip scripts and styling.

        Args:
            html_content: Raw HTML returned by :meth:`fetch_documentation`.

        Returns:
            A list of dictionaries, one per match, each with:
                - "text":     the sentence/element text we matched on
                - "keyword":  the keyword that triggered the match
                - "severity": "breaking" or "notice"
                - "tag":      the HTML tag the text came from
        """
        soup = BeautifulSoup(html_content, "html.parser")

        changes: List[Dict[str, str]] = []
        seen_texts = set()  # avoids reporting the same sentence twice

        # Only these tags tend to contain human-readable announcements.
        content_tags = ["h1", "h2", "h3", "h4", "p", "li"]

        for element in soup.find_all(content_tags):
            # get_text() strips out nested tags and tidies up the whitespace.
            text = element.get_text(" ", strip=True)

            # Ignore empty or very short fragments such as nav links.
            if len(text) < 15:
                continue

            lowered = text.lower()

            for keyword in CHANGE_KEYWORDS:
                if keyword in lowered and text not in seen_texts:
                    seen_texts.add(text)
                    changes.append(
                        {
                            "text": text,
                            "keyword": keyword,
                            "severity": (
                                "breaking"
                                if keyword in BREAKING_KEYWORDS
                                else "notice"
                            ),
                            "tag": element.name,
                        }
                    )
                    # One match per element is enough; move to the next one.
                    break

        return changes

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def detect(self) -> List[Dict[str, str]]:
        """Fetch the docs page and return every change we could spot.

        This is the method other parts of the project should call.

        Returns:
            A list of change dictionaries (see :meth:`parse_changes`).
            Returns an empty list if the page cannot be fetched at all.
        """
        try:
            html_content = self.fetch_documentation()
        except Exception as error:
            # Catch everything: a browser can fail in many more ways than a
            # plain HTTP call. One unreachable page should never crash a run.
            print(f"[detector] Could not fetch {self.docs_url}: {error}")
            return []

        return self.parse_changes(html_content)


if __name__ == "__main__":
    # Quick manual test against Stripe's upgrades page.
    STRIPE_DOCS_URL = "https://stripe.com/docs/upgrades"

    detector = APIChangeDetector(STRIPE_DOCS_URL)
    detected_changes = detector.detect()

    print(f"Checked: {STRIPE_DOCS_URL}")
    print(f"Found {len(detected_changes)} possible change(s).\n")

    # Show only the first 10 so the terminal output stays readable.
    for index, change in enumerate(detected_changes[:10], start=1):
        print(f"{index}. [{change['severity']}] ({change['keyword']})")
        print(f"   {change['text'][:200]}\n")
