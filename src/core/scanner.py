"""Scan a project's Python files for places where an API is used.

Once :mod:`detector` tells us an API has changed, we still need to know which
lines of our own code care about it. This module does that lookup: give it a
few keywords (a package name, an endpoint, a method call) and it reports every
matching line in the project.

Two options make the results much less noisy, and both are worth knowing about:

* ``skip_comments=True`` (the default) ignores matches that only appear inside
  comments or strings. A docstring that says "we used to call stripe here" is
  prose, not code, and fixing it is not urgent.
* ``whole_word=True`` requires the keyword to be a complete word, so the
  keyword "stripe" stops matching a variable named ``stripewrapper``.

You can also run this file directly against any folder - see the command line
interface at the bottom.
"""

import argparse
import os
import re
import tokenize
from typing import Dict, List, Optional, Tuple

from src.core.paths import is_fixed_output
from src.domain.change_event import ChangeEvent
from src.domain.finding import CodeLocation, Finding
from src.domain.ids import derive_finding_id

# Folders we never want to walk into. These hold installed packages or build
# artefacts, so matches in them are not our code and would drown out the rest.
IGNORED_DIRS = {"venv", ".venv", "__pycache__", ".git"}

# Keywords the command line interface looks for when you do not name any.
DEFAULT_KEYWORDS = ["stripe", "openai", "requests.get"]

# The token types that hold prose rather than running code. COMMENT covers
# "# like this"; STRING covers "quoted text" and docstrings.
MASKED_TOKEN_TYPES = {tokenize.COMMENT, tokenize.STRING}

# Python 3.12+ splits f-strings into their own token types. FSTRING_MIDDLE is
# the literal text between the braces - the part that is prose. The `{...}`
# pieces stay as normal code tokens, which is exactly what we want: real code
# inside an f-string still counts as real code. We look the names up instead of
# importing them so this file also works on older Python versions.
for _token_name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
    if hasattr(tokenize, _token_name):
        MASKED_TOKEN_TYPES.add(getattr(tokenize, _token_name))

# Stand-in for "to the end of the line" when we record a masked region.
END_OF_LINE = 10**9


class CodebaseScanner:
    """Searches every ``.py`` file under a project for API usage.

    Example:
        scanner = CodebaseScanner("/path/to/project")
        findings = scanner.scan_for_api_usage(["stripe", "requests.get"])
        print(f"{len(findings)} match(es) in {scanner.files_scanned} file(s)")
    """

    def __init__(
        self,
        project_root: str = ".",
        extra_ignored_dirs: list[str] | None = None,
        skip_comments: bool = True,
        whole_word: bool = False,
    ) -> None:
        """Remember which folder to scan and how picky to be about matches.

        Args:
            project_root: Folder to search. Defaults to the current directory.
            extra_ignored_dirs: Extra folder *names* to skip, on top of the
                built-in defaults (venv, .venv, __pycache__, .git). Names, not
                paths - passing ["tests"] skips every folder called "tests".
            skip_comments: When True (the default), a match is only reported if
                it appears in real code. Matches that sit entirely inside
                comments or strings - docstrings included - are skipped.
            whole_word: When True, the keyword must be a complete word. With
                this on, "stripe" no longer matches "stripewrapper". Defaults
                to False, which is the plain substring behaviour.
        """
        # Store the absolute path so results are unambiguous no matter where
        # the script was started from.
        self.project_root = os.path.abspath(project_root)

        # Combine the built-in ignores with anything the caller added. We copy
        # IGNORED_DIRS with set(...) so we never modify the shared default.
        self.ignored_dirs = set(IGNORED_DIRS)
        if extra_ignored_dirs:
            self.ignored_dirs.update(extra_ignored_dirs)

        self.skip_comments = skip_comments
        self.whole_word = whole_word

        # How many files the most recent scan actually read. Callers use this
        # to say "3 matches across 12 files" instead of just "3 matches".
        # It stays 0 until scan_for_api_usage runs.
        self.files_scanned = 0

    def find_python_files(self) -> List[str]:
        """Walk the project and collect every ``.py`` file worth scanning.

        Folders in :attr:`ignored_dirs` are skipped entirely.

        Returns:
            A list of absolute paths to Python files.
        """
        python_files: List[str] = []

        for current_dir, subdirs, filenames in os.walk(self.project_root):
            # Editing `subdirs` in place tells os.walk not to descend into
            # those folders at all, which is much faster than filtering later.
            subdirs[:] = [d for d in subdirs if d not in self.ignored_dirs]

            for filename in filenames:
                if filename.endswith(".py"):
                    full_path = os.path.join(current_dir, filename)
                    # Our own previous output is not part of the codebase, and
                    # counting it would double every finding after a fix run.
                    if is_fixed_output(full_path):
                        continue
                    python_files.append(full_path)

        return python_files

    # --- Working out which parts of a file are prose ----------------------

    def _find_masked_regions(
        self, file_path: str
    ) -> Optional[Dict[int, List[Tuple[int, int]]]]:
        """Map out the comment and string regions of one file.

        We use Python's own :mod:`tokenize` module rather than regular
        expressions, because only a real tokenizer reliably knows where a
        string ends - think nested quotes, escaped quotes, or a triple-quoted
        docstring spanning twenty lines. A regex would guess, and guess wrong.

        Returns:
            A dictionary of ``{line_number: [(start_column, end_column), ...]}``
            marking the prose regions, or None if the file could not be
            tokenized (which tells the caller to fall back to a plain scan).
        """
        masked: Dict[int, List[Tuple[int, int]]] = {}

        try:
            # Opening in binary mode lets tokenize honour any encoding
            # declaration at the top of the file, e.g. "# -*- coding: ... -*-".
            with open(file_path, "rb") as f:
                for token in tokenize.tokenize(f.readline):
                    if token.type not in MASKED_TOKEN_TYPES:
                        continue

                    start_row, start_col = token.start
                    end_row, end_col = token.end

                    if start_row == end_row:
                        # The usual case: a comment or a short string.
                        masked.setdefault(start_row, []).append(
                            (start_col, end_col)
                        )
                    else:
                        # A multi-line string (usually a docstring). Mask from
                        # where it starts to the end of that line, then every
                        # whole line in between, then up to where it ends.
                        masked.setdefault(start_row, []).append(
                            (start_col, END_OF_LINE)
                        )
                        for row in range(start_row + 1, end_row):
                            masked.setdefault(row, []).append((0, END_OF_LINE))
                        masked.setdefault(end_row, []).append((0, end_col))

        except (tokenize.TokenError, SyntaxError, UnicodeDecodeError, OSError) as error:
            # The target file may simply not be valid Python - a template, a
            # snippet, or a file for a different Python version. That is not
            # our problem to solve, so we say so and scan it the plain way.
            print(
                f"[scanner] Could not tokenize {os.path.basename(file_path)} "
                f"({error}); scanning it line by line instead."
            )
            return None

        return masked

    @staticmethod
    def _is_inside_masked_region(
        column: int, regions: List[Tuple[int, int]]
    ) -> bool:
        """True if `column` falls inside any (start, end) region on the line."""
        return any(start <= column < end for start, end in regions)

    def _keyword_columns(self, line: str, keyword: str) -> List[int]:
        """Find the column of every place `keyword` appears in `line`.

        Matching is always case-insensitive. When :attr:`whole_word` is on we
        use a word-boundary pattern so "stripe" matches ``import stripe`` but
        not ``stripewrapper``.
        """
        if self.whole_word:
            # \b marks a word boundary. re.escape keeps dots in a keyword like
            # "requests.get" literal instead of meaning "any character".
            pattern = r"\b" + re.escape(keyword) + r"\b"
            return [m.start() for m in re.finditer(pattern, line, re.IGNORECASE)]

        # Plain substring search, but we want *every* position, not just the
        # first, so a line can be judged code even if one copy is in a comment.
        columns: List[int] = []
        lowered_line = line.lower()
        lowered_keyword = keyword.lower()
        search_from = 0
        while True:
            found_at = lowered_line.find(lowered_keyword, search_from)
            if found_at == -1:
                return columns
            columns.append(found_at)
            search_from = found_at + 1

    # --- The main entry point --------------------------------------------

    def _iter_matches(self, api_keywords: List[str]):
        """Yield one record per match: the single source of scanning truth.

        Both public entry points are built on this, so the dictionary form and
        the :class:`~src.domain.finding.Finding` form cannot drift apart. It
        yields ``(file_path, line_number, line, column, keyword)`` where
        `file_path` is the absolute path as :meth:`find_python_files` produced
        it, `line` is the raw unstripped line, and `column` is the 0-based
        offset of the first occurrence of `keyword` on it.

        This is a generator, so :attr:`files_scanned` is only fully updated once
        it has been consumed to the end. Both callers below build a complete
        collection, which consumes it.
        """
        self.files_scanned = 0

        for file_path in self.find_python_files():
            try:
                # errors="ignore" keeps one oddly-encoded file from stopping
                # the whole scan.
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except OSError as error:
                print(f"[scanner] Could not read {file_path}: {error}")
                continue

            # Count the file as scanned once we know we can read it.
            self.files_scanned += 1

            # Only work out the comment/string regions if we actually intend to
            # use them - tokenizing every file costs time for nothing if the
            # caller wants comments included anyway.
            masked_regions: Optional[Dict[int, List[Tuple[int, int]]]] = None
            if self.skip_comments:
                masked_regions = self._find_masked_regions(file_path)

            # enumerate(..., start=1) gives human-friendly line numbers.
            for line_number, line in enumerate(lines, start=1):
                for keyword in api_keywords:
                    columns = self._keyword_columns(line, keyword)
                    if not columns:
                        continue

                    # If every copy of the keyword on this line sits inside a
                    # comment or a string, this is prose - skip it. If even one
                    # copy is real code, we report the line.
                    # (masked_regions is None when tokenizing failed, which is
                    # our signal to fall back to the plain scan for this file.)
                    if self.skip_comments and masked_regions is not None:
                        regions = masked_regions.get(line_number, [])
                        if all(
                            self._is_inside_masked_region(column, regions)
                            for column in columns
                        ):
                            continue

                    yield file_path, line_number, line, columns[0], keyword

    def scan(
        self,
        change_event: ChangeEvent,
        api_keywords: Optional[List[str]] = None,
    ) -> Tuple[Finding, ...]:
        """Find every place `change_event` affects this project.

        This is the Impact Analysis boundary from ADR-0001: a ChangeEvent plus a
        repository in, typed Findings out.

        Args:
            change_event: The change to look for. Its `change_event_id` is
                carried on every Finding so the two can be joined later.
            api_keywords: What to search for. Defaults to the change event's own
                `symbol`, which is the honest default -- the thing that changed
                is the thing to look for. A caller may widen the search (the CLI
                passes `--keywords`), because a symbol's package name often
                appears where the full dotted path does not.

        Returns:
            A tuple of Finding, possibly empty, at most one per keyword per line.
            Empty is a normal result, not an error.

        Paths on the returned Findings are POSIX-form, per the CodeLocation
        contract, so they differ from the native absolute paths
        :meth:`scan_for_api_usage` returns. On Windows that means forward
        slashes; ``open()`` accepts them either way.
        """
        keywords = (
            [change_event.symbol] if api_keywords is None else list(api_keywords)
        )

        findings: List[Finding] = []

        for file_path, line_number, line, column, keyword in self._iter_matches(
            keywords
        ):
            # POSIX-form for the domain model. The raw path stays available to
            # the dictionary API, which existing callers still rely on.
            posix_path = file_path.replace("\\", "/")

            # snippet is the stripped line, matching what the dictionary form
            # reports. Note that `column` indexes the RAW line, so it does not
            # line up with an offset into `snippet` when the line is indented.
            location = CodeLocation(
                file_path=posix_path,
                line=line_number,
                column=column,
                snippet=line.strip(),
            )

            findings.append(
                Finding(
                    finding_id=derive_finding_id(
                        change_event_id=change_event.change_event_id,
                        file_path=posix_path,
                        line=line_number,
                        column=column,
                        matched_symbol=keyword,
                    ),
                    change_event_id=change_event.change_event_id,
                    location=location,
                    matched_symbol=keyword,
                )
            )

        return tuple(findings)

    def scan_for_api_usage(
        self, api_keywords: List[str]
    ) -> List[Dict[str, object]]:
        """Find every line in the project that mentions one of the keywords.

        Matching is case-insensitive. By default it is a plain substring check,
        so ``"stripe"`` also matches ``import stripe`` and ``StripeClient``;
        pass ``whole_word=True`` to the constructor to require complete words.

        Args:
            api_keywords: Keywords or endpoint patterns to look for,
                e.g. ``["stripe", "openai", "requests.get"]``.

        Returns:
            A list of findings, at most one per keyword per line. Each finding
            is a dictionary with:
                - "file_path":       absolute path of the file
                - "line_number":     1-based line number
                - "line_content":    the matching line, whitespace trimmed
                - "matched_keyword": the keyword that matched

            Also sets :attr:`files_scanned` to the number of files read.

        This is the compatibility form, kept because callers and tests written
        before the typed boundary existed still use it. :meth:`scan` is the
        typed entry point; both read from :meth:`_iter_matches`, so the two
        always report the same matches in the same order.
        """
        return [
            {
                "file_path": file_path,
                "line_number": line_number,
                "line_content": line.strip(),
                "matched_keyword": keyword,
            }
            for file_path, line_number, line, _column, keyword in self._iter_matches(
                api_keywords
            )
        ]


if __name__ == "__main__":
    # Command line interface, so you can point the scanner at any folder
    # without writing a script. Try:
    #
    #   python -m src.core.scanner examples --keywords stripe requests.get
    #   python -m src.core.scanner . --whole-word
    #   python -m src.core.scanner examples --include-comments
    parser = argparse.ArgumentParser(
        description="Scan a folder's Python files for API usage keywords.",
    )
    parser.add_argument(
        "path",
        nargs="?",  # makes the argument optional
        default=".",
        help="Folder to scan. Defaults to the current directory.",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",  # accepts one or more values
        default=DEFAULT_KEYWORDS,
        metavar="KEYWORD",
        help=f"Keywords to look for. Defaults to: {' '.join(DEFAULT_KEYWORDS)}",
    )
    parser.add_argument(
        "--include-comments",
        action="store_true",  # True when the flag is present, else False
        help="Also report matches found only in comments and strings.",
    )
    parser.add_argument(
        "--whole-word",
        action="store_true",
        help='Require complete words, so "stripe" will not match "stripewrapper".',
    )
    args = parser.parse_args()

    scanner = CodebaseScanner(
        project_root=args.path,
        # The flag is phrased as "include", but the option is "skip", so flip it.
        skip_comments=not args.include_comments,
        whole_word=args.whole_word,
    )
    results = scanner.scan_for_api_usage(args.keywords)

    print(f"Scanned: {scanner.project_root}")
    print(f"Files:   {scanner.files_scanned}")
    print(f"Keywords: {', '.join(args.keywords)}")
    print(f"Comments/strings: {'included' if args.include_comments else 'skipped'}")
    print(f"Word matching: {'whole words' if args.whole_word else 'substring'}")
    print(f"\nFound {len(results)} match(es).\n")

    for finding in results:
        # Show the path relative to the scanned folder so output stays readable.
        relative_path = os.path.relpath(
            str(finding["file_path"]), scanner.project_root
        )
        print(f"{relative_path}:{finding['line_number']}")
        print(f"   [{finding['matched_keyword']}] {finding['line_content']}\n")
