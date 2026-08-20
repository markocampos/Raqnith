# Go-Live Checklist — Raqnith (raqnith.duckdns.org)

Follow this order. Do **not** skip ahead; each stage depends on the previous
one. PayMongo's own guidance is mirrored here: complete account verification,
enable payment methods, secure keys, configure webhooks, then run a small real
live transaction before full launch.

## 0. Preflight

- [ ] Production environment uses `config.settings.production` (`DJANGO_SETTINGS_MODULE`)
- [ ] `DJANGO_SECRET_KEY` set to a fresh, random value (never the dev default)
- [ ] `DJANGO_ALLOWED_HOSTS` includes `raqnith.duckdns.org`
- [ ] `DJANGO_CSRF_TRUSTED_ORIGINS` includes `https://raqnith.duckdns.org`
- [ ] `DJANGO_BASE_URL` is `https://raqnith.duckdns.org`
- [ ] PostgreSQL reachable; `migrate` applied (incl. `payments.0005_paymentattempt_redirect_url`)
- [ ] `manage.py check --deploy` shows no critical warnings

## 1. Development + unit tests

- [ ] `python manage.py test` / `pytest` green
- [ ] `ruff check .` clean
- [ ] Cart → checkout → order build → intent flow verified with mocked PayMongo

## 2. PayMongo account

- [ ] Account verified / approved for production
- [ ] Payment methods enabled in the PayMongo dashboard: **QR Ph**, **GCash**, **Maya**
- [ ] Live API keys created (`pk_live_…`, `sk_live_…`)
- [ ] Webhook secret created (`whsk_…`) for the checkout endpoint

## 3. Staging (test keys on HTTPS)

- [ ] Deployed behind HTTPS (Nginx/Cloudflare → Gunicorn → Django)
- [ ] `DEBUG=False`, `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE`/HSTS active
- [ ] PayMongo **test** keys set in production env
- [ ] Webhook endpoint registered: `https://raqnith.duckdns.org/webhooks/paymongo/`

## 4. Payment testing (test mode)

- [ ] **QR Ph**: intent creates, QR image renders inline, scanning settles the
      order via webhook; order page shows "Payment confirmed"
- [ ] **Duplicate submit**: double-clicking Pay creates exactly one attempt/charge
- [ ] **Webhook**: `payment.paid` marks attempt succeeded + order paid; replay is a no-op
- [ ] **Retry**: failed attempt → "Try again" keeps order/email, creates fresh attempt
- [ ] **Recovery**: close the browser mid-payment, reopen `/orders/<id>/` → reconciles
- [ ] **Reconciliation**: run `python manage.py reconcile_payments --dry-run`, then for real

## 5. Security review

- [ ] No secrets in `settings.py`, Git, JavaScript, HTML, or logs
- [ ] Webhook signature verified before processing (HMAC constant-time)
- [ ] Order + payment state machines enforced; no direct paid transition
- [ ] Admin exposes only masked/display-safe payment info

## 6. Live keys + small real transaction

- [ ] Swap in live keys and the live webhook secret
- [ ] Register webhook with the live key pair
- [ ] Perform one small real **QR Ph** payment end-to-end
- [ ] Perform one small real **GCash** payment end-to-end
- [ ] Confirm webhook received and order marked paid

## 7. Refund test

- [ ] Refund the small real transaction via `PaymentService.refund_payment`
      (or admin-triggered refund)
- [ ] Confirm refund `succeeded` and `Refund.provider_refund_id` is populated

## 8. Production launch

- [ ] `collectstatic` run and static served by Nginx
- [ ] Gunicorn running (workers = CPU × 2 + 1), managed by systemd/supervisor
- [ ] `reconcile_payments` scheduled (cron, e.g. every 10 minutes)
- [ ] Logs rotated; payment logger at `INFO`/`WARNING` captures order/attempt ids
- [ ] Monitoring/alerting on webhook 5xx and reconcile errors
- [ ] Full user checkout (QR Ph, GCash, Maya) smoke-tested on the live domain

## Post-launch

- [ ] Watch webhook success rate and reconciliation report for the first week
- [ ] Refunds routed through the `Refund` model (never edit order totals)
