# Shared vs sealed review: protocol

Written and committed before any run. Whatever the run shows goes into `results/` and the README, including a result where sealed review does not win.

## Question

When three reviewers see each other's answers, do they find fewer distinct problems than when each reviews alone?

## Material

Five small changes in [`changes.json`](changes.json). Each hides two known problems, ten in total. Most are common review misses: a check that is only equivalent for integers, an off-by-one that moves every caller, a comparison that is no longer constant time.

## Reviewers

The three reviewers are the ones in [`../sealroom.template.yaml`](../sealroom.template.yaml): the same instructions, read from that file, with the same three focus areas (correctness, security, release risk). Each runs as Claude Code in print mode (`claude -p`, model `sonnet`) with tools turned off, in an empty folder, so each answer comes only from the change in front of it.

## Two conditions

- **Sealed.** Each reviewer gets only the change. This is a SEALROOM blind room.
- **Shared.** Reviewer A gets the change. Reviewer B gets the change plus A's answer. Reviewer C gets the change plus A's and B's answers. This is what a shared Switch room delivers, where every agent receives every message.

Every reviewer call is a fresh session. Nothing else differs.

## Scoring

For each change and condition, a grader (`claude -p`, model `sonnet`) gets the change, the list of known problems and the three reviews, without being told the condition, and marks each known problem as found or not. A problem counts as found only when at least one review names it explicitly. The grader prompt is the same for both conditions.

Measures, per condition:

1. **Distinct problems found** by the team, out of 10. This is the main measure.
2. **Problems found by more than one reviewer** (redundancy).
3. **Splits**: changes where the three verdicts were not all the same.

## What would count as a result

Sealed finding more distinct problems than shared supports the idea behind SEALROOM. Equal or fewer means it does not, on this material. With five changes and one run per condition, any difference shows a direction, not proof.
