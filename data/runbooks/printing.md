# Runbook: office printing

## Nothing prints, queue looks stuck
Clearing a stuck queue by restarting the print spooler service resolves the large majority of
cases. Restarting the printer itself rarely helps if the queue is the actual problem.

## Streaky, faded, or blank output on an office printer
Consumables (toner, drum) first; this is very rarely a driver or network issue if only print
quality (not connectivity) is affected.

## Scan-to-email not sending
This is usually the printer's stored SMTP credentials expiring, not a problem with the destination
mailbox. Confirm the destination address is correct before escalating as an email-delivery issue.
