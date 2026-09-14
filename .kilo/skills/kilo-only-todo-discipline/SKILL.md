---
name: kilo-only-todo-discipline
description: For every user request, always create a todo list to track tasks and verify all items are completed successfully before finishing. Enforces structured task tracking using the todowrite tool. Use at the start of any non-trivial request and before responding.
license: MIT
---

# Todo Discipline

This skill is specifically designed for the Kilo agent. Do not propagate to other agent skill directories.

## When to run

At the start of any request with 2+ distinct steps or non-trivial scope, and before any final response.

## Rules

1. **Create todos immediately** — call `todowrite` with all discovered tasks before doing other work. Break the request into concrete, actionable items.
2. **Update in real time** — mark items `in_progress` before starting work on them, and `completed` only after the work is actually done (including required verification).
3. **Never skip verification** — before the final response, confirm every todo item is `completed`. If anything is `in_progress` or `pending`, finish or explain why it remains open.
4. **No premature completion** — do not mark a task `completed` until tests, lint, typecheck, or other required gates have actually passed.

## Example flow

```
User: "Add a todo-only skill and run lint"

Assistant:
1. todowrite([{content: "Create kilo-only-todo-discipline skill under .kilo/skills/", status: pending, priority: high}, ...])
2. Update first item to in_progress
3. Write SKILL.md
4. Mark first item completed
5. Update second item to in_progress
6. Run lint / typecheck
7. Mark second item completed
8. Final response only after all items are completed
```
