# Autonomous Development Policy

## Authority Order

When instructions conflict, use this precedence:

1. `.specify/memory/constitution.md`
2. Current feature `spec.md`
3. Current feature `plan.md`, contracts, and data model
4. This `AGENTS.md`
5. `docs/DECISIONS.md`
6. `docs/ROADMAP.md`
7. Existing repository conventions
8. Agent implementation judgment

The constitution is the highest project-level authority.

---

# Operating Mode

This repository is developed using an autonomous Spec Kit feature cycle.

The human has granted standing approval for the agent to proceed through normal development phases without requesting permission at every step.

Within already-approved product scope, do not stop merely to ask whether to:

- continue to the next Spec Kit phase
- create tests
- fix a failing test introduced by the feature
- fix an obvious bug
- make a small refactor needed by the feature
- choose names for files, functions, classes, tables, tests, or variables
- choose among equivalent implementation techniques
- update documentation affected by the implementation
- address clear LOW or MEDIUM analysis/convergence findings
- rerun tests
- rerun analysis or convergence
- commit a completed feature
- begin the next roadmap feature

Prefer continuing autonomously.

---

# Superpowers Brainstorming Standing Approval

For work already inside the approved project roadmap, the human opts out of unnecessary brainstorming approval gates.

Use Superpowers brainstorming when it materially helps establish or clarify a new feature, but:

- read existing project context first
- do not ask questions already answered by the constitution, specs, roadmap, decisions, code, or prior artifacts
- make reversible implementation decisions autonomously
- treat the project roadmap as approval to investigate and specify the listed feature
- do not require a separate human "yes" before implementation when the resulting specification contains no material unresolved user decision

Human approval is still required for the escalation categories below.

---

# Mandatory Human Escalation

Stop and ask ONE focused question only when the answer materially changes what is being built in one of these categories.

## Product semantics

Examples:

- introducing a new staff capability
- removing an expected capability
- changing the meaning of Accept, Edit, Reject, Defer, or Create
- deciding whether information should appear in or disappear from normal views
- changing what an annotation or engagement value means

## Data semantics

Examples:

- changing what constitutes one annotation, clip, participant, activity, or observation
- changing how human and AI values interact
- destructive transformation of existing project data
- changing identity-association semantics

## Privacy, ethics, or identity

Examples:

- sending sensitive media to a new external/cloud service
- participant re-identification
- reverse-image search
- searching for legal names or home addresses
- demographic inference
- psychological inference
- public release of data when authorization is unclear

## Major architecture

Examples:

- replacing React/TypeScript
- replacing FastAPI/Python
- replacing SQLite
- introducing microservices
- introducing cloud infrastructure
- introducing a substantial external service
- introducing a major dependency with deployment implications

## Destructive or irreversible action

Examples:

- deleting real participant data
- rewriting Git history
- destructive schema migration without validated recovery
- deleting large portions of existing functionality
- overwriting human-reviewed data

## External blocker

Examples:

- missing credentials
- inaccessible required hardware
- authorization only the human can provide
- missing external dataset

If escalation is required:

1. ask one question only
2. explain why it changes the resulting product
3. recommend one option
4. give alternatives only when materially different
5. resume autonomously after the answer

---

# Standard Feature Lifecycle

For every roadmap feature:

## A. Start Feature

Create or switch to the appropriate feature branch.

Do not develop features directly on `main`.

Use sequential identifiers:

`001-...`
`002-...`
`003-...`

Ensure Spec Kit's active-feature metadata points to the correct feature.

---

## B. Specify

Run the Spec Kit specification phase.

Define:

- what users need
- expected behavior
- boundaries
- acceptance scenarios
- edge cases
- measurable success criteria

Do not overload the specification with implementation details.

Use existing decisions without asking the human to repeat them.

---

## C. Clarify

Run clarification when meaningful ambiguity exists.

Resolve implementation-level ambiguity autonomously.

Escalate only decisions covered by Mandatory Human Escalation.

If no material ambiguity remains, continue automatically.

---

## D. Plan

Produce the implementation plan.

Include as appropriate:

- architecture
- modules
- data structures
- API contracts
- algorithms
- migrations
- testing
- files affected
- failure behavior
- security/privacy implications

Stay within the modular-monolith architecture unless explicitly amended.

---

## E. Checklist

Run requirements-quality validation.

Correct clear requirement-quality problems automatically.

Continue when the checklist passes.

---

## F. Tasks

Produce dependency-ordered implementation tasks with exact file paths.

Tasks must be independently verifiable where practical.

Testing tasks should accompany the behavior they verify.

---

## G. Analyze

Run cross-artifact consistency analysis before implementation.

Check:

constitution
→ specification
→ plan
→ contracts
→ tasks

Automatically correct clear findings.

Repeat analysis until:

- no CRITICAL findings remain
- no HIGH findings remain

MEDIUM and LOW findings should also be fixed when the correct resolution is clear and does not require human escalation.

---

## H. Implement

Implement the complete feature.

Follow tasks in dependency order.

Do not intentionally leave the feature half-built merely because a minimal subset works.

Use TDD or regression-first tests where practical.

Do not expand unrelated scope.

---

## I. Test

Run all tests available in the current environment.

When a failure occurs:

### Feature regression

Fix it.

### Pre-existing failure

Verify when practical, document it, and continue.

### Environment limitation

Document it accurately.

Do not claim an unrun test passed.

Record required validation for the appropriate environment.

Examples include CUDA-only tests that cannot run on macOS.

---

## J. Converge

Run Spec Kit convergence.

If convergence identifies remaining work:

converge
→ append tasks
→ implement
→ test
→ converge again

Continue until:

`CONVERGED`

Do not ask permission to fix ordinary convergence findings.

---

## K. Final Validation

Before committing:

- all feature tasks are complete
- convergence reports `CONVERGED`
- locally available tests have been run
- new failures introduced by the feature are fixed
- environment-specific unrun tests are documented
- `git diff` has been reviewed
- `git status` has been reviewed
- no secrets are staged
- no temporary databases are staged
- no prohibited media or biometric artifacts are staged
- real project data has not been accidentally modified

---

## L. Commit

Once the feature is converged and validated:

- commit automatically on its feature branch
- use a concise conventional commit
- do not ask the human for permission to commit

Example:

`feat: implement clip annotation pipeline`

Do NOT automatically merge to `main`.

---

## M. Continue

After committing:

1. update roadmap status
2. record durable decisions made during the feature
3. start the next roadmap feature
4. repeat this lifecycle

Do not wait for the human to say "continue."

---

# Testing Policy

Never hide failing tests.

Clearly distinguish:

- passing
- failing
- skipped
- not run
- pre-existing failures
- environment limitations

A feature may be committed when:

- convergence reports `CONVERGED`
- no feature-caused test failures remain
- unavailable environment-specific tests are explicitly documented

Merging may have stricter requirements than committing.

---

# Git Policy

Each major Spec Kit feature gets its own feature branch.

Commit once the feature is converged.

Do not merge feature branches into `main` automatically.

Do not rewrite shared Git history without explicit human approval.

Do not commit secrets or temporary/generated artifacts that are excluded by project policy.

---

# Scope Discipline

Use YAGNI.

Do not add speculative capabilities simply because they may eventually be useful.

Do not perform unrelated refactoring.

If a small refactor is necessary to implement the feature safely, perform it and test it.

Large unrelated refactors become separate future work.

---

# TPA-Specific Persistent Rules

Carry these decisions into every feature:

- React + TypeScript + Vite frontend
- FastAPI + Python backend
- SQLite/local application storage
- local processing of sensitive participant media
- open-source models
- existing anonymous participant format such as `Person_0001`
- anonymous cross-video participant association is permitted
- real-world participant re-identification is prohibited
- do not search the web, reverse-image services, external databases, or identity services to discover participant legal names or home addresses
- participant-derived analytical records are permitted where project authorization allows them
- current annotation state is authoritative
- original imported/model values begin with `source = AI`
- human-created or human-modified values use `source = HUMAN`
- `source` and `review_status` are independent
- review history is append-only
- review actions are CREATE, ACCEPT, EDIT, REJECT, and DEFER
- reviewed work cannot be silently overwritten by automation
- rejected annotations remain auditable but are excluded from normal views and exports
- labels are deactivated rather than destructively deleted
- activity and observation labels are distinct
- multiple annotations may describe the same moment
- model confidence and review priority are separate
- models surface candidate observations; humans make program interpretations
- facial-expression outputs must be represented as uncertain visible-affect observations, not definitive internal emotional states
- preserve existing participant IDs across reviewed data
- do not rerun identity clustering in a way that invalidates reviewed participant associations

---

# Completion Condition

Continue autonomously until every roadmap feature is:

SPECIFIED
→ PLANNED
→ TASKED
→ ANALYZED
→ IMPLEMENTED
→ TESTED
→ CONVERGED
→ COMMITTED

Stop only for a Mandatory Human Escalation issue or a genuine external blocker.
