# Friction log

The friction log is open-ended. Anything that slowed you down, confused you or surprised you belongs in it, not only the template steps.

## Files
- `eval/friction_log.csv` holds every row, manual and automatic.
  - Columns: `time_utc, provider, category, step, expected, actual, severity, minutes_lost, feeling, docs_link, fix, source, qid, run_id, raw_file`.
- `eval/friction/friction_summary.csv` has one row per provider, filled in by hand from your recording.
  - Columns: `signup_start_utc, first_success_utc, ttfc_minutes, signup_steps, card_required, free_credits, credits_visible_in_api, docs_pages_before_first_call, errors_before_success, red, yellow, green, biggest_issue`.

**Severity** (Google DevRel friction-log convention): **Green** = minor, **Yellow** = slowed me down, **Red** = blocked me.

**Categories** (optional; any free text also works): `signup`, `auth`, `docs`, `sdk/install`, `params`, `results quality`, `latency`, `rate limit`, `billing/credits`, `dashboard`, `support`, `other`.

## Logging by hand

```bash
# full entry: provider, step, what happened, severity, minutes lost
.venv/bin/python friction/log.py tavily "first call" "401 with Bearer header" red 5 --category auth \
    --expected "200" --docs https://docs.tavily.com/... --fix "key had a trailing newline"

# quick note: anything at all; severity defaults to green
.venv/bin/python friction/log.py note exa "credits only visible after a page refresh" --category dashboard
.venv/bin/python friction/log.py note parallel "v1 moved max_results under advanced_settings" --category params --severity yellow
```

Suggested flow per provider:
1. Start the stopwatch and screen recording, then open the signup page and write `signup_start_utc`.
2. Log each screen, each docs page you needed, and each error as it happens.
3. Write `first_success_utc` at the first 200 response with results. `ttfc_minutes` is the difference.
4. Fill the summary row: card required, free credits, whether remaining credits show in the dashboard and in the API response, and the biggest issue.

## Automatic logging (source = `auto`)

The harness appends a row for every anomaly it sees, tagged with `qid`, `provider`, the promptfoo `run_id` and `raw_file` (the saved raw JSON). Logged: `lib/anomalies.py`, `lib/search.py`, `providers/claude_native.py`.

| Anomaly | Category | Severity |
|---|---|---|
| HTTP 401/403 | auth | Red |
| HTTP 402/432/433 (out of credits / plan limit) | billing/credits | Red |
| HTTP 429 | rate limit | Yellow |
| Other non-2xx, exceptions | other | Yellow |
| Timeout | latency | Yellow |
| In-body error inside an HTTP 200 (Claude `web_search_tool_result_error`) | rate limit / other | Yellow |
| Empty result list | results quality | Green |
| Response schema differs from the docs (documented field missing) | docs | Green |
| Date filter appears ignored (a provider-dated result is older than window start minus 24 h) | params | Yellow |
| Domain filter appears ignored (results from other hosts) | params | Yellow |
| Search latency over the use-case budget | latency | Green |
| Provider-reported cost > 1.5× the price table | billing/credits | Yellow |
| `Deprecation` / `Sunset` / `Warning` headers or a `warning(s)` field in the body | docs | Green |
| Python warnings raised by SDKs or libraries during the call | sdk/install | Green |
| Warm-up call failed; Claude `pause_turn` needed; answer-model refusal or error | other | Green/Yellow |

Set `EVAL_NO_FRICTION_AUTOLOG=1` to switch automatic logging off (the unit tests and the fixture run do this).

## Analysis
`./run.sh analyze` summarizes manual and auto rows per provider, per category and per severity. It writes `out/friction_summary.md` and two charts:
- `out/charts/friction_by_category.png`
- `out/charts/friction_time_to_first_call.png`, from `friction_summary.csv`
