# Multi Webhook Delivery Design

## Goal

Allow the existing Enterprise WeChat forwarding service to send each generated message to multiple robot webhook URLs while keeping the existing single `WECHAT_WEBHOOK_URL` configuration working.

## Behavior

- `WECHAT_WEBHOOK_URL` remains supported for single-robot deployments.
- `WECHAT_WEBHOOK_URLS` adds multi-robot support with comma separated URLs; the parser also tolerates newline separated values when supplied by the environment.
- When `WECHAT_WEBHOOK_URLS` is set, it is the source of truth for delivery targets.
- Each outbound message is attempted for every configured robot.
- If any target fails, the service reports a send failure after attempting the remaining targets.
- Logs identify targets by position only, never by full webhook URL.

## Files

- `main.py`: parse webhook target configuration and fan out delivery.
- `.envtemple`: document the new multi-target environment variable.
- `README.md`: document configuration and failure behavior.
- `tests/test_wechat_webhooks.py`: cover parsing, fan-out, and partial failure behavior with stdlib tests.

## Non-Goals

- No per-message routing rules.
- No retry queue.
- No parallel HTTP delivery.
- No support for non-WeChat robot payload formats.
