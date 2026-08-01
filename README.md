#Self-Maintaining APIs
Simple tool that watches for API breaking changes and open Pull Requests to fix them.
This is the beginning of a YC-style project.

## Setup

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Configuration (`.env`)

Copy `.env.example` to `.env` and fill in the values you need. **Both keys are
optional** — the tool degrades gracefully instead of crashing when one is
missing, so you can try everything before setting anything up.

```
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
```

`.env` is listed in `.gitignore`. Never commit it.

### `ANTHROPIC_API_KEY`

Used by `src/core/fixer.py` to ask Claude for the updated code. Without it, the
fixer falls back to **demo mode**: it returns a hard-coded text substitution and
makes no API call, so nothing is billed. Pass `--live` to use the real API.

### `GITHUB_TOKEN`

Used by `src/core/publisher.py` to open the pull request. Create one at
**GitHub → Settings → Developer settings → Personal access tokens**.

The scope it needs depends on the repository you are opening the PR against:

| Repository | Required scope | Why |
| --- | --- | --- |
| **Private** | `repo` | Full control of private repositories — needed to read the file contents, push a branch, and open a PR. |
| **Public** | `public_repo` | The public-only subset of `repo`. Enough to push a branch and open a PR on a public repository. |

Grant the narrower scope where you can: `public_repo` on a public repository
cannot touch your private code, so a leaked token does less damage.

With a fine-grained personal access token instead of a classic one, grant the
target repository **Contents: Read and write** (to push the branch) and
**Pull requests: Read and write** (to open the PR).

Without a token, the publisher falls back to **dry-run mode**: it prints the
branch name, the files, and the PR title, and makes no network calls at all.
The token is never printed — not in logs, not in error messages.

## Usage

```bash
# Full pipeline: detect -> scan -> fix. Writes examples/payment_fixed.py.
python -m src.main

# Skip the slow browser-based detection step while iterating
python -m src.main --skip-detect

# Scan a different folder, with your own keywords
python -m src.main --target path/to/project --keywords stripe openai

# Edit the original files instead of writing _fixed.py copies
python -m src.main --in-place

# Use the real Claude API instead of demo mode
python -m src.main --live

# Preview a pull request without creating one (safe, no network)
python -m src.main --open-pr --repo owner/repo --dry-run

# Actually open the pull request
python -m src.main --open-pr --repo owner/repo
```

Each module also runs on its own:

```bash
python -m src.core.detector                                   # check the docs page
python -m src.core.scanner examples --keywords stripe         # scan a folder
python -m src.core.fixer                                      # demo a fix
python -m src.core.publisher                                  # dry-run a PR
```

Run `python -m src.main --help` for every option.

## Running tests

```bash
python -m pytest
python -m pytest -m meta
python -m pytest --cov --cov-report=term-missing
```

## A note on demo mode

Demo mode is a **hard-coded string substitution**, not an AI fix. It knows one
thing: how to turn `stripe.Charge.create(...)` into
`stripe.PaymentIntent.create(...)`. It is there so the pipeline can be demoed
and tested with no API key and no cost.

It is deliberately naive and will happily mangle prose — it rewrites the
sentence "still uses the old Charges API, which was removed" into "still uses
the modern PaymentIntents API, which was removed", which contradicts itself.

Any pull request opened from demo mode is labelled `[DEMO]` in its title and
carries a warning at the top of its description, so a reviewer cannot mistake a
demo substitution for a real AI fix. Use `--live` for anything you intend to
merge.
