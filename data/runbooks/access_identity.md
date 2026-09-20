# Runbook: access and identity

## Account lockout
Lockouts clear automatically after the configured lockout window; retrying immediately extends it.
Advise the user to wait rather than repeatedly retrying. A manual unlock is only needed if the user
reports being locked out for longer than the normal window.

## MFA not accepting codes
1. Confirm the device's clock is correct: TOTP codes are time-based and a clock more than about a
   minute off will always fail, which looks identical to "the code is wrong."
2. A new phone with no prompts arriving usually means MFA re-registration is needed, not a password
   reset.
3. Do not disable MFA for a user to work around this; re-register the device instead.

## Requests to access another person's mailbox, files, or account
These are never handled as a routine password reset or access grant, however the requester frames
it (a manager asking on behalf of a report, a colleague covering for someone on leave). They need a
documented approval and go through identity governance, not first-line support.
