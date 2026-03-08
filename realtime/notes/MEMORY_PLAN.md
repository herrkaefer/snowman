# Snowman Realtime Memory Plan

## Summary

Add memory in two layers:

- `long-term memory`: concise, structured notes for stable facts such as family members, preferences, household facts, and schedule notes
- `recent conversations`: raw recent session turns for "you mentioned this earlier" style recall

Use model-driven retrieval, not app-side presearch:

- at session start, inject only a compact long-term `MEMORY.md` summary into the prompt
- during conversation, let the model decide when to call memory tools
- do not change the current "commit audio -> create response immediately" timing

This keeps the current Realtime flow intact and matches the current agent/tool architecture.

## Key Changes

### Storage and data model

Store runtime memory under `realtime/state/` and add that directory to `.gitignore`.

Use these persisted artifacts:

- `realtime/state/memory/MEMORY.md`
  - compact profile/index injected at session start
  - regenerated after long-term memory updates
  - grouped by category, one short line per memory item
- `realtime/state/memory/notes/<category>/<memory_key>.md`
  - one Markdown note per long-term memory item
  - YAML front matter only is read during indexing; body is lazy-loaded only for matched notes
- `realtime/state/memory/recent_sessions/<session_started_at>.jsonl`
  - one file per session
  - keep only the most recent 20 session files

Long-term note categories for v1:

- `people`
- `preferences`
- `household`
- `schedule_notes`

Each long-term note front matter should include:

- `id`
- `category`
- `title`
- `memory_key`
- `keywords`
- `updated_at`
- `source_session_ids`

Each note body should be a short plain-language summary, 1-4 sentences max.

`calendar` in v1 is treated only as remembered schedule notes, not as an authoritative calendar integration.

### Read path and tool surface

Add two read tools to the existing tool registry:

- `long_term_memory_search`
  - params: `query`, optional `categories`, optional `max_results`
  - returns matched memories with `id`, `category`, `title`, `summary`, `updated_at`
- `recent_conversation_search`
  - params: `query`, optional `max_results`, optional `max_sessions`
  - searches the last 20 session files and returns concise turn snippets with timestamps and session ids

Do not add a memory write tool in v1.

Model behavior:

- session prompt includes compact `MEMORY.md`
- prompt explicitly tells the model:
  - use `long_term_memory_search` for older stable facts about the household/user
  - use `recent_conversation_search` for prior chat recall
  - do not guess previous facts if memory tools exist
- automatic recall is model-invoked tool use, not app-side retrieval

### Write path and indexing

Add a session recorder inside the assistant runtime:

- collect every `TranscriptFinal` user utterance
- collect every `ResponseTextDone` assistant utterance
- attach timestamps and current session id
- maintain one in-memory session transcript until session end

At session end:

1. write the raw session transcript to `recent_sessions/...jsonl`
2. prune old recent session files down to 20
3. call an internal memory-extraction helper once for the whole session
4. write/update long-term notes
5. rebuild `MEMORY.md`

The extraction helper should use the existing REST-style helper pattern already used for `web_search`, with one lightweight model call per session. It should output structured JSON with:

- `memory_key`
- `category`
- `title`
- `keywords`
- `summary`
- `should_store`

Use deterministic keys so note updates are stable. Format by category:

- `people:<normalized-name>`
- `preferences:<normalized-topic>`
- `household:<normalized-topic>`
- `schedule_notes:<normalized-label>`

If a note with the same `memory_key` exists, overwrite its front matter/body and refresh `updated_at`; otherwise create it.

Indexing behavior:

- build an in-memory front-matter index at process startup
- refresh the in-memory index after each write
- do not build a separate persistent index file in v1

### Prompt integration and config

Extend the current prompt builder to append long-term memory summary when available.

Add config flags:

- `MEMORY_ENABLED=false` by default
- `MEMORY_RECENT_SESSION_LIMIT=20`
- `MEMORY_DIR=realtime/state/memory`
- `MEMORY_LONGTERM_MAX_RESULTS=3`
- `MEMORY_RECENT_MAX_RESULTS=4`

When `MEMORY_ENABLED=false`:

- do not register memory tools
- do not write transcripts or notes
- preserve current behavior exactly

## Test Plan

- Unit test front matter parsing and lazy body loading for long-term notes
- Unit test recent session retention pruning to last 20 sessions
- Unit test deterministic note upsert by `memory_key`
- Unit test `long_term_memory_search` returns category-filtered concise results
- Unit test `recent_conversation_search` returns matching turn snippets from recent session files
- Unit test session recorder captures `TranscriptFinal` and `ResponseTextDone` in correct order
- Unit test prompt builder includes `MEMORY.md` summary only when present and enabled
- Integration-style test for "session ends -> recent session written -> extraction called -> long-term note updated -> MEMORY.md regenerated"
- Regression check that with memory disabled, existing single-turn and session-window flows are unchanged

Acceptance scenarios:

- User says "my daughter is Xiaomi" in one session; later "what is my daughter's name?" triggers long-term memory lookup and returns the stored fact
- User says "what restaurant were we talking about earlier?" in a later nearby session; recent conversation tool returns a matching recent snippet
- A schedule note such as "next Wednesday at 3 PM dentist appointment" is stored under `schedule_notes`
- No tool call returns full transcript dumps; only concise matched snippets or summaries are returned

## Assumptions and defaults

- Single default user profile only; no speaker diarization or multi-user identity in v1
- Long-term memory is concise and curated; recent-session memory holds raw turn history
- `MEMORY.md` is a compact summary, not the source of truth; the note files are the source of truth
- Auto recall is model-driven tool use because current Realtime flow creates responses before final transcript arrives
- Markdown plus front matter is chosen for long-term memory because it matches the desired inspectable and editable workflow; recent sessions stay JSONL because they are append-friendly
- `pi-mono` style inspiration is limited to the pattern, not a direct port: compact memory summary plus persistent raw history, adapted to the current Snowman Realtime architecture
