"""
Self-Maintaining APIs - Main Entry Point

The whole pipeline, end to end:
  [1] detect a breaking change in an API provider's documentation
  [2] scan a target folder for code that uses that API
  [3] fix each affected file and save the result alongside the original

Step [3] runs the fixer in DEMO MODE, which means it never calls the real
Claude API: no API key is needed and nothing is billed. See src/core/fixer.py.
"""

import os

from src.core.detector import APIChangeDetector
from src.core.fixer import CodeFixer
from src.core.scanner import CodebaseScanner

# A plain-English description of what the provider changed. In a finished tool
# this text would come from the detector; here we spell it out so the demo is
# easy to follow. It is passed to the fixer for every file we try to update.
CHANGE_DESCRIPTION = (
    "The Charge API has been removed. Use PaymentIntent instead: "
    "stripe.PaymentIntent.create() takes `payment_method` rather than "
    "`source`, and needs confirm=True to charge immediately."
)

# Which folder the scanner searches. Point this at the codebase you actually
# want to check. It deliberately does NOT point at this project's own `src`
# folder: this tool's source is full of the word "stripe" in comments and
# examples, and those self-matches would bury the results you care about.
SCAN_TARGET = "examples"

# Files the fixer has already written end with this. We skip them, otherwise
# the tool would keep trying to "fix" its own previous output, over and over.
FIXED_SUFFIX = "_fixed.py"


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


def fix_files_from_findings(findings: list) -> None:
    """Fix every file the scanner flagged, and save each result to a new file.

    One file at a time, we:
      1. skip it if it is already one of our own `_fixed.py` outputs
      2. read the current contents
      3. ask the fixer for an updated version
      4. save that version next to the original

    Anything that goes wrong with one file is reported and we move on to the
    next, so a single unreadable file cannot stop the whole run.
    """
    if not findings:
        print("Nothing to fix - the scan found no matching code.")
        return

    # demo_mode=True is the important part: no network, no key, no cost.
    fixer = CodeFixer(demo_mode=True)
    print("Mode: DEMO - no real AI call is made, so this costs nothing.")
    print("      (Pass demo_mode=False and set ANTHROPIC_API_KEY for real fixes.)")

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
            with open(file_path, "r", encoding="utf-8") as f:
                original_code = f.read()
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
        # identical copy would just be noise, so we say so and move on.
        if fixed_code == original_code:
            print(f"{label} -> no change needed")
            skipped += 1
            continue

        # --- 4. Save the result to a new file ---------------------------
        # save_fixed_code also returns an "ERROR: ..." string on failure.
        saved_path = fixer.save_fixed_code(file_path, fixed_code)
        if saved_path.startswith("ERROR:"):
            print(f"{label} -> FAILED ({saved_path})")
            failed += 1
            continue

        print(f"{label} -> saved {display_path(saved_path)}")
        changed += 1

    # --- The summary ----------------------------------------------------
    print(
        f"\nSummary: {examined} file(s) examined, "
        f"{changed} changed, {skipped} skipped, {failed} failed."
    )
    if changed:
        print("Open each *_fixed.py next to its original to compare the two.")
        print("Nothing was overwritten - your original files are untouched.")


def main():
    print("=" * 60)
    print("Self-Maintaining APIs - Starting scan...")
    print("=" * 60)

    # 1. Detect possible changes from API documentation
    docs_url = "https://stripe.com/docs/upgrades"
    print(f"\n[1] Checking documentation: {docs_url}")

    detector = APIChangeDetector(docs_url)
    changes = detector.detect()

    if not changes:
        print("No potential breaking changes or deprecations found.")
        print("Done.")
        return

    print(f"Found {len(changes)} potential change(s):")
    for i, change in enumerate(changes, 1):
        print(f"  {i}. [{change.get('type', change.get('severity', 'unknown'))}] {change.get('message', change.get('text', ''))}")

    # 2. Scan the target codebase for related API usage
    print(f"\n[2] Scanning '{SCAN_TARGET}' for related API usage...")

    # Keywords we want to look for (you can expand this list later)
    keywords = ["stripe", "requests.get"]

    # project_root=SCAN_TARGET keeps the scan focused on the code we care
    # about. The scanner skips matches that only appear in comments or strings
    # by default, so prose about Stripe is not reported as real usage.
    scanner = CodebaseScanner(SCAN_TARGET)
    findings = scanner.scan_for_api_usage(keywords)

    # scanner.files_scanned tells us how much ground we covered, which makes a
    # result of "0 matches" much easier to interpret.
    print(f"Scanned {scanner.files_scanned} Python file(s) in '{SCAN_TARGET}'.")
    print(f"Keywords: {', '.join(keywords)}")

    if not findings:
        # Zero matches is a perfectly normal outcome, not a failure. Say so
        # plainly instead of leaving the user wondering what went wrong.
        print("\nNo matching API usage found - that is expected here.")
        print(f"Nothing in '{SCAN_TARGET}' uses these keywords in real code yet.")
        print("To scan your own project, change SCAN_TARGET at the top of this file")
        print("to that project's folder, or run the scanner directly:")
        print("  python -m src.core.scanner <folder> --keywords stripe requests.get")
    else:
        print(f"\nFound {len(findings)} matching line(s):\n")
        for finding in findings:
            print(f"  File: {finding['file_path']}")
            print(f"  Line {finding['line_number']}: {finding['line_content'].strip()}")
            print(f"  Matched: {finding['matched_keyword']}")
            print("-" * 50)

    # 3. Fix the real files the scanner just found, instead of a hardcoded
    #    snippet. Each fix is written to a new *_fixed.py file.
    print("\n[3] Fixing the affected files with the AI code fixer...")
    fix_files_from_findings(findings)

    print("\n" + "=" * 60)
    print("Scan completed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
