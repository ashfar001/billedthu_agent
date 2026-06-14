# Bill Eduthu Webapp / Backend Changes Needed

Do not change the webapp blindly. These are the backend/admin features the
agent now expects.

## Activation

- Add `POST /api/agent/activate/`.
- Request:
  - `setup_code`
  - `machine_name`
- Response:
  - `device_id`
  - `device_secret`
  - `store_code`
  - `counter_id`
  - `merchant_name`
  - `upload_url`
- Setup codes should be single-use, expiring, regeneratable, and revocable.
- Setup code statuses: `UNUSED`, `USED`, `EXPIRED`, `REVOKED`.

## Upload

- Accept uploads at `upload_url` or `/api/bills/upload/`.
- Verify headers:
  - `X-Device-ID`
  - `X-Timestamp`
  - `X-Signature`
- Signature rule:
  - `HMAC_SHA256(device_secret, canonical_json_body + timestamp)`
- Accept multipart upload fields:
  - `device_id`
  - `store_code`
  - `counter_id`
  - `table_id`
  - `merchant_name`
  - `receipt_json`
  - `raw_text`
  - `parser_confidence`
  - `upload_status`
  - `file`

## Heartbeat / Device Monitoring

- Add or update `POST /api/agent/heartbeat/`.
- Track device last seen, online/offline, version, queue counts, and revoked status.
- Return:
  - `agent_disabled`
  - `update_required`
  - `latest_version`
  - `download_url`
  - `sha256`
  - `mandatory_update`

## Version Check

- Add `GET /api/agent/version/`.
- Return update information for the dashboard and future auto-update flow.

## Super Admin

- Device page should show device ID, merchant/store, counter, setup code status,
  activated machine name, last seen, agent version, and online/offline status.
- Add actions to generate/regenerate/revoke setup codes and revoke devices.
