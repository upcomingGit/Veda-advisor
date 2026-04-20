# Install Veda

Veda is not a plugin. It's a repo of instructions you point your AI assistant at. The exact mechanism differs by assistant — pick your tool below.

> **Tested models:** GPT-5.4, Claude Opus 4.7, Claude Opus 4.6. Other frontier models from the same families should work but have not been verified. If you run Veda on a different model and it misbehaves, please [open an issue](CONTRIBUTING.md#1-issues-highest-value).

## Before you install — a word on privacy

Onboarding writes a `profile.md` file containing your personal investment profile: net worth exposure, goals, risk tolerance, hard constraints. **Never commit this file.**

The repo's `.gitignore` already excludes `profile.md` and `journal.md`, so if you cloned Veda and work inside that folder, you're protected by default. But be aware of two things:

1. **Don't push to the public `upcomingGit/Veda-advisor` repo.** You don't have write access, but if you fork the repo to your own account and then push your profile by accident, your financial profile is public. The `.gitignore` prevents this, but only if you don't modify it.
2. **Prefer keeping your profile outside the cloned Veda folder** if you're nervous about mistakes. You can point your assistant at Veda (for frameworks) and at a separate private folder (for your profile and journal). See the "profile location" tip under each install section.

If you want a clean setup: make a **separate private repo** (e.g., `my-investing-notes`) for `profile.md` and `journal.md`, and keep the Veda clone untouched as a read-only framework reference.

## GitHub Copilot in VS Code

**Requires:** Copilot Chat in **Agent mode** (not Ask mode). Agent mode is the one that can read and write files in your workspace. In Ask mode, Veda can still reason for you, but it won't be able to write your `profile.md` to disk — you'll need to save it yourself.

**Step 1.** Clone the repo somewhere on your machine:

```powershell
git clone https://github.com/upcomingGit/Veda-advisor.git
```

**Step 2.** Open the `Veda-advisor` folder in VS Code (or add it to your existing workspace as a second root: `File → Add Folder to Workspace`).

**Step 3.** In Copilot Chat, switch the mode selector to **Agent**. Open a new chat and invoke Veda with the built-in slash command:

```
/veda
```

Copilot auto-discovers `.prompt.md` files in `.github/prompts/` and surfaces them in the `/` menu. `/veda` tells Copilot to read `SKILL.md`, adopt the Veda persona, and drive the pipeline — onboarding if `profile.md` is missing, otherwise your next investment question. In Agent mode, `profile.md` is written to the folder root; in Ask mode, you save it yourself.

If `/veda` doesn't appear in the menu, the most likely reasons are that your Copilot extension predates prompt files (update it), or you opened a parent folder rather than the `Veda-advisor` folder itself so `.github/prompts/veda.prompt.md` is out of the workspace's prompt-discovery path. (VS Code discovers prompt files from each workspace folder's `.github/prompts/`; additional locations can be added via the `chat.promptFilesLocations` setting.) As a fallback, type:

```
Read SKILL.md in the Veda-advisor folder and follow it.
```

*Where your profile lives:* by default, alongside `SKILL.md` in the cloned folder. To keep it in a separate private repo, tell the assistant: *"Write profile.md to `<your/other/path>/profile.md` and read it from there every session."*

*Advanced — auto-activate in a project workspace:* to skip typing `/veda` on every chat, copy `SKILL.md` contents into that workspace's `.github/copilot-instructions.md` file. Most users are fine with `/veda` per new chat.

## Claude Code

[Claude Code](https://code.claude.com/docs/en/overview) is Anthropic's terminal-and-IDE coding agent. Veda ships a ready-to-use [skill](https://code.claude.com/docs/en/skills) at `.claude/skills/veda/SKILL.md`. Because it lives in the project's `.claude/skills/` directory, Claude Code auto-discovers it whenever you run `claude` inside the Veda-advisor folder.

**Step 1.** Install Claude Code if you don't have it — see [code.claude.com](https://code.claude.com/docs/en/overview) for the installer appropriate to your OS. On Windows PowerShell, the one-liner is `irm https://claude.ai/install.ps1 | iex`; on macOS/Linux/WSL it's `curl -fsSL https://claude.ai/install.sh | bash`.

**Step 2.** Clone the repo and start Claude Code inside it. Claude Code is a project-scoped agent — the folder you launch it from determines which skills, memory files, and working directory it sees — so `cd` into the Veda-advisor folder before running `claude`:

```powershell
git clone https://github.com/upcomingGit/Veda-advisor.git
cd Veda-advisor
claude
```

On first run, Claude Code will prompt you to sign in with your Claude account (or paste an Anthropic API key). Either works for Veda.

**Step 3.** Invoke Veda from the Claude Code prompt:

```
/veda
```

Or with an initial question on the same line:

```
/veda should I add to TSMC here?
```

The skill's `name: veda` frontmatter is what registers `/veda` as a slash command; the skill body instructs Claude to read the root `SKILL.md` and run the full pipeline. Onboarding triggers automatically if `profile.md` is missing, so the very first `/veda` in a fresh clone kicks off the interview.

*Persistence:* Claude Code has filesystem tools, so your `profile.md` and `portfolio.md` persist across sessions in the repo folder just like they do for Copilot and Gemini CLI. Both files are in `.gitignore` by default.

*Where your profile lives:* by default, at the repo root next to `SKILL.md`. To keep it in a separate private folder, tell Veda at onboarding: *"Write profile.md to `<your/other/path>/profile.md` and read it from there every session."* Then also point Claude Code at that folder by starting with `claude --add-dir <your/other/path>` — skills inside `.claude/skills/` of an added directory are still auto-loaded.

*Optional — always-on context:* Claude Code loads any `CLAUDE.md` at the project root into every session. If you want Veda's playbook applied automatically to every chat in the Veda-advisor workspace (not only after `/veda`), create a one-line `CLAUDE.md` containing `@SKILL.md`. Most users prefer the explicit `/veda` switch so general-coding chats stay general.

## Cursor

**Step 1.** Clone the repo inside your working directory.

**Step 2.** Either (a) `@`-reference `SKILL.md` at the start of your investment chat, or (b) create a Cursor rule file at `.cursor/rules/veda.mdc` whose body instructs the model to follow `SKILL.md` whenever an investment question is asked. Cursor's MDC rule format is documented in Cursor's own docs — the minimum content is a line like *"When the user asks an investment question, read and follow `SKILL.md` in this workspace."*

**Step 3.** Run onboarding the same way: *"Read SKILL.md. You are Veda. Run onboarding."*

## Gemini (web)

Gemini's web app supports custom instructions plus knowledge file uploads via **[Gems](https://support.google.com/gemini/answer/15235603)**. You set up a Gem once, and every conversation with it has Veda's full playbook loaded. This is the tool-of-choice for users who don't want to install anything locally.

**Trade-off versus Copilot / Claude Code:** no filesystem. Your `profile.md` lives in the chat, not on disk — you copy it out at the end of onboarding and paste it back at the start of every future session. Python scripts like [scripts/calc.py](scripts/calc.py) can't execute, so Veda shows its EV / Kelly / FX math inline (still verifiable) rather than calling the deterministic calculator.

**Step 1.** Clone the repo locally so you have the files to upload:

```powershell
git clone https://github.com/upcomingGit/Veda-advisor.git
```

**Step 2.** Go to [gemini.google.com](https://gemini.google.com/), open the sidebar, click **Explore Gems → New Gem**. Name it `Veda`.

**Step 3.** In the **Instructions** field, paste:

> *You are Veda. On every investment question, follow the playbook in `SKILL.md` (attached as Knowledge). If no profile has been pasted into this conversation yet, run the onboarding interview from `setup/onboarding.prompt.md` before anything else. Do not answer investment questions from prior knowledge — drive the 9-stage pipeline from `SKILL.md` every time. State uncertainty explicitly; refuse out-of-scope questions per the Stage 0 decline script.*

**Step 4.** Under **Knowledge**, upload these files from your clone (the Gems upload dialog takes files one at a time or multi-select within a folder — there's no folder-level upload):

- `SKILL.md`
- `setup/onboarding.prompt.md`, `setup/profile.template.md`, `setup/profile.example-aggressive.md`, `setup/profile.example-novice.md`
- `routing/framework-router.md`
- `templates/decision-block.md`
- Every file in `frameworks/` (currently just `frameworks/lynch.md`)

Click **Save**.

**Step 5.** Start a chat with the Veda Gem. Type *"Run onboarding."* Gemini will interview you and produce your profile inline. **Copy the profile and save it somewhere private** — your own notes app, a private GitHub repo, a local file. The Gem's Knowledge is static; newly-produced profiles do not get written back to it.

**Step 6.** At the start of every future session, paste your saved profile into the first message before asking your investment question. That makes the profile part of that conversation's context.

*Refreshing your profile:* when something material changes (goals, risk tolerance, drawdown tolerance), ask Veda to *"update my profile"* mid-chat. It will produce a revised version inline — overwrite your saved copy.

*CLI alternative:* if you prefer the terminal, Veda also ships a `.gemini/commands/veda.toml` command that [Gemini CLI](https://geminicli.com/) auto-discovers (install with `npm install -g @google/gemini-cli`, then `cd Veda-advisor && gemini && /veda`). The CLI path has filesystem access, so your profile persists on disk the same way it does for Copilot and Claude Code. Most users prefer the web Gem above.

## Gemini Code Assist (VS Code) and other web chat assistants

This catch-all covers web ChatGPT, Gemini Code Assist in VS Code, and any assistant that doesn't have a native install path above.

- **Gemini Code Assist (VS Code extension):** place a `GEMINI.md` at the Veda-advisor folder root containing `@SKILL.md`. Gemini Code Assist's agent mode picks it up automatically. Your `profile.md` lives on disk as usual.
- **ChatGPT and other web chat:** paste the contents of `SKILL.md` as a system / custom instruction at the start of each session. Paste `setup/onboarding.prompt.md` when running onboarding. Save the resulting `profile.md` somewhere private and paste it back at the start of every session — web assistants without a filesystem can't persist it for you.

## Invoking Veda across sessions

LLM assistants do not persist context across chat sessions or workspace reopens. Every new chat starts blank. Here is what to do:

| Situation | What to do |
|---|---|
| **First time (onboarding)** | Type `/veda` in your tool of choice. In Copilot and Claude Code, `/veda` is a registered slash command. In Gemini (web), start a new chat with your Veda Gem. In Cursor, `@SKILL.md`. Veda detects `profile.md` is missing (or that no profile has been pasted into the chat, for web tools) and runs onboarding. |
| **New chat, same workspace** | Invoke `/veda` again (or equivalent). The assistant reads `SKILL.md` and your `profile.md` fresh each chat — there is no "auto-start." This is intentional: every session re-validates the profile (Hard Rule #9 re-asks FX if stale, Stage 1 re-checks `profile_last_updated`). |
| **Reopened your editor after a week** | Same — `/veda` in a new chat. If `profile_last_updated` is >6 months old, Veda surfaces the stale-profile check before answering. |
| **Returning after a month away** | `/veda` still works. Veda will re-ask any market data that moves day-to-day (FX, prices) before using them. If you want to refresh specific profile fields, say *"Veda: update my profile"* — that runs onboarding's Step 0 in "update" mode (targeted edits, no re-interview). |
| **Re-running onboarding deliberately** | `/veda` → then say *"redo onboarding"* (or just *"onboarding"*). Veda's Step 0 asks whether to **update** (targeted edits), **redo** (full re-interview, backs up existing profile to `profile.md.bak-<today>`), or **cancel**. Default is update. Never overwrites silently. |
| **Switching between tools** | Your `profile.md` is portable across Copilot, Claude Code, and Cursor (all have filesystem access). For Gemini web, keep a saved copy of your profile outside the tool and paste it at the start of each new chat. The schema, validator, and pipeline are identical across tools. |

Invocation varies by tool — see the sections above for exact details: Copilot and Claude Code use `/veda`; Gemini web loads Veda automatically when you chat with your Veda Gem; Cursor uses `@SKILL.md` or a `.cursor/rules/veda.mdc` rule; web ChatGPT and similar need `SKILL.md` pasted as a system instruction.

**Why there is no "always-on" default:** Veda is scoped to public-markets investment questions. Auto-activating on every message would mean refusing half your chats (coding, email drafting, everything else) with the Stage 0 decline script. `/veda` is the on-switch; general chats stay general.

## Connecting your portfolio (fully optional)

Portfolio-level questions — *"am I too concentrated in semis?"*, *"does this new position overlap with what I already own?"*, *"what's my real portfolio heat?"* — need Veda to see your holdings.

**You don't have to do anything up front.** The default workflow is: when Veda needs your holdings, it will ask, and you paste them in any format — a copy from your broker app, a spreadsheet dump, or rough natural language (*"40% NVDA, 15% TSMC, 10% AVGO, rest cash"*). Veda parses whatever you send. No CSV required, no script to run, no markdown to hand-write. Veda will save those holdings to `portfolio.md` in your workspace (gitignored by default) and tell you it did so — that way you don't have to re-paste them next session. If you don't want persistence, say *"don't save"* in the same message as the paste, or delete `portfolio.md` afterwards.

**Optional power-user shortcut.** If you trade often and want persistence without pasting, there's a CSV importer:

```powershell
# Export your holdings from Zerodha Kite (or any broker) as a CSV, then:
python scripts/import_portfolio.py zerodha holdings.csv
# Or, for any broker whose CSV has ticker / shares / avg_cost / current_price columns:
python scripts/import_portfolio.py generic my_export.csv
```

The script writes `portfolio.md`. Theses and tags are filled in *lazily* — when you ask Veda about a specific holding, it asks you for the one-line thesis and saves it back. You never batch-fill the whole file.

- `portfolio.md` is gitignored by default. Never commit it.
- Supported brokers today: Zerodha, plus a generic CSV importer.
- More brokers coming in v0.2 (Groww, ICICI Direct, Interactive Brokers, Fidelity).
- Native broker integration via MCP is on the v1.0 roadmap.

See [scripts/README.md](scripts/README.md) for details. Most users can ignore this section and just paste holdings when asked.
