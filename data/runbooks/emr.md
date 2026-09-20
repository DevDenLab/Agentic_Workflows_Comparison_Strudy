# Runbook: EMR (electronic medical record)

## Frozen or unresponsive while charting
1. Confirm the issue is local, not organisation-wide: ask if colleagues on the same unit are affected.
2. Ask the user to note the exact screen and patient context where it froze. Do not have them
   restart the workstation until confirmed no unsaved note can be recovered.
3. A single frozen session on one workstation: restart the EMR client, not the device.
4. Repeated freezes tied to the medication administration record specifically: known interaction
   with a slow print spooler on workstations-on-wheels; restart the print spooler service.
5. If multiple users on the same unit are affected at once, escalate as a potential outage; do not
   treat as a single-user ticket.

## EMR sign-in fails but the network account works
This is usually an EMR-specific credential, not the network password. Do not reset the network
password for this. Escalate to Clinical Applications Support with the exact error text.

## Order entry timing out
Known to correlate with end-of-shift load between 06:45-07:15 and 18:45-19:15. If it recurs outside
those windows, treat as a possible interface outage to the lab or pharmacy system and escalate P1.
