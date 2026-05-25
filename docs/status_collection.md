# AnuPpuccin Task Status Collection

Source: https://publish.obsidian.md/tasks/Reference/Status+Collections/AnuPpuccin+Theme

| Markdown | Character | Status | Decision | Type | Guidance |
| --- | --- | --- | --- | --- | --- |
| `- [ ] #task` | `space` | Unchecked | Keep | Open | Default active task. |
| `- [x] #task` | `x` | Checked | Keep | Resolved | Work is complete. |
| `- [>] #task` | `>` | Rescheduled | Keep | Historical | Carried forward: this task was not completed here; a new active copy exists elsewhere. |
| `- [!] #task` | `!` | Important | Keep | Open/decorative | Attention required. Use when the user explicitly flags the task as needing care, judgment, or discussion; do not use as priority. |
| `- [-] #task` | `-` | Cancelled | Keep | Resolved | Task is intentionally dropped. |
| `- [/] #task` | `/` | In Progress | Keep | Open/decorative | Already started; resume rather than start fresh. |
| `- [?] #task` | `?` | Question | Keep | Open/decorative | Use only when the deliverable is an answer, not when answering is merely a prerequisite. |
| `- [*] #task` | `*` | Star | Keep | Open/decorative | Agent task. Use when the task is assigned to the agent. |
| `- [n] #task` | `n` | Note | Exclude | N/A | Notes are plain bullets, not task statuses. |
| `- [l] #task` | `l` | Location | Exclude | N/A | Location is task text or metadata, not a status. |
| `- [i] #task` | `i` | Information | Exclude | N/A | Information is a plain bullet, not a task status. |
| `- [I] #task` | `I` | Idea | Exclude | N/A | Ideas are plain bullets unless they become actionable tasks. |
| `- [S] #task` | `S` | Amount | Exclude | N/A | Amounts belong in task text or metadata, not status. |
| `- [p] #task` | `p` | Pro | Exclude | N/A | Pros are plain bullets under a decision, not task statuses. |
| `- [c] #task` | `c` | Con | Exclude | N/A | Cons are plain bullets under a decision, not task statuses. |
| `- [b] #task` | `b` | Bookmark | Exclude | N/A | Bookmarks are plain bullets or links, not task statuses. |
| `- ["] #task` | `"` | Quote | Exclude | N/A | Quotes are plain bullets or blockquotes, not task statuses. |

Excluded statuses:

| Markdown | Character | Status | Reason |
| --- | --- | --- | --- |
| `- [<] #task` | `<` | Scheduled | Scheduling is represented with task date markers: `⏳`, `🛫`, and `📅`. |
| `- [n] #task` | `n` | Note | Notes are plain bullets, not task statuses. |
| `- [l] #task` | `l` | Location | Location is task text or metadata, not a status. |
| `- [i] #task` | `i` | Information | Information is a plain bullet, not a task status. |
| `- [I] #task` | `I` | Idea | Ideas are plain bullets unless they become actionable tasks. |
| `- [S] #task` | `S` | Amount | Amounts belong in task text or metadata, not status. |
| `- [p] #task` | `p` | Pro | Pros are plain bullets under a decision, not task statuses. |
| `- [c] #task` | `c` | Con | Cons are plain bullets under a decision, not task statuses. |
| `- [b] #task` | `b` | Bookmark | Bookmarks are plain bullets or links, not task statuses. |
| `- ["] #task` | `"` | Quote | Quotes are plain bullets or blockquotes, not task statuses. |

## Guidance Notes

### `- [>]` Rescheduled

Carried forward. Use when an old task record is closed because a new active copy exists elsewhere.

Match when the workflow carries a task forward from an older note into today's note.

```md
# old record
- [>] Do the thing

# new active record
- [ ] Do the thing
```

### `- [!]` Important

Attention required. Use when the user explicitly flags the task as needing care, judgment, or discussion. This is not priority.

Match things like:

- "this one needs attention"
- "pay attention to this"
- "be careful with this one"
- "this needs a decision before acting"

```md
- [!] Call bank about suspicious transfer 🔺
```

### `- [/]` In Progress

Already started. Use when active work is underway and the task should be resumed rather than started fresh.

Match things like:

- "I started this"
- "I'm halfway through"
- "continue working on this"
- "pick this back up"
- "this is in progress"

Do not use merely because a task is selected, planned, or scheduled.

```md
- [/] Finish wiring the MCP status resolver
```

### `- [?]` Question

Use only when the deliverable is an answer, not when answering is merely a prerequisite.

Match things like:

- "question: should I renew the domain?"
- "answer this: does the NAS support snapshots?"
- "find out whether the old Docker auth config is still needed"
- "decide whether to keep the subscription"

Do not match ordinary research or implementation tasks where an answer is just one step in the work.

```md
- [?] Decide whether to renew the domain
- [?] Find out whether the NAS supports snapshots
```

### `- [*]` Star

Agent task. Use when the task is assigned to the agent.

Match things like:

- "agent task"
- "for the agent"
- "you take this"
- "this one is yours"

Do not use for priority, importance, favorites, or general emphasis.

```md
- [*] Wire the standup task status examples
```
