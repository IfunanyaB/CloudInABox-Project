# Cloud-in-a-Box usability study task sheet

**Draft for supervisor and ethics review — not authorization to recruit or collect data.** Confirm the approved participant profile, sample size, consent wording, recording plan, retention period, and withdrawal deadline with the university before running the study.

## Study question

Can a non-technical SaaS founder request an isolated cloud environment, understand its status, and interpret its budget and governance information using the Cloud-in-a-Box portal?

## Facilitator setup

- Assign a random participant code (for example, `P01`). Keep any signed consent record separate from study observations.
- Use only fictional organization and contact details supplied by the facilitator. Do not ask participants to enter real business, Azure, or personal account credentials.
- Use a clearly labelled study tenant and agree on provisioning and deprovisioning before the session. A budget alert is not a spending cap; a live Azure request may incur charges.
- Do not provide the platform administrator key to customer participants. If administrator tasks are in the approved study, run them as a separate administrator cohort with a temporary study credential and separate consent.
- Start screen or audio recording only if the approved protocol and participant consent permit it. Exclude or redact private request tokens, keys, emails, and subscription identifiers from any retained recording.
- Record times in UTC and use the same start/end definitions for every participant. Do not coach during a task; record any help given.

## Read to the participant

“Thank you for taking part. Please work through the tasks as you normally would. I’m evaluating the portal, not you. You can stop at any time. Please use only the fictional details I provide, and do not enter personal or business credentials. I may take notes about task completion and difficulties. Any recording will follow the consent form and the approved study plan.”

## Tasks and completion criteria

| ID | Participant prompt | Completion criterion | Timer start | Timer stop |
|---|---|---|---|---|
| T1 | “Request a Development cloud environment for the fictional startup using the details on this card.” | A request is accepted and the portal presents the private reference/token or another documented way to retrieve the request. | When the participant begins interacting with the request page. | When the portal confirms acceptance or the participant gives up. |
| T2 | “Return to the request and find its current status and history.” | Participant retrieves the same request and correctly identifies its current status and at least one history event. | When the participant begins the return/status task. | When the status/history is correctly identified or the participant gives up. |
| T3 | “Find the environment’s Azure region, subscription context, requested budget alert, and provisioning outcome.” | Participant locates the displayed values and distinguishes a budget alert from a spending cap. Mark fields unavailable in the UI as not found; do not infer them. | When the participant begins looking for the environment details. | When all available values are reported or the participant gives up. |
| T4 (optional admin cohort only) | “Review the Azure resource verification, identify one failed or unavailable check, and export the evaluation report.” | Participant finds the verification result, explains one check, and downloads the report. | When the participant begins the admin task. | When the report is downloaded or the participant gives up. |
| T5 | “Does the monthly budget alert stop Azure spending when its threshold is reached? Explain your answer.” | Correct answer: no. It sends an alert; it does not stop deployments, shut down resources, or cap charges. | When the prompt is read. | When the participant answers. |

Use the participant-facing wording as written for every session. The facilitator may repeat the prompt but should not explain the interface or suggest where to click. If a service outage, browser/API failure, or Azure throttling blocks a task, stop the timer, mark the task `blocked_by_system`, and record the observed error without treating it as a participant failure.

## After the tasks

- Administer only the questionnaire approved in the study plan. If that is the System Usability Scale (SUS), use its validated ten items and scoring instructions unchanged.
- Ask the participant for any final comments using neutral prompts such as “What was confusing?” and “What would you change first?”
- Thank the participant and explain the approved withdrawal/contact process.
- Save task-level observations using the blank CSV template. Never put names, email addresses, request tokens, admin keys, or raw Azure credentials in the analysis dataset.

## Study integrity

Do not invent or backfill task times, participant comments, questionnaire scores, baseline results, policy outcomes, or network isolation findings. Report the actual number and type of participants, task failures, assistance, technical interruptions, and limitations. Keep usability findings separate from Azure provisioning and security test results.
