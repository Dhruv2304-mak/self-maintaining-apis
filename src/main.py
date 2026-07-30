"""
Self-Maintaining APIs - Main Entry Point

The whole pipeline, end to end:
  [1] detect a breaking change in an API provider's documentation
  [2] scan a target folder for code that uses that API
  [3] fix each affected file
  [4] optionally open a GitHub pull request with the result (--open-pr)

Step [3] has two ways to save its work:
  * by default it writes a copy next to the original, e.g. payment_fixed.py
  * with --in-place it edits the original file directly

Step [4] never depends on those saved files. It uses the fixed contents we kept
in memory, so the pull request always modifies the ORIGINAL file and a reviewer
sees a clean diff instead of a mysterious new _fixed.py.

Run `python -m src.main --help` to see every option. With no options at all it
behaves exactly as it always has: detect, scan "examples", write _fixed.py
copies, never call the real Claude API, and never touch GitHub.
"""

import argparse
import os

from src.core.detector import APIChangeDetector
from src.core.fixer import CodeFixer
from src.core.publisher import PRPublisher
from src.core.scanner import CodebaseScanner

# A plain-English description of what the provider changed. In a finished tool
# this text would come from the detector; here we spell it out so the demo is
# easy to follow. It is passed to the fixer for every file we try to update,
# and it goes into the pull request description.
CHANGE_DESCRIPTION = (
    "The Charge API has been removed. Use PaymentIntent instead: "
    "stripe.PaymentIntent.create() takes `payment_method` rather than "
    "`source`, and needs confirm=True to charge immediately."
)

# Default folder the scanner searches, used when --target is not given. It
# deliberately does NOT point at this project's own `src` folder: this tool's
# source is full of the word "stripe" in comments and examples, and those
# self-matches would bury the results you care about.
SCAN_TARGET = "examples"

# Default keywords, used when --keywords is not given.
DEFAULT_KEYWORDS = ["stripe", "requests.get"]

# Files the fixer has already written end with this. We skip them, otherwise
# the tool would keep trying to "fix" its own previous output, over and over.
FIXED_SUFFIX = "_fixed.py"

# The documentation page step [1] checks for breaking changes.
DOCS_URL = "https://stripe.com/docs/upgrades"

# The top of this project, worked out from this file's location:
# .../project/src/main.py -> .../project/src -> .../project
# GitHub wants paths relative to the repository root, so we measure from here.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_args(argv=None):
    """Read the command line options.

    Args:
        argv: Normally left as None, which means "use the real command line".
            Tests can pass a list of strings instead.
    """
    parser = argparse.ArgumentParser(
        # Show default values automatically in --help, so nobody has to guess.
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Detect an API change, find affected code, fix it, and "
        "optionally open a pull request.",
    )
    parser.add_argument(
        "--target",
        default=SCAN_TARGET,
        metavar="PATH",
        help="Folder to scan for affected code.",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",  # accepts one or more values
        default=DEFAULT_KEYWORDS,
        metavar="KEYWORD",
        help="Keywords that mark code as affected.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",  # True when the flag is present, else False
        help="Overwrite the original files instead of writing _fixed.py copies.",
    )
    parser.add_argument(
        "--skip-detect",
        action="store_true",
        help="Skip step [1]. It opens a browser and takes 10-30 seconds.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call the real Claude API instead of using demo mode.",
    )
    parser.add_argument(
        "--open-pr",
        action="store_true",
        help="After fixing, open a GitHub pull request with the results.",
    )
    parser.add_argument(
        "--repo",
        metavar="NAME",
        help='Target repository as "owner/repo". Required with --open-pr.',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Describe the pull request instead of creating it, even with a token.",
    )

    args = parser.parse_args(argv)

    # argparse cannot express "this flag needs that flag", so check by hand.
    # parser.error prints the usage line and a clear message, then exits.
    if args.open_pr and not args.repo:
        parser.error(
            "--open-pr also needs --repo, e.g. --repo your-name/your-repo"
        )

    return args


def display_path(path: str) -> str:
    """Shorten a path for printing, e.g. "examples/payment.py".

    Absolute paths are correct but hard to read. We show the path relative to
    wherever the script was run from, with forward slashes so the output looks
    the same on Windows, macOS, and Linux.
    """
    try:
        relative = os.path.relpath(path)
    except ValueError:
        # relpath fails if the path is on a different Windows drive than the
        # current folder. In that case the full path is the best we can do.
        return path.replace("\\", "/")
    return relative.replace("\\", "/")


def to_repo_path(file_path: str):
    """Convert a local path into the form the GitHub API expects.

    GitHub identifies files by their path from the repository root, always with
    forward slashes - "examples/payment.py", never
    "C:\\Users\\me\\project\\examples\\payment.py".

    Returns:
        The repository-relative path, or None if the file sits outside this
        project (in which case it is not part of the repository at all, and
        cannot go into a pull request).
    """
    try:
        relative = os.path.relpath(os.path.abspath(file_path), PROJECT_ROOT)
    except ValueError:
        # Different Windows drive, so definitely not inside the project.
        return None

    # A leading ".." means the path climbed out of the project folder.
    if relative.startswith(".."):
        return None

    return relative.replace("\\", "/")


def group_findings_by_file(findings: list) -> dict:
    """Collapse a flat list of findings into one entry per file.

    The scanner reports one finding per matching *line*, so a file with five
    matching lines appears five times. We only want to read, fix, and save
    each file once, so we group them here and keep the match count for the
    report.

    Returns:
        A dictionary of ``{file_path: number_of_matches}``, sorted by path so
        the output is in a predictable order every run.
    """
    counts: dict = {}

    for finding in findings:
        path = str(finding["file_path"])
        # .get(path, 0) means "the count so far, or 0 if this is the first one".
        counts[path] = counts.get(path, 0) + 1

    # Rebuild the dictionary in sorted order. Dictionaries remember insertion
    # order, so this makes the printed report stable between runs.
    return {path: counts[path] for path in sorted(counts)}


def read_source_file(file_path: str) -> tuple:
    """Read a Python file, and note which line ending it uses.

    We read raw bytes rather than text so we can *see* the real line endings
    before Python hides them. That matters for --in-place: if we wrote "\\n"
    into a file that used "\\r\\n", every single line would show up as changed
    in a diff, which would make the pull request unreadable.

    Returns:
        A tuple of ``(code, uses_crlf)``. `code` always uses plain "\\n" line
        endings, which is what the fixer expects. `uses_crlf` records what the
        file actually had, so we can put it back exactly as we found it.

    Raises:
        OSError: the file could not be read (missing, permissions).
        UnicodeDecodeError: the file is not valid UTF-8 text.
    """
    with open(file_path, "rb") as f:
        raw = f.read()

    text = raw.decode("utf-8")

    # Work out the dominant line ending. A file with 40 CRLF lines and one
    # stray LF is a CRLF file, so we compare the two counts rather than just
    # asking "is there a single \r\n anywhere?".
    crlf_count = raw.count(b"\r\n")
    lone_lf_count = raw.count(b"\n") - crlf_count
    uses_crlf = crlf_count > lone_lf_count

    # Normalise to "\n" for the fixer. The second replace catches the very old
    # Mac style of using "\r" on its own.
    code = text.replace("\r\n", "\n").replace("\r", "\n")
    return code, uses_crlf


def write_in_place(file_path: str, fixed_code: str, uses_crlf: bool) -> None:
    """Overwrite `file_path` with `fixed_code`, keeping its line endings.

    Raises:
        OSError: the file could not be written.
    """
    # Start from a known state (plain "\n"), then convert if the original file
    # used "\r\n".
    to_write = fixed_code.replace("\r\n", "\n")
    if uses_crlf:
        to_write = to_write.replace("\n", "\r\n")

    # newline="" tells Python to write our line endings through untouched.
    # Without it, Windows would silently turn every "\n" into "\r\n" and undo
    # all the care above.
    with open(file_path, "w", encoding="utf-8", newline="") as f:
        f.write(to_write)


def build_fixer(use_live: bool) -> CodeFixer:
    """Create the fixer and say out loud which mode it actually ended up in.

    We ask for live mode when --live was passed, but CodeFixer quietly falls
    back to demo mode when it cannot find an API key. So we report
    `fixer.demo_mode` - what really happened - rather than what we asked for.
    """
    fixer = CodeFixer(demo_mode=not use_live)

    if fixer.demo_mode:
        print("Mode: DEMO - no real AI call is made, so this costs nothing.")
        if fixer.demo_reason:
            print(f"      Reason: {fixer.demo_reason}.")
        if use_live:
            # The user asked for --live and did not get it. Say so plainly.
            print("      You passed --live, but demo mode was used instead.")
            print("      Add ANTHROPIC_API_KEY to your .env file for real fixes.")
    else:
        print(f"Mode: LIVE - calling the real Claude API ({fixer.model}).")

    return fixer


def fix_files_from_findings(
    findings: list,
    in_place: bool = False,
    use_live: bool = False,
) -> dict:
    """Fix every file the scanner flagged.

    One file at a time, we:
      1. skip it if it is already one of our own `_fixed.py` outputs
      2. read the current contents
      3. ask the fixer for an updated version
      4. save that version - either over the original (--in-place) or as a
         separate `_fixed.py` copy (the default)

    Anything that goes wrong with one file is reported and we move on to the
    next, so a single unreadable file cannot stop the whole run.

    Returns:
        A dictionary describing the run, for the pull request step to use:
            - "changes":      {repo_relative_path: fixed_code} kept in memory
            - "match_counts": {repo_relative_path: number_of_matches}
            - "examined" / "changed" / "skipped" / "failed": counts
            - "demo_mode":    True if no real AI call was made
            - "model":        which Claude model was configured
    """
    # Collect the fixed contents in memory. The pull request is built from
    # this, not from files on disk, so --open-pr works whether or not
    # --in-place was used and regardless of any _fixed.py copies.
    changes: dict = {}
    match_counts: dict = {}

    if not findings:
        print("Nothing to fix - the scan found no matching code.")
        return {
            "changes": changes,
            "match_counts": match_counts,
            "examined": 0,
            "changed": 0,
            "skipped": 0,
            "failed": 0,
            "demo_mode": True,
            "model": "",
        }

    fixer = build_fixer(use_live)

    # Loud warning before we touch anybody's source files.
    if in_place:
        print()
        print("!" * 60)
        print("IN-PLACE MODE: original files will be overwritten.")
        print("No _fixed.py copies are created. Commit or back up first.")
        print("!" * 60)

    files_to_fix = group_findings_by_file(findings)

    # Tally counters for the summary at the end. Every file ends up in exactly
    # one of these, so the three of them always add up to `examined`.
    examined = len(files_to_fix)
    changed = 0
    skipped = 0
    failed = 0

    print(f"\nFound matches in {examined} file(s). Fixing each one:\n")

    for file_path, match_count in files_to_fix.items():
        shown = display_path(file_path)
        label = f"  {shown}: {match_count} match(es)"

        # --- 1. Never try to fix our own output -------------------------
        if file_path.endswith(FIXED_SUFFIX):
            print(f"{label} -> skipped (already a fixed file)")
            skipped += 1
            continue

        # --- 2. Read the file -------------------------------------------
        try:
            original_code, uses_crlf = read_source_file(file_path)
        except (OSError, UnicodeDecodeError) as error:
            # Permissions, a deleted file, or text that is not valid UTF-8.
            print(f"{label} -> FAILED (could not read the file: {error})")
            failed += 1
            continue

        # --- 3. Ask the fixer for an updated version --------------------
        # fix_code never raises; it returns an "ERROR: ..." string instead.
        fixed_code = fixer.fix_code(
            original_code=original_code,
            change_description=CHANGE_DESCRIPTION,
            file_path=file_path,
        )
        if fixed_code.startswith("ERROR:"):
            print(f"{label} -> FAILED ({fixed_code})")
            failed += 1
            continue

        # The fixer may decide this file needs no change after all. Writing an
        # identical copy would just be noise, so we say so and move on. This
        # matters even more in --in-place mode: it saves a pointless rewrite
        # that would show up as a modified file in git for no reason.
        if fixed_code == original_code:
            print(f"{label} -> no change needed")
            skipped += 1
            continue

        # --- 4. Save the result -----------------------------------------
        if in_place:
            # Overwrite the original, keeping its original line endings.
            try:
                write_in_place(file_path, fixed_code, uses_crlf)
            except OSError as error:
                print(f"{label} -> FAILED (could not write the file: {error})")
                failed += 1
                continue
            print(f"{label} -> updated in place")
        else:
            # Write a separate copy. save_fixed_code also returns an
            # "ERROR: ..." string on failure rather than raising.
            saved_path = fixer.save_fixed_code(file_path, fixed_code)
            if saved_path.startswith("ERROR:"):
                print(f"{label} -> FAILED ({saved_path})")
                failed += 1
                continue
            print(f"{label} -> saved {display_path(saved_path)}")

        changed += 1

        # --- 5. Remember the result for a possible pull request ---------
        # The PR always modifies the ORIGINAL path, never the _fixed.py copy.
        repo_path = to_repo_path(file_path)
        if repo_path is None:
            # The file lives outside this project, so it is not part of the
            # repository and cannot be included in a pull request.
            print(
                f"      (note: outside {display_path(PROJECT_ROOT)}, "
                "so it cannot go into a pull request)"
            )
        else:
            changes[repo_path] = fixed_code
            match_counts[repo_path] = match_count

    # --- The summary ----------------------------------------------------
    print(
        f"\nSummary: {examined} file(s) examined, "
        f"{changed} changed, {skipped} skipped, {failed} failed."
    )
    if changed and in_place:
        print("Your original files were edited. Use `git diff` to review them.")
    elif changed:
        print("Open each *_fixed.py next to its original to compare the two.")
        print("Nothing was overwritten - your original files are untouched.")

    return {
        "changes": changes,
        "match_counts": match_counts,
        "examined": examined,
        "changed": changed,
        "skipped": skipped,
        "failed": failed,
        "demo_mode": fixer.demo_mode,
        "model": fixer.model,
    }


def build_pr_title(result: dict) -> str:
    """Write the pull request title from what actually happened.

    In demo mode we put "[DEMO]" right at the front. A reviewer scanning a list
    of pull requests should be able to tell at a glance that this one was not
    produced by a real AI, without having to open it.
    """
    file_count = len(result["changes"])
    prefix = "[DEMO] " if result["demo_mode"] else ""
    return (
        f"{prefix}Auto-fix: update {file_count} file(s) for a breaking API change"
    )


def build_pr_body(result: dict) -> str:
    """Write the pull request description for a human reviewer.

    The most important job here is honesty about where the change came from.
    A demo-mode fix is a hard-coded text substitution, not an AI fix, and a
    reviewer who assumes otherwise might merge nonsense. So that warning goes
    first, before anything else.
    """
    lines = []

    if result["demo_mode"]:
        lines += [
            "> **This is a DEMO-MODE change, not an AI-generated fix.**",
            ">",
            "> These edits come from a small hard-coded text substitution in",
            "> `src/core/fixer.py` - the Claude API was never called. The",
            "> substitution is deliberately naive and is known to mangle prose",
            "> in comments and docstrings. **Read every line before merging.**",
            "",
        ]
    else:
        lines += [
            f"Generated by the Claude API (`{result['model']}`).",
            "An AI wrote these edits, so please review them as you would any",
            "other contribution.",
            "",
        ]

    lines += [
        "## The breaking change",
        "",
        CHANGE_DESCRIPTION,
        "",
        "## Files updated",
        "",
    ]

    for path in sorted(result["match_counts"]):
        count = result["match_counts"][path]
        lines.append(f"- `{path}` - {count} matching line(s) found")

    lines += [
        "",
        "## How this was produced",
        "",
        f"- Files examined: {result['examined']}",
        f"- Files changed: {result['changed']}",
        f"- Files skipped: {result['skipped']}",
        f"- Files failed: {result['failed']}",
        "",
        "---",
        "*Opened automatically by the self-maintaining-apis tool.*",
    ]

    return "\n".join(lines)


def open_pull_request(result: dict, repo_full_name: str, force_dry_run: bool) -> None:
    """Put the fixed files into a pull request for review."""
    changes = result["changes"]

    # Nothing changed means there is nothing to review. Do not create an empty
    # branch or an empty pull request.
    if not changes:
        print("No files were changed, so no pull request was created.")
        return

    publisher = PRPublisher(repo_full_name, dry_run=force_dry_run)

    title = build_pr_title(result)
    body = build_pr_body(result)

    # In a dry run, show the description too. It is the part a reviewer reads,
    # so it is worth checking before a real pull request goes out.
    if publisher.dry_run:
        print("--- pull request description (preview) ---")
        print(body)
        print("--- end of description ---\n")

    # create_pull_request never raises; it returns a string either way.
    outcome = publisher.create_pull_request(changes=changes, title=title, body=body)

    print()
    if outcome.startswith("ERROR:"):
        print(f"Could not open the pull request: {outcome}")
    elif outcome.startswith("DRY RUN"):
        print(outcome)
        print("Re-run without --dry-run (and with a GITHUB_TOKEN) to open it.")
    else:
        print(f"Pull request opened: {outcome}")


def main(argv=None):
    args = parse_args(argv)

    print("=" * 60)
    print("Self-Maintaining APIs - Starting scan...")
    print("=" * 60)

    # 1. Detect possible changes from API documentation. This is the slow part
    #    - it drives a real browser - so --skip-detect lets you jump past it
    #    while working on the later steps.
    if args.skip_detect:
        print("\n[1] Skipped the documentation check (--skip-detect).")
        print("    Using the known Stripe breaking change instead.")
    else:
        print(f"\n[1] Checking documentation: {DOCS_URL}")

        detector = APIChangeDetector(DOCS_URL)
        changes = detector.detect()

        if not changes:
            print("No potential breaking changes or deprecations found.")
            print("Done.")
            return

        print(f"Found {len(changes)} potential change(s):")
        for i, change in enumerate(changes, 1):
            print(f"  {i}. [{change.get('type', change.get('severity', 'unknown'))}] {change.get('message', change.get('text', ''))}")

    # 2. Scan the target codebase for related API usage
    print(f"\n[2] Scanning '{args.target}' for related API usage...")

    # project_root=args.target keeps the scan focused on the code we care
    # about. The scanner skips matches that only appear in comments or strings
    # by default, so prose about Stripe is not reported as real usage.
    scanner = CodebaseScanner(args.target)
    findings = scanner.scan_for_api_usage(args.keywords)

    # scanner.files_scanned tells us how much ground we covered, which makes a
    # result of "0 matches" much easier to interpret.
    print(f"Scanned {scanner.files_scanned} Python file(s) in '{args.target}'.")
    print(f"Keywords: {', '.join(args.keywords)}")

    if not findings:
        # Zero matches is a perfectly normal outcome, not a failure. Say so
        # plainly instead of leaving the user wondering what went wrong.
        print("\nNo matching API usage found - that is expected here.")
        print(f"Nothing in '{args.target}' uses these keywords in real code yet.")
        print("To scan a different project, pass --target:")
        print("  python -m src.main --target path/to/project")
    else:
        print(f"\nFound {len(findings)} matching line(s):\n")
        for finding in findings:
            print(f"  File: {finding['file_path']}")
            print(f"  Line {finding['line_number']}: {finding['line_content'].strip()}")
            print(f"  Matched: {finding['matched_keyword']}")
            print("-" * 50)

    # 3. Fix the real files the scanner just found.
    print("\n[3] Fixing the affected files with the AI code fixer...")
    result = fix_files_from_findings(
        findings,
        in_place=args.in_place,
        use_live=args.live,
    )

    # 4. Optionally put the results in front of a reviewer.
    if args.open_pr:
        print("\n[4] Opening a pull request with the fixed files...")
        open_pull_request(result, args.repo, force_dry_run=args.dry_run)

    print("\n" + "=" * 60)
    print("Scan completed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
