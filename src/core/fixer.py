"""Use Claude to update code that a breaking API change has made outdated.

The detector finds *that* something changed; this module tries to fix the code.
We hand Claude three things — the current code, a description of the breaking
change, and (optionally) the file path for context — and ask for the updated
code back.

Set your key in a `.env` file at the project root (see `.env.example`):

    ANTHROPIC_API_KEY=sk-ant-...

DEMO MODE
---------
No API key? No problem. Pass ``demo_mode=True`` (or just leave the key out) and
:meth:`CodeFixer.fix_code` skips the network entirely, returning a hand-written
"pretend" fix instead. Nothing is sent to Anthropic and nothing is billed. This
is meant for demos, offline work, and tests — never for real fixes, because the
fake fixer only knows the one Stripe example below.
"""

import os
import sys
from pathlib import Path
from typing import List, Optional

import anthropic
from dotenv import load_dotenv

# The Claude model we send requests to. Claude Sonnet 5 is the current Sonnet
# release - a good balance of code quality, speed, and cost for this job.
DEFAULT_MODEL = "claude-sonnet-5"

# Upper limit on how much text Claude may write back. Generous enough for a
# whole rewritten file, low enough to stay under the SDK's request timeout.
MAX_TOKENS = 16000

# The "role" we give Claude. This part never changes between requests, so we
# keep it separate from the per-request details below.
SYSTEM_PROMPT = """You are an expert software engineer who updates code after \
an API provider ships a breaking change.

Follow these rules exactly:
1. Return ONLY the updated code. No explanations, no commentary, no markdown \
code fences.
2. Preserve the original coding style, formatting, naming, and comments \
wherever you can.
3. Make the minimum edits needed to handle the breaking change. Do not \
refactor, rename, or "improve" anything you were not asked to change.
4. If the code needs no change for this particular breaking change, return it \
back completely unchanged."""

# --- Demo-mode knowledge --------------------------------------------------
# Demo mode does not "understand" code; it only knows this one substitution.
# Stripe removed the old Charges API, so `stripe.Charge.create(...)` becomes
# `stripe.PaymentIntent.create(...)` with two argument changes:
#   * `source=` was renamed to `payment_method=`
#   * `confirm=True` is needed to charge right away (Charge.create always did)
DEMO_OLD_CALL = "stripe.Charge.create"
DEMO_NEW_CALL = "stripe.PaymentIntent.create"


class CodeFixer:
    """Asks Claude to rewrite outdated code for a given breaking change.

    Example:
        fixer = CodeFixer()
        new_code = fixer.fix_code(old_code, "The `foo` parameter was removed.")

    Example (no API key needed):
        fixer = CodeFixer(demo_mode=True)
        new_code = fixer.fix_code(old_code, "Charge was replaced by PaymentIntent.")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        demo_mode: bool = False,
    ) -> None:
        """Set up the Claude client (or the offline fake one).

        Args:
            api_key: Your Anthropic API key. If you leave this out, we read
                the ANTHROPIC_API_KEY environment variable instead (loading a
                `.env` file first, if one exists).
            model: Which Claude model to use. The default is fine for most
                cases. Ignored in demo mode, since we never call the API.
            demo_mode: Set to True to never touch the network. :meth:`fix_code`
                then returns a hand-written pretend fix instead of asking
                Claude. We also switch this on automatically when no API key
                can be found, so the program still does *something* useful
                instead of only reporting an error.

        Note:
            Nothing here ever raises. A missing key just turns demo mode on,
            and any other setup problem is recorded and reported later by
            :meth:`fix_code`, so creating a CodeFixer can never crash you.
        """
        # Reads the .env file (if present) and copies its values into the
        # environment. Safe to call even when there is no .env file.
        load_dotenv()

        self.model = model
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

        # True when the caller asked for demo mode *or* we had no choice.
        # `demo_reason` is just a friendly explanation for printing/logging.
        self.demo_mode = bool(demo_mode) or not self.api_key
        self.demo_reason: Optional[str] = None
        if demo_mode:
            self.demo_reason = "demo_mode=True was requested"
        elif not self.api_key:
            self.demo_reason = "no ANTHROPIC_API_KEY was found"

        # `self._client` stays None in demo mode; fix_code checks this.
        self._client: Optional[anthropic.Anthropic] = None
        self._setup_error: Optional[str] = None

        if not self.demo_mode:
            self._client = anthropic.Anthropic(api_key=self.api_key)

    def _build_prompt(
        self,
        original_code: str,
        change_description: str,
        file_path: str,
    ) -> str:
        """Assemble the message we send to Claude.

        The tags (<breaking_change>, <code>) are not magic - they just make it
        obvious to Claude where each piece of information starts and stops.
        """
        location = f"\nThis code lives in: {file_path}" if file_path else ""

        return f"""An API provider announced this breaking change:

<breaking_change>
{change_description}
</breaking_change>
{location}

Update the code below so it keeps working after this change.

<code>
{original_code}
</code>

Remember: reply with the updated code only."""

    def _extract_code(self, response: anthropic.types.Message) -> str:
        """Pull the plain text out of Claude's reply and tidy it up.

        A response is a *list* of blocks, not a single string. Claude Sonnet 5
        thinks before answering by default, so the first block may be a
        "thinking" block rather than the answer. We therefore keep only the
        blocks whose type is "text" instead of blindly reading the first one.
        """
        parts: List[str] = [
            block.text for block in response.content if block.type == "text"
        ]
        code = "\n".join(parts).strip()

        # We asked for no markdown fences, but strip them just in case Claude
        # adds them anyway - otherwise they would end up inside the .py file.
        if code.startswith("```"):
            lines = code.split("\n")
            lines = lines[1:]  # drop the opening ``` (and any language label)
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]  # drop the closing ```
            code = "\n".join(lines).strip()

        return code

    # --- Demo mode -------------------------------------------------------

    @staticmethod
    def _demo_rewrite_source_arg(line: str) -> List[str]:
        """Turn one `source=X` line into `payment_method=X` + `confirm=True`.

        Returns a *list* of lines, because a multi-line call needs two lines
        (the renamed argument, then confirm=True) while a single-line call
        needs just one. Handles both of these shapes:

            source=token,                          -> two lines
            stripe.PaymentIntent.create(source=t)  -> one line
        """
        # Split off any trailing comment so we only rewrite real code.
        code, hash_sign, comment = line.partition("#")

        # Read the value after "source=", stopping at the first , or ) or end.
        after = code.split("source=", 1)[1]
        value = ""
        for character in after:
            if character in ",)":
                break
            value += character
        value = value.strip()

        code = code.replace(f"source={value}", f"payment_method={value}", 1)
        stripped = code.rstrip()

        # Case A: the call closes on this same line, e.g. `create(..., source=t)`.
        # Squeeze confirm=True in just before that final closing bracket.
        if stripped.endswith(")"):
            close = stripped.rfind(")")
            rebuilt = stripped[:close] + ", confirm=True" + stripped[close:]
            if hash_sign:
                rebuilt = f"{rebuilt}  {hash_sign}{comment}"
            return [rebuilt]

        # Case B: `source=token,` sits on its own line inside a multi-line call,
        # so confirm=True becomes a sibling argument on the next line. We drop
        # the original comment here - it described the argument we just removed.
        indent = line[: len(line) - len(line.lstrip())]
        return [
            f"{indent}payment_method={value},  # renamed from `source`",
            f"{indent}confirm=True,  # charge now, like Charge.create did",
        ]

    def _demo_fix_stripe(self, original_code: str) -> str:
        """Rewrite the old Stripe Charges call as a modern PaymentIntent call.

        This is plain string editing, one line at a time - no AI involved. It
        only handles the shapes of code used in this project's demo, which is
        exactly the point: it is fake, but it *looks* like a real fix. Because
        it is dumb text matching, it would also rename an unrelated `source=`
        elsewhere in the same snippet - another reason demo output is for
        looking at, not for committing.
        """
        fixed_lines: List[str] = []

        for line in original_code.split("\n"):
            # Apply the edits in sequence rather than picking just one, because
            # a short call can contain the method name AND the renamed argument
            # AND a stale comment all on a single line.

            # 1. The call itself: Charge.create -> PaymentIntent.create
            if DEMO_OLD_CALL in line:
                line = line.replace(DEMO_OLD_CALL, DEMO_NEW_CALL)

            # 2. Comments and docstrings that still name the removed API.
            if "old Charges API" in line:
                line = line.replace("old Charges API", "modern PaymentIntents API")

            # 3. The renamed argument: source=X -> payment_method=X, plus
            #    confirm=True so the customer is still charged immediately.
            #    This one can turn a single line into two, so it goes last.
            if "source=" in line:
                fixed_lines.extend(self._demo_rewrite_source_arg(line))
                continue

            fixed_lines.append(line)

        return "\n".join(fixed_lines)

    def _demo_fix_code(self, original_code: str, change_description: str) -> str:
        """Return a believable fake "fixed" version of `original_code`.

        Two cases:
          * The code uses the old Stripe Charges API -> we rewrite it properly.
          * Anything else -> we hand the code back with a note on top, because
            demo mode genuinely does not know how to fix it.
        """
        if DEMO_OLD_CALL in original_code:
            return self._demo_fix_stripe(original_code)

        # Fallback: unchanged code plus an honest banner, so nobody mistakes
        # this for a real fix if it ever gets written to a file.
        summary = change_description.strip().split("\n")[0] or "unspecified change"
        banner = (
            "# NOTE: produced by CodeFixer demo mode - the real Claude API was\n"
            "# never called, so this code was NOT actually updated.\n"
            f"# Reported change: {summary}\n"
        )
        return banner + original_code

    # --- Public entry point ----------------------------------------------

    def fix_code(
        self,
        original_code: str,
        change_description: str,
        file_path: str = "",
    ) -> str:
        """Ask Claude to update `original_code` for a breaking change.

        In demo mode (see :meth:`__init__`) no request is made at all and a
        hand-written pretend fix is returned instead.

        Args:
            original_code: The source code as it exists today.
            change_description: What the API provider changed, in plain
                English (e.g. the text the detector found).
            file_path: Optional path to the file, given to Claude as extra
                context. Purely informational, and unused in demo mode.

        Returns:
            The updated code as a string - always a string, never None. On any
            failure this returns a human-readable message starting with
            "ERROR:" instead of raising, so a caller looping over many files
            never crashes mid-run. Check for that prefix before writing the
            result to disk.
        """
        if not original_code.strip():
            return "ERROR: No code was provided to fix."

        # Demo mode short-circuits everything below: no client, no network.
        if self.demo_mode:
            return self._demo_fix_code(original_code, change_description)

        # Problem from __init__ (something other than a missing API key).
        if self._client is None:
            return self._setup_error or "ERROR: CodeFixer is not configured."

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": self._build_prompt(
                            original_code, change_description, file_path
                        ),
                    }
                ],
            )

        # Below: specific problems first, general ones last. Python uses the
        # first matching `except`, so a broad one at the top would swallow
        # everything and hide the real cause.
        except anthropic.AuthenticationError:
            return (
                "ERROR: Your API key was rejected. Check the ANTHROPIC_API_KEY "
                "value in your .env file."
            )
        except anthropic.NotFoundError:
            return (
                f"ERROR: The model '{self.model}' was not found. Check the "
                "model name, or that your key has access to it."
            )
        except anthropic.RateLimitError:
            return "ERROR: Rate limited by the API. Wait a moment and try again."
        except anthropic.APIConnectionError:
            return "ERROR: Could not reach the API. Check your internet connection."
        except anthropic.APIStatusError as error:
            return f"ERROR: The API returned {error.status_code}: {error.message}"
        except Exception as error:  # last resort, so we never crash the caller
            return f"ERROR: Unexpected problem while calling Claude: {error}"

        # Claude can decline a request for safety reasons. That is a normal
        # (successful) response, not an exception, so we check for it here.
        if response.stop_reason == "refusal":
            return "ERROR: Claude declined to answer this request."

        fixed_code = self._extract_code(response)
        if not fixed_code:
            return "ERROR: Claude returned an empty response."

        return fixed_code

    # --- Saving the result -----------------------------------------------

    def save_fixed_code(self, original_file_path: str, fixed_code: str) -> str:
        """Write `fixed_code` to a new file with `_fixed` added to the name.

        We never overwrite the original file. The new file is written into the
        same folder as the original, so you can diff the two side by side and
        decide for yourself whether to keep the change.

        Args:
            original_file_path: Path of the file the code came from, e.g.
                "src/payments/payment.py". Only used to build the new name -
                we never read or modify this file. Pass an empty string when
                there is no original file.
            fixed_code: The updated code to write.

        Returns:
            The path of the file we wrote, as a string. On failure this returns
            a message starting with "ERROR:" instead of raising, the same way
            :meth:`fix_code` does - so check for that prefix before telling the
            user where their file is.

        Examples:
            payment.py         -> payment_fixed.py
            src/api/charge.py  -> src/api/charge_fixed.py
            ""                 -> fixed_code.py  (in the current directory)
        """
        # Guard first: never write an empty file, and never save one of our own
        # "ERROR: ..." strings as if it were real code. fix_code returns those
        # instead of raising, so without this check a failed fix would quietly
        # end up on disk looking like a valid Python file.
        if not fixed_code or not fixed_code.strip():
            return "ERROR: There is no fixed code to save."
        if fixed_code.startswith("ERROR:"):
            return f"ERROR: Refusing to save a failed fix: {fixed_code}"

        # Work out the new file name.
        if not original_file_path.strip():
            # No original file, so fall back to a fixed name in this folder.
            target = Path("fixed_code.py")
        else:
            original = Path(original_file_path)
            # `stem` is the name without the extension ("payment"), `suffix`
            # is the extension (".py"), and `with_name` keeps the same folder.
            target = original.with_name(f"{original.stem}_fixed{original.suffix}")

        try:
            # Create the folder if it does not exist yet, then write the file.
            #   encoding="utf-8" keeps any non-English characters in the code
            #     intact instead of letting Windows mangle them.
            #   newline="" writes the line endings exactly as they appear in
            #     the string. Without it, Windows silently turns every "\n"
            #     into "\r\n", and then a diff against the original marks
            #     every single line as changed - which defeats the point.
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(fixed_code, encoding="utf-8", newline="")
        except OSError as error:
            # Permissions, a read-only disk, a silly filename... report it
            # rather than crashing a caller that is looping over many files.
            return f"ERROR: Could not save the fixed code to '{target}': {error}"

        return str(target)


if __name__ == "__main__":
    # A made-up example so you can try the fixer without a real breaking
    # change. This runs in DEMO MODE by default, so it never touches the
    # network. Pass --live to use the real Claude API instead:
    #
    #     python -m src.core.fixer          # offline demo (default)
    #     python -m src.core.fixer --live   # real API call, needs a key
    use_demo = "--live" not in sys.argv

    FAKE_OLD_CODE = '''import stripe


def create_charge(amount, token):
    """Charge a customer using the old Charges API."""
    return stripe.Charge.create(
        amount=amount,
        currency="usd",
        source=token,  # old-style token field
    )
'''

    FAKE_CHANGE = (
        "The Charge API has been removed. Use PaymentIntent instead: "
        "stripe.PaymentIntent.create() takes `payment_method` rather than "
        "`source`, and needs confirm=True to charge immediately."
    )

    print("=" * 60)
    print("CodeFixer demo (fake breaking change)")
    print("=" * 60)

    fixer = CodeFixer(demo_mode=use_demo)
    if fixer.demo_mode:
        print(f"Mode: DEMO - no API call will be made ({fixer.demo_reason}).")
    else:
        print(f"Mode: LIVE - calling {fixer.model}.")

    print("\n--- BEFORE ---")
    print(FAKE_OLD_CODE)

    result = fixer.fix_code(
        original_code=FAKE_OLD_CODE,
        change_description=FAKE_CHANGE,
        file_path="src/payments/charges.py",
    )

    # fix_code never raises - it returns an "ERROR: ..." string instead.
    if result.startswith("ERROR:"):
        print(f"\n--- FAILED ---\n{result}")
    else:
        print("--- AFTER ---")
        print(result)
