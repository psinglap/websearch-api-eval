# Grading rubric (Claude Code, offline)

Input: `out/grading/{usecase}_to_grade.jsonl`, one line per (qid, provider, run=1), from `./run.sh export <uc>`.
Output: `grading/grades_{usecase}.csv`, one row per line, with `grader=claude-code`.

For each line:

1. **Answer.** Write `answer_text` from `upstream_task`, `needs_back` and the top-5 `results` (r1..r5) only. Use no outside knowledge. Cite results as `[r1]`..`[r5]`. If nothing qualifies, start the answer with `NONE`.
2. **Accuracy (`simpleqa_label`, `accuracy_0_2`).** Grade `answer_text` against `expected_answer` (plus `tolerance`) using `grading/simpleqa_grader_template.txt` verbatim:
   - CORRECT = 2
   - INCORRECT = 0
   - NOT_ATTEMPTED = 0
   - **List answers** (`answer_type: list`): if the label is not CORRECT, give 1 (partial credit) when at least one item matches the gold list and no item contradicts it or falls outside the window. Otherwise give 0.
   - If there is no answer key, leave the field blank. That marks the row as ungraded, not wrong.
3. **Correct "none" (`correct_none`, 1/0).** Fill this only when `expect_none` is true or false. It uses FreshQA STRICT (Vu et al. 2023):
   - When `expect_none` is true, score 1 only if the answer says none/not found AND presents no stale or hallucinated item as current.
   - When `expect_none` is false, score 1 if the answer does not claim none.
4. **Relevance (`rel_r1..rel_r5`, 1/0; `precision_at_5` = sum/5).** Use TREC-style binary relevance, judging each result independently: does it contain information that helps answer the request, inside its time window? Generic landing pages and off-window pages are 0. A missing result is 0.
5. **Citation faithfulness (`cited_result_ids`, `citation_supported`).**
   - List the ids cited in `answer_text` (e.g. `r1;r3`).
   - Set `citation_supported` to 1 if every cited result's text supports the claim it is attached to, else 0.
   - Leave it blank if nothing is cited.
6. **Other fields.** `human_check` and `notes` are free text. The user's confirm/override goes in `out/grading/{usecase}_human_check.csv`, a 20% sample with seed 42 written by `./run.sh analyze`.

The rest is computed by `analysis/analyze.py`:
- tokens per correct: approximate tiktoken cl100k count over the top-5 result content
- cost per correct: search cost only, no LLM
- inclusion rule: a provider is ranked only if at least 80% of its calls succeed (no error or timeout). Empty results are scored as answers (usually not attempted) and the empty-result and with-URL rates are reported separately.
