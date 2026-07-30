"""
Self-Maintaining APIs - Main Entry Point
This script detects API changes, scans the local codebase for affected usage,
and then demonstrates how the CodeFixer would update the outdated code.

The fixer runs in DEMO MODE, which means it never calls the real Claude API:
no API key is needed and nothing is billed. See src/core/fixer.py for details.
"""

from src.core.detector import APIChangeDetector
from src.core.fixer import CodeFixer
from src.core.scanner import CodebaseScanner

# A small, made-up example of outdated code for the fixer demo. Stripe removed
# the old Charges API, so this snippet is exactly the kind of thing our scanner
# is looking for out in the wild.
EXAMPLE_OLD_CODE = '''import stripe


def create_charge(amount, token):
    """Charge a customer using the old Charges API."""
    return stripe.Charge.create(
        amount=amount,
        currency="usd",
        source=token,  # old-style token field
    )
'''

# A plain-English description of what the provider changed. In a finished tool
# this text would come from the detector; here we spell it out so the demo is
# easy to follow.
EXAMPLE_CHANGE = (
    "The Charge API has been removed. Use PaymentIntent instead: "
    "stripe.PaymentIntent.create() takes `payment_method` rather than "
    "`source`, and needs confirm=True to charge immediately."
)

# Where we pretend the example code lives. The fixer uses this to name the file
# it saves, so the demo writes examples/payment_fixed.py and leaves the rest of
# the project alone. Nothing reads this file - it does not have to exist.
EXAMPLE_FILE_PATH = "examples/payment.py"

# Which folder the scanner searches. Point this at the codebase you actually
# want to check. It deliberately does NOT point at this project's own `src`
# folder: this tool's source is full of the word "stripe" in comments and
# examples, and those self-matches would bury the results you care about.
SCAN_TARGET = "examples"


def demonstrate_fixer():
    """Show a BEFORE -> AFTER example of the CodeFixer, without any API calls.

    We build the fixer with demo_mode=True so it returns a hand-written
    pretend fix instead of asking Claude. That keeps this script runnable
    on any machine, with or without an ANTHROPIC_API_KEY.
    """
    # demo_mode=True is the important part: no network, no key, no cost.
    fixer = CodeFixer(demo_mode=True)

    print("Mode: DEMO - no real AI call is made, so this costs nothing.")
    print("      (Pass demo_mode=False and set ANTHROPIC_API_KEY for real fixes.)")

    print("\nThe breaking change we are fixing for:")
    print(f"  {EXAMPLE_CHANGE}")

    print("\n--- BEFORE (outdated code) ---")
    print(EXAMPLE_OLD_CODE)

    # fix_code always returns a string. On failure that string starts with
    # "ERROR:" instead of raising, so we check for that before showing it.
    fixed_code = fixer.fix_code(
        original_code=EXAMPLE_OLD_CODE,
        change_description=EXAMPLE_CHANGE,
        file_path=EXAMPLE_FILE_PATH,
    )

    if fixed_code.startswith("ERROR:"):
        print("--- FIX FAILED ---")
        print(fixed_code)
        return

    print("--- AFTER (updated code) ---")
    print(fixed_code)

    # Finally, write the result to a new file so you can open it and diff it.
    # The original file is never touched - `_fixed` is added to the name, so
    # examples/payment.py becomes examples/payment_fixed.py.
    saved_path = fixer.save_fixed_code(EXAMPLE_FILE_PATH, fixed_code)

    # save_fixed_code returns an "ERROR: ..." string instead of raising, so
    # check for that before announcing a file that may not exist.
    if saved_path.startswith("ERROR:"):
        print(f"Could not save the fixed code: {saved_path}")
    else:
        print(f"Saved the fixed code to: {saved_path}")


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

    # 3. Demonstrate the fixer. We only reach this point when the detector
    #    found something, because we returned early otherwise.
    print("\n[3] Demonstrating the AI code fixer...")
    demonstrate_fixer()

    print("\n" + "=" * 60)
    print("Scan completed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
