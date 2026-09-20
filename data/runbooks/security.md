# Runbook: security incidents

## Suspected phishing
Do not click links or open attachments in the reported message. Do not forward the message to other
staff "to warn them"; forwarding spreads a live payload. Preserve the original message; do not
delete it before it has been reviewed.

## Possible credential compromise (password entered on a fake site, unfamiliar sign-ins)
Treat as urgent regardless of how minor the user thinks it is. A password reset alone is not
sufficient if MFA may also be compromised (e.g. the user also approved an unexpected MFA prompt);
that combination needs a security review, not just a reset.

## Lost or stolen device
The organisation's data-protection duty starts the moment the device is reported missing, not when
it is confirmed lost for good. Record what was on the device (patient data, saved credentials) as
part of the initial report; that detail changes how urgently it needs to be handled.

## Ransomware / files suddenly encrypted or inaccessible with a ransom note
Isolate the device from the network immediately (unplug it / disable Wi-Fi) rather than trying to
read or interact with the note. This is the one situation where doing nothing else first is correct.
