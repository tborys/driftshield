Fetch GitHub issue $ARGUMENTS from the demouser/driftshield-agentic repository.

Run:
```bash
gh issue view $ARGUMENTS --repo demouser/driftshield-agentic --json title,body,labels,milestone,comments
```

Then read CLAUDE.md from the repo root for stack and execution rules.

Then do the following in order:

1. State the issue title, acceptance criteria, and any explicit dependencies in plain language.
2. Identify which parts of the codebase are in scope based on the "Likely Touch Points" in the issue body.
3. Read the relevant existing source files before proposing anything.
4. Propose a TDD implementation plan:
   - List the failing tests to write first (file paths and test names)
   - List the implementation steps in order
   - List any migration or schema changes needed
   - Flag any acceptance criteria that need a browser check (UI changes)
5. Ask for approval before writing any code.

Do not write any code until the plan is approved.
