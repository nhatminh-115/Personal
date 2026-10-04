# Bearer-authenticated Automation webhooks

Automations can keep their interval or wall-clock schedule and also accept an
external webhook signal.

## Configure

Enable **Allow secret-authenticated webhook triggers** when creating or editing an
Automation. AURA returns the relative endpoint and a random bearer secret once.
Copy the secret into the external service's secret store. AURA stores only its
SHA-256 digest; the secret cannot be recovered later. To replace a lost or
compromised secret, disable the webhook, save, then enable it and save again.

The endpoint is returned as `webhook_path`, for example:

    /v1/automations/<automation-id>/webhook/events

Use the API base address shown by your deployment. By default AURA binds its
API to loopback; keep it there unless an authenticated access layer protects
remote access.

## Send a signal

Send `POST` with these headers:

    Authorization: Bearer <secret>
    X-Aura-Event-Id: <stable-event-id>

The event ID must contain 1–128 letters, digits, dots, underscores, colons, or
hyphens. Reuse the same ID when retrying the same external event. AURA returns
the original queued event for duplicate deliveries. A different event is
rejected with HTTP 409 while that Automation already has a queued, running, or
approval-paused run.

The request body is ignored and is not stored. The run uses the Automation's
saved instruction and project/session scope, so external payload text cannot
replace the user's instruction. The durable outbox dispatches the run through
the normal approval flow and local-only Automation routing policy.

HTTP `202` means the trigger was queued; it does not mean the Automation run
has completed. Paused automations return `409`. Invalid credentials return
`401`; missing, archived, or unconfigured webhook triggers return `404`.

## Retry a failed run

Run history offers **Retry run** for a failed or dead-lettered execution. AURA
queues a new run with a new event and run ID, using the Automation's current
saved instruction and scope. The request body and payload of the earlier
webhook are not replayed. The new history entry records the source event ID;
the original entry remains unchanged. Retries are available only while the
Automation is enabled and no other run is queued, executing, or waiting for an
approval.
