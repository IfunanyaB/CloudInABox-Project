# Usability study analysis plan

**Use only after the required study approval is confirmed and real sessions are complete.** This plan does not contain study results.

## Prepare the data

1. Copy the blank task and questionnaire templates for analysis; retain the original blank templates.
2. Use random participant codes only. Keep consent records and any contact information separately with access limited to the approved research team.
3. Remove request tokens, email addresses, administrator keys, subscription identifiers, and other unnecessary identifiers before analysis.
4. Preserve the raw anonymized rows unchanged. Keep a separate cleaned copy with a note for every transformation.
5. Mark system/API/Azure outages as `blocked_by_system`; do not count them as participant errors or silently remove them. Report how they were handled.

## Task-based results

For each task, report the number of eligible attempts and the number completed successfully, partially, unsuccessfully, or blocked by the system. Report the completion rate with its denominator. Summarize completion times using median and range; include mean and standard deviation only if useful for the small sample and show the number of timed attempts. Report assistance and recurring confusion/error themes with anonymized examples.

Keep portal usability results separate from Azure provisioning reliability, policy-compliance results, and cross-tenant network tests. A task blocked by Azure throttling is a system interruption, not proof of user error.

## SUS scoring, if approved

Use the approved, unmodified ten-item SUS questionnaire and its matching scoring instructions. For each complete response set, score items 1, 3, 5, 7, and 9 as response minus 1; score items 2, 4, 6, 8, and 10 as 5 minus response; sum the ten adjusted values and multiply by 2.5. The resulting score is on a 0–100 scale and is not a percentage. Do not calculate a score from incomplete answers unless the approved protocol defines a missing-data method. Report participant count, median and range alongside any mean; do not present a small study as statistically generalizable.

## Manual-versus-automated comparison

Only compare durations when both methods use the same task scope and start/end definitions. Record the source and date of each manual baseline. Report the paired observations and the difference for each comparable case, then summarize descriptively. Do not compare a scripted test run with a participant's portal session as if they were equivalent workflows.

## Reporting checklist

- Approved protocol version, dates, participant count and participant profile categories.
- Number invited, number who consented, number completing each task, and exclusions with reasons.
- Task results, timing definitions, assistance, system interruptions, questionnaire instrument/version and scoring.
- Whether sessions used a live shared-subscription deployment and how resulting Azure resources were cleaned up.
- Anonymization, storage, retention, withdrawal handling, and limitations.
- No invented or reconstructed results. If no participants complete the study, report that plainly.
