# Task Lifecycle

A task line is an event record. Its text means: this is what the task was understood to be when it was written here. After that, do not rewrite its meaning in place. The normal mutation is status only.

Daily review closes yesterday's promises and creates today's active commitments.

## Created

A new task starts as an unchecked task in the note where it was captured:

```md
- [ ] Do the thing
```

That line is now historical. Its wording should stay stable unless it is being corrected immediately after capture.

## Reviewed Later

When yesterday's open tasks are reviewed the next day, ask whether each task is still real.

### Done

If the work is complete, mark the original task done in place:

```md
- [x] Do the thing
```

### Dropped

If the task is no longer worth doing, mark the original task dropped in place:

```md
- [-] Do the thing
```

### Still Real, Needed Now

If the task is still real and belongs in today's attention, carry it forward. Mark the original task as carried, then create a new active copy in today's daily note:

```md
- [>] Do the thing
```

```md
- [ ] Do the thing
```

The carried line is historical. The new unchecked line is the active task.

### Still Real, Not Needed Now

If the task is still real but not for today, do not keep editing yesterday until it looks current. Create the current active version where it belongs, with the appropriate date marker, and mark the original as carried.

Use task date markers for time semantics:

```md
- [ ] Do the thing ⏳ 2026-05-27
```

Daily-note placement alone does not mean due today, scheduled today, or active today.

## Rule

Do not rewrite the past. Close old task records by changing status. Represent changed intent with a new task record.
