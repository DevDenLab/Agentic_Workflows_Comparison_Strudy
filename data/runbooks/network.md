# Runbook: network connectivity

## VPN drops repeatedly
1. Confirm this is a repeated pattern (every N minutes) rather than a one-off: a fixed interval
   points to the client's keep-alive/idle-timeout setting, not the gateway.
2. Ask whether other remote-access users report the same symptom right now; if yes, this is a
   gateway-side issue, escalate rather than troubleshooting the individual client further.
3. Restarting the VPN client resolves most single-user cases; restarting the whole computer rarely
   adds anything beyond that.

## Wi-Fi unreliable in a specific physical area
Chronic Wi-Fi trouble confined to one room or hallway is almost always an access-point coverage gap,
not a client device fault. Note the exact location for the network team; do not spend time
re-imaging or swapping devices for a coverage problem.

## "No internet" but internal apps still work
This pattern (internal reachable, internet not) points at DNS or a proxy/firewall rule, not a
physical link problem. A physical link problem breaks both at once.
