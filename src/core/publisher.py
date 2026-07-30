"""Open a GitHub Pull Request containing our fixed code.

The fixer produces updated file contents; this module gets them in front of a
human. It creates a branch, commits the new contents onto it, and opens a PR
against the repository's default branch.

Why a PR and not a direct commit to main: a pull request is reviewable. The
fixer is a machine making guesses about somebody's code, so a person should
look at the diff before it lands. The PR body says outright whether the change
came from the real Claude API or from demo mode, so a reviewer is never misled.

We modify the ORIGINAL files rather than adding `_fixed.py` copies, because a
diff of "here is the same file, changed" is reviewable and a diff of "here is a
whole new file" is not.

Set your token in a `.env` file at the project root (see `.env.example`):

    GITHUB_TOKEN=ghp_...

The token needs the `repo` scope for private repositories, or `public_repo`
for public ones. Without a token this module runs in DRY RUN mode: it prints
what it would do and makes no network calls.
"""

import os
from datetime import datetime, timezone
from typing import Dict, Optional

from dotenv import load_dotenv
from github import Auth, Github
from github.GithubException import (
    BadCredentialsException,
    GithubException,
    UnknownObjectException,
)

# Prefix for the branches we create. The timestamp is added after it.
DEFAULT_BRANCH_PREFIX = "auto-api-fix"

# Commit message used for each file we change.
COMMIT_MESSAGE = "Auto-fix: update code for a breaking API change"


class PRPublisher:
    """Creates a branch, commits fixed files to it, and opens a pull request.

    Example:
        publisher = PRPublisher("your-name/your-repo")
        url = publisher.create_pull_request(
            changes={"examples/payment.py": "new file contents..."},
            title="Fix removed Stripe Charge API",
            body="Details for the reviewer...",
        )
        print(url)  # or an "ERROR: ..." string
    """

    def __init__(
        self,
        repo_full_name: str,
        token: str | None = None,
        dry_run: bool = False,
        branch_prefix: str = DEFAULT_BRANCH_PREFIX,
    ) -> None:
        """Set up the publisher.

        Args:
            repo_full_name: Which repository to open the PR against, in
                "owner/repo" form, e.g. "Dhruv2304-mak/self-maintaining-apis".
            token: A GitHub personal access token. If you leave this out, we
                read GITHUB_TOKEN from the environment instead (loading a
                `.env` file first, if one exists).
            dry_run: Set to True to print what would happen and make no
                network calls at all. We also switch this on automatically
                when no token can be found, so the program still shows you
                something useful instead of only reporting an error.
            branch_prefix: Start of the new branch name. A UTC timestamp is
                appended so repeated runs never collide.

        Note:
            Nothing here ever raises. A missing token just turns dry-run mode
            on, so creating a PRPublisher can never crash your program.
        """
        # Reads the .env file (if present) and copies its values into the
        # environment. Safe to call even when there is no .env file.
        load_dotenv()

        self.repo_full_name = repo_full_name
        self.branch_prefix = branch_prefix

        # The token is kept private: it is never printed, never included in an
        # error message, and never written to a file. See _redact() below.
        self._token = token or os.getenv("GITHUB_TOKEN")

        # True when the caller asked for a dry run *or* we had no choice.
        self.dry_run = bool(dry_run) or not self._token
        self.dry_run_reason: Optional[str] = None
        if dry_run:
            self.dry_run_reason = "dry_run=True was requested"
        elif not self._token:
            self.dry_run_reason = "no GITHUB_TOKEN was found"

    # --- Small helpers ---------------------------------------------------

    def _redact(self, text: object) -> str:
        """Return `text` as a string with the token removed, just in case.

        We never deliberately print the token, but an error message from a
        library is not something we control - a redirect URL or a debug string
        could contain it. This is the safety net that makes sure a leaked token
        never reaches a log file or a screenshot.
        """
        message = str(text)
        if self._token and self._token in message:
            message = message.replace(self._token, "***REDACTED***")
        return message

    def _make_branch_name(self) -> str:
        """Build a branch name that is unique to this moment.

        Using a UTC timestamp means two runs a second apart get two different
        branches, so re-running the tool never fails with "branch already
        exists".
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"{self.branch_prefix}/{stamp}"

    def _describe_dry_run(
        self, changes: Dict[str, str], title: str, branch_name: str
    ) -> None:
        """Print exactly what a real run would have done."""
        print("DRY RUN - nothing will be sent to GitHub.")
        if self.dry_run_reason:
            print(f"  Reason:      {self.dry_run_reason}")
        print(f"  Repository:  {self.repo_full_name}")
        print(f"  New branch:  {branch_name}")
        print(f"  PR title:    {title}")
        print(f"  Files ({len(changes)}):")
        for path in sorted(changes):
            # len(...encode()) is the real byte count, which is what GitHub
            # stores - a character count would be wrong for accented text.
            size = len(changes[path].encode("utf-8"))
            print(f"    - {path} ({size} bytes)")

    # --- The main entry point --------------------------------------------

    def create_pull_request(
        self, changes: Dict[str, str], title: str, body: str
    ) -> str:
        """Create a branch with `changes` on it and open a pull request.

        Args:
            changes: Maps a repository-relative path (with forward slashes,
                e.g. "examples/payment.py") to that file's complete new
                contents. Paths that do not exist yet are created.
            title: The pull request title.
            body: The pull request description, shown to the reviewer.

        Returns:
            The pull request's URL on success. In dry-run mode, a string
            starting with "DRY RUN". On failure, a human-readable message
            starting with "ERROR:" instead of raising - the same convention
            :meth:`CodeFixer.fix_code` uses, so a caller can check the prefix.
        """
        if not changes:
            return "ERROR: There are no file changes to publish."

        branch_name = self._make_branch_name()

        # Dry run: describe and stop. No client is built, so no network call
        # can happen even by accident.
        if self.dry_run:
            self._describe_dry_run(changes, title, branch_name)
            return "DRY RUN: no pull request was created."

        try:
            # Auth.Token is the current PyGithub way to authenticate.
            github_client = Github(auth=Auth.Token(self._token))
            repo = github_client.get_repo(self.repo_full_name)

            # Ask the API which branch is the default. Never hardcode "main":
            # plenty of repositories still use "master", or something else
            # entirely, and guessing wrong makes the PR fail.
            default_branch = repo.default_branch
            source = repo.get_branch(default_branch)
            print(f"  Default branch: {default_branch}")

            # Create our new branch pointing at the same commit the default
            # branch is currently on.
            repo.create_git_ref(
                ref=f"refs/heads/{branch_name}", sha=source.commit.sha
            )
            print(f"  Created branch: {branch_name}")

            # Commit each file onto the new branch.
            for path in sorted(changes):
                content = changes[path]
                try:
                    # GitHub needs the file's current blob SHA to update it -
                    # that is how it knows we are changing the version we
                    # think we are, rather than clobbering someone else's edit.
                    existing = repo.get_contents(path, ref=branch_name)

                    # get_contents returns a list when the path is a folder.
                    # A folder is not something we can write file contents to.
                    if isinstance(existing, list):
                        return (
                            f"ERROR: '{path}' is a directory in the repository, "
                            "not a file."
                        )

                    repo.update_file(
                        path=path,
                        message=COMMIT_MESSAGE,
                        content=content,
                        sha=existing.sha,
                        branch=branch_name,
                    )
                    print(f"  Updated: {path}")

                except UnknownObjectException:
                    # The file is not in the repository yet, so add it.
                    repo.create_file(
                        path=path,
                        message=COMMIT_MESSAGE,
                        content=content,
                        branch=branch_name,
                    )
                    print(f"  Created: {path}")

            # Finally, open the pull request into the default branch.
            pull_request = repo.create_pull(
                title=title,
                body=body,
                head=branch_name,
                base=default_branch,
            )
            return pull_request.html_url

        # Below: specific problems first, general ones last. Python uses the
        # first matching `except`, and both of these are subclasses of
        # GithubException, so a broad catch at the top would hide them.
        except BadCredentialsException:
            return (
                "ERROR: GitHub rejected the token. Check the GITHUB_TOKEN value "
                "in your .env file, and that it has not expired."
            )
        except UnknownObjectException:
            return (
                f"ERROR: Could not find the repository '{self.repo_full_name}'. "
                "Check the owner/repo spelling, and that your token has access "
                "to it (the `repo` scope for private repositories, or "
                "`public_repo` for public ones)."
            )
        except GithubException as error:
            # Anything else the API refused: a protected branch, a PR that
            # already exists, a rate limit, an empty repository.
            return (
                f"ERROR: GitHub returned {error.status}: "
                f"{self._redact(error.data)}"
            )
        except Exception as error:  # last resort, so we never crash the caller
            return f"ERROR: Unexpected problem opening the PR: {self._redact(error)}"


if __name__ == "__main__":
    # A dry-run demo with made-up content, so you can try this file with no
    # token and no repository. Nothing is sent anywhere.
    #
    #     python -m src.core.publisher
    FAKE_CHANGES = {
        "examples/payment.py": (
            "import stripe\n\n\n"
            "def charge_customer(amount, token):\n"
            '    """Charge a customer."""\n'
            "    return stripe.PaymentIntent.create(\n"
            "        amount=amount,\n"
            '        currency="usd",\n'
            "        payment_method=token,\n"
            "        confirm=True,\n"
            "    )\n"
        ),
        "examples/refund.py": (
            "import stripe\n\n\n"
            "def refund(charge_id):\n"
            '    """Refund a payment."""\n'
            "    return stripe.Refund.create(payment_intent=charge_id)\n"
        ),
    }

    FAKE_TITLE = "Auto-fix: update 2 file(s) for a breaking API change"
    FAKE_BODY = "The Charge API has been removed. Use PaymentIntent instead."

    print("=" * 60)
    print("PRPublisher demo (dry run)")
    print("=" * 60)

    # dry_run=True forces dry-run mode even if a real GITHUB_TOKEN exists,
    # so running this demo can never open a pull request by accident.
    publisher = PRPublisher("your-name/your-repo", dry_run=True)

    print()
    result = publisher.create_pull_request(
        changes=FAKE_CHANGES,
        title=FAKE_TITLE,
        body=FAKE_BODY,
    )

    print(f"\nResult: {result}")

    # create_pull_request never raises - it returns an "ERROR: ..." string.
    if result.startswith("ERROR:"):
        print("Something went wrong (see above).")
