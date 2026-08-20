Yes — I’d build this as a **custom Django checkout using PayMongo Payment Intents**, not PayMongo Checkout Pages. That gives you control over the entire payment UI, validation, loading states, errors, order state, and confirmation screen. PayMongo explicitly positions Payment Acceptance/Payment Intents for teams building their own checkout experience. ([PayMongo][1])

There is one hard limitation we should design around: **a completely zero-redirect payment system is not possible for every PayMongo payment method**. Normal card payments may complete inside your site, but cards requiring 3-D Secure must send the customer to their bank authentication flow. GCash/Maya/etc. also require provider authentication. We can make those transitions feel seamless and immediately return the customer to the same branded checkout. ([PayMongo][2])

# Django + PayMongo Project Blueprint

## Main objective

Build a payment system with:

* Django backend
* PostgreSQL
* PayMongo Payment Intent API
* Custom checkout interface
* Card payment without PayMongo Hosted Checkout
* QR Ph
* Optional GCash/Maya later
* Strong frontend + backend validation
* Verified PayMongo webhooks
* Duplicate-payment prevention
* Order/payment reconciliation
* Retry flow
* Mobile-first checkout
* Automated tests
* Audit trail
* Secure production deployment
* Minimal user friction

For a conservative production base, I would use **Django 5.2 LTS**, currently supported with security/data-loss fixes through April 2028. Django 6.1 was released August 5, 2026, and is also viable if you prefer newer framework features and accept a sooner framework-upgrade cycle. ([Django Project][3])

---

# PHASE 0 — Define the Payment Architecture

Before coding, lock this rule:

```text
Customer Browser
      ↓
Django Checkout
      ↓
Django creates Order
      ↓
Django creates PayMongo Payment Intent
      ↓
Browser receives client_key
      ↓
Customer enters card
      ↓
Browser → PayMongo directly
      ↓
Payment Method created
      ↓
Browser attaches Payment Method
      ↓
 ┌───────────────┬────────────────────┐
 │ succeeded     │ awaiting_next_action
 │               │
 ↓               ↓
Success page    3DS / Bank authentication
                 ↓
             Return to Django
                 ↓
           Django verifies status
                 ↓
             Success page

Meanwhile:

PayMongo
   ↓
Webhook
   ↓
Django
   ↓
Verify Signature
   ↓
Update Payment + Order
```

### Critical security rule

The card number, expiry and CVC should **never be submitted to Django**.

The browser creates the Payment Method directly with PayMongo using your **public API key**. Your Django backend keeps only the secret key and creates/retrieves Payment Intents. PayMongo specifically warns that sending card data through your own server increases your PCI DSS scope. ([PayMongo][4])

So Django should never have fields like:

```python
card_number
card_cvc
card_expiry
```

in a model, log, session or POST handler.

---

# PHASE 1 — Project Foundation

Suggested structure:

```text
project/
│
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   ├── test.py
│   │   └── production.py
│   │
│   ├── urls.py
│   └── wsgi.py
│
├── apps/
│   ├── accounts/
│   ├── catalog/
│   ├── cart/
│   ├── orders/
│   └── payments/
│
├── templates/
│   ├── checkout/
│   └── payments/
│
├── static/
│   ├── css/
│   └── js/
│       └── checkout.js
│
├── tests/
│
├── manage.py
├── requirements.txt
└── .env
```

### Initial stack

```text
Django 5.2 LTS
PostgreSQL
httpx
python-decouple or environment variables
Gunicorn
Nginx / managed reverse proxy
```

I would use `httpx` rather than burying payment calls inside views.

Create:

```text
payments/services/paymongo.py
```

All PayMongo communication goes through this service.

---

# PHASE 2 — Database Design

The most important mistake to avoid is treating an order and a payment as the same thing.

They are separate state machines.

## Order

Example:

```python
class Order(models.Model):

    class Status(models.TextChoices):
        DRAFT = "draft"
        PENDING_PAYMENT = "pending_payment"
        PAID = "paid"
        CANCELLED = "cancelled"
        PAYMENT_FAILED = "payment_failed"
        FULFILLED = "fulfilled"

    id = models.UUIDField(...)
    user = models.ForeignKey(...)
    status = models.CharField(...)
    
    subtotal_amount = models.PositiveBigIntegerField()
    discount_amount = models.PositiveBigIntegerField(default=0)
    total_amount = models.PositiveBigIntegerField()

    currency = models.CharField(default="PHP", max_length=3)

    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True)
```

Store money in **centavos**, not float.

Example:

```text
₱499.00

database:

49900
```

PayMongo also expresses PHP Payment Intent amounts in centavos. ([PayMongo][4])

---

# PHASE 3 — Payment Model

Create a separate payment attempt model.

```python
class PaymentAttempt(models.Model):

    class Status(models.TextChoices):
        CREATED = "created"
        AWAITING_METHOD = "awaiting_method"
        AWAITING_ACTION = "awaiting_action"
        PROCESSING = "processing"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        CANCELLED = "cancelled"

    id = models.UUIDField(...)

    order = models.ForeignKey(
        Order,
        related_name="payment_attempts",
        on_delete=models.PROTECT
    )

    provider = models.CharField(default="paymongo")

    paymongo_intent_id = models.CharField(
        max_length=100,
        unique=True,
        null=True
    )

    amount = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)

    status = models.CharField(...)

    payment_method = models.CharField(
        max_length=30,
        blank=True
    )

    failure_code = models.CharField(
        max_length=100,
        blank=True
    )

    failure_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

This lets a customer do:

```text
Order #ABC

Attempt #1
Card → declined

Attempt #2
Card → 3DS failed

Attempt #3
Card → succeeded
```

without corrupting the order.

---

# PHASE 4 — Cart → Checkout Validation

Never calculate the final amount from browser values.

Bad:

```javascript
fetch("/pay/", {
    body: JSON.stringify({
        amount: 499
    })
})
```

A user can modify that.

Instead:

```text
Browser:

cart_id = ABC123
coupon = SUMMER10
shipping_method = standard
```

Then Django calculates:

```text
Product price
+ quantity
- discount
+ shipping
+ tax
----------------
FINAL SERVER TOTAL
```

Only this total becomes the PayMongo amount.

## Validation layers

### Client validation

Used for UX:

```text
Required fields
Email format
Phone formatting
Postal code
Card formatting
Expiration format
CVC length
Terms checkbox
```

### Django validation

Used for security:

```text
Product exists
Product available
Correct price
Valid coupon
Valid quantity
Valid shipping option
Currency allowed
Minimum transaction valid
Order belongs to current user/session
Order is not already paid
```

### PayMongo validation

Used for payment details:

```text
Valid card
CVC
Expiry
Issuer response
3DS
Fraud checks
```

PayMongo recommends letting PayMongo validate card information rather than storing or processing those sensitive details yourself. ([PayMongo][5])

---

# PHASE 5 — Checkout UI/UX Design

I would use a **single-page checkout**, not a five-page wizard.

Desktop:

```text
┌───────────────────────────────────────────────┐

                  Secure Checkout

┌─────────────────────┐ ┌─────────────────────┐
│ CONTACT             │ │ ORDER SUMMARY       │
│                     │ │                     │
│ Email               │ │ Product             │
│ Phone               │ │ Qty × Price         │
│                     │ │                     │
├─────────────────────┤ │ Subtotal            │
│ BILLING             │ │ Shipping            │
│                     │ │ Discount            │
│ Name                │ │ ─────────────       │
│ Address             │ │ Total               │
│ City                │ │                     │
│ Postal code         │ └─────────────────────┘
│                     │
├─────────────────────┤
│ PAYMENT             │
│                     │
│ ● Card              │
│ ○ QR Ph             │
│ ○ GCash             │
│ ○ Maya              │
│                     │
│ Card number         │
│ MM / YY     CVC     │
│                     │
│ [ Pay ₱2,499.00 ]   │
└─────────────────────┘
```

Mobile:

```text
ORDER SUMMARY
    ↓
CONTACT
    ↓
BILLING
    ↓
PAYMENT
    ↓
sticky bottom button

PAY ₱2,499
```

---

# PHASE 6 — UX Friction Reduction

Do not make users press unnecessary buttons.

For example:

### Bad

```text
Checkout
↓
Continue
↓
Payment method
↓
Continue
↓
Review
↓
Confirm
↓
Pay
```

### Better

```text
Checkout
↓
Enter details
↓
Choose payment
↓
Pay ₱2,499
```

Use inline validation.

Example:

```text
Email
john@
      ❌ Enter a complete email address
```

Then immediately change:

```text
john@gmail.com
✓
```

Don't throw an alert box after submitting the entire page.

---

# PHASE 7 — Create Payment Intent

Your Django endpoint:

```text
POST /payments/create-intent/
```

Process:

```text
1. Authenticate/session validation
2. Retrieve checkout/order
3. Lock order
4. Verify order is unpaid
5. Recalculate amount
6. Create PaymentAttempt
7. Call PayMongo
8. Save Payment Intent ID
9. Return public information to browser
```

Response example:

```json
{
    "payment_id": "ae24...",
    "payment_intent_id": "pi_...",
    "client_key": "...",
    "amount": 249900,
    "currency": "PHP"
}
```

PayMongo's documented workflow is exactly this separation: the backend creates the Payment Intent with the secret key and returns the intent/client information required for frontend payment operations. ([PayMongo][6])

---

# PHASE 8 — Card Payment

Now your JavaScript runs.

```text
Customer enters card
      ↓
checkout.js
      ↓
PayMongo /payment_methods
      ↓
Payment Method ID
      ↓
Attach Payment Method
      ↓
Payment Intent
```

Importantly:

```text
Browser ────────────────→ PayMongo
         Card data
```

not:

```text
Browser → Django → PayMongo
          ❌
```

---

# PHASE 9 — Payment State Handler

After attachment, handle the PayMongo intent state explicitly.

PayMongo currently documents these principal Payment Intent states:

```text
awaiting_payment_method
awaiting_next_action
processing
succeeded
```

A failed attempt can return the Payment Intent to `awaiting_payment_method`, with the error available through `last_payment_error`. ([PayMongo][4])

So your JavaScript logic should conceptually be:

```javascript
switch (status) {

    case "succeeded":
        verifyPayment();
        break;

    case "awaiting_next_action":
        handleAuthentication();
        break;

    case "processing":
        pollStatus();
        break;

    case "awaiting_payment_method":
        showPaymentError();
        unlockForm();
        break;
}
```

---

# PHASE 10 — 3D Secure

This deserves special attention.

PayMongo applies 3DS 2.0 to card payments where required. When triggered, PayMongo supplies:

```text
next_action.redirect.url
```

and the user authenticates through their bank. ([PayMongo][2])

The experience becomes:

```text
YOUR CHECKOUT
     ↓
Pay button
     ↓
Processing...
     ↓
Bank authentication
     ↓
OTP / biometric
     ↓
YOUR SITE
     ↓
"Confirming your payment..."
     ↓
Success
```

Return URL:

```text
https://example.com/payments/return/
```

Do **not** immediately say:

```text
PAYMENT SUCCESSFUL
```

when the customer returns.

Instead:

```text
return
↓
server retrieves Payment Intent
↓
verify actual provider state
↓
show result
```

PayMongo explicitly recommends server-side confirmation and warns against trusting redirect parameters alone. ([PayMongo][5])

---

# PHASE 11 — Webhooks

This is the heart of the reliable payment system.

Endpoint:

```text
POST /webhooks/paymongo/
```

Example flow:

```text
PayMongo
   ↓
payment.paid
   ↓
Webhook endpoint
   ↓
Validate signature
   ↓
Check duplicate event
   ↓
Find PaymentAttempt
   ↓
Check amount/currency
   ↓
Set payment = succeeded
   ↓
Set order = paid
   ↓
Commit DB transaction
```

Never trust:

```text
Frontend says:
"payment succeeded"
```

Instead:

```text
PayMongo webhook
+
server-side Payment Intent verification
=
payment truth
```

PayMongo states that webhook notifications are the production mechanism for payment outcomes and requires verification using the webhook signature. ([PayMongo][5])

---

# PHASE 12 — Webhook Replay Protection

Create:

```python
class WebhookEvent(models.Model):

    provider_event_id = models.CharField(
        max_length=150,
        unique=True
    )

    event_type = models.CharField(max_length=100)

    payload = models.JSONField()

    processed = models.BooleanField(default=False)

    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True)
```

Then:

```text
Receive webhook

event already exists?
     │
   yes ─→ return 200
     │
     no
     ↓
process
```

This makes processing idempotent on your side.

---

# PHASE 13 — Duplicate Payment Prevention

Very important.

Imagine the customer double-clicks:

```text
PAY NOW
PAY NOW
PAY NOW
```

The frontend should immediately:

```javascript
button.disabled = true
```

and display:

```text
Processing payment...
```

But frontend protection alone is insufficient.

Backend:

```python
with transaction.atomic():

    order = (
        Order.objects
        .select_for_update()
        .get(id=order_id)
    )

    if order.status == Order.Status.PAID:
        raise AlreadyPaid()
```

And maintain only one active PaymentAttempt for a given checkout operation.

---

# PHASE 14 — Retry Without Losing Checkout Data

Suppose:

```text
Card declined
```

Do NOT send them back to the cart.

Show:

```text
Payment wasn't completed

Your card was declined.

[ Try another card ]

Order total: ₱2,499
```

Keep:

```text
name
email
address
shipping
cart
coupon
```

Only reset payment-sensitive information.

That gives much lower friction.

---

# PHASE 15 — Error Design

Don't display:

```text
API_ERROR_CODE_400
```

Translate provider errors.

Example:

```text
insufficient funds
↓
Your card doesn't have enough available funds.
Try another card or payment method.
```

```text
invalid CVC
↓
Please check your card security code.
```

```text
expired card
↓
This card appears to be expired.
```

```text
network timeout
↓
We're still checking your payment.
Please don't submit another payment yet.
```

That last state is especially important.

A timeout does **not necessarily mean payment failure**.

---

# PHASE 16 — Processing Recovery

Suppose the customer closes the tab during:

```text
processing
```

When they return:

```text
/order/ABC/
```

the system should check:

```text
Order paid?
    ↓
yes → receipt

Pending PaymentAttempt?
    ↓
yes → retrieve provider status

Failed?
    ↓
retry payment
```

This prevents abandoned or ambiguous payments.

---

# PHASE 17 — QR Ph

For the lowest-friction on-site alternative, I would strongly consider:

```text
Card
QR Ph
GCash
Maya
```

with QR Ph second.

PayMongo's Payment Intent API can return a QR image for QR Ph instead of redirecting the checkout page. ([PayMongo][4])

Your interface:

```text
Pay with QR Ph

┌───────────────────┐
│                   │
│      QR CODE      │
│                   │
└───────────────────┘

Scan using your banking or e-wallet app.

Amount
₱2,499.00

Waiting for payment...

● ● ●
```

Frontend can poll:

```text
/payment-status/{uuid}/
```

every few seconds while the webhook remains the authoritative backend event.

When payment arrives:

```text
✓ Payment received
```

No page reload required.

---

# PHASE 18 — GCash / Maya

These can still appear as beautiful payment buttons inside your checkout:

```text
┌────────────────────────┐
│ Pay with GCash         │
└────────────────────────┘

┌────────────────────────┐
│ Pay with Maya          │
└────────────────────────┘
```

But provider authentication requires leaving your page temporarily. PayMongo documents redirects for e-wallet payment completion. ([PayMongo][4])

So make the experience:

```text
Your checkout
↓
GCash
↓
authentication
↓
return to yoursite.com/payment/return
↓
"Confirming payment..."
↓
success
```

Not:

```text
GCash
↓
random homepage
```

---

# PHASE 19 — Checkout State Machine

I recommend implementing explicit state transitions.

```text
ORDER

DRAFT
  ↓
PENDING_PAYMENT
  ↓
PAID
  ↓
FULFILLED
```

Possible failure:

```text
PENDING_PAYMENT
       ↓
PAYMENT_FAILED
       ↓
PENDING_PAYMENT
       ↓
PAID
```

Payment:

```text
CREATED
    ↓
AWAITING_METHOD
    ↓
AWAITING_ACTION
   /          \
3DS          none
 ↓             ↓
PROCESSING ←───┘
    ↓
SUCCEEDED
```

Or:

```text
PROCESSING
    ↓
FAILED
```

Explicit state transitions will save you from a lot of payment bugs.

---

# PHASE 20 — API Endpoint Blueprint

I would expose roughly these routes:

```text
GET
/checkout/

POST
/checkout/validate/

POST
/payments/intents/

GET
/payments/<uuid>/status/

POST
/payments/<uuid>/retry/

GET
/payments/return/

POST
/webhooks/paymongo/

GET
/orders/<uuid>/success/

GET
/orders/<uuid>/receipt/
```

Internally:

```text
payments/
├── models.py
├── urls.py
├── views.py
├── forms.py
├── selectors.py
├── services/
│   ├── paymongo.py
│   ├── payment_service.py
│   └── webhook_service.py
└── tests/
```

Keep PayMongo code out of `views.py`.

---

# PHASE 21 — PayMongo Service Layer

Conceptually:

```python
class PayMongoClient:

    def create_payment_intent(...):
        ...

    def retrieve_payment_intent(...):
        ...

    def refund_payment(...):
        ...

    def verify_webhook(...):
        ...
```

Then business logic:

```python
class PaymentService:

    def initiate_payment(...):
        ...

    def mark_payment_succeeded(...):
        ...

    def mark_payment_failed(...):
        ...

    def reconcile_payment(...):
        ...
```

This makes testing much easier.

---

# PHASE 22 — Security Hardening

Production settings should include:

```python
DEBUG = False

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SECURE_SSL_REDIRECT = True

SECURE_HSTS_SECONDS = ...
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

X_FRAME_OPTIONS = "DENY"
```

Django recommends HTTPS, secure session/CSRF cookies, HSTS and proper CSRF protection for production systems. ([Django Project][7])

Also:

```text
Secret PayMongo key
↓
environment variable / secrets manager

never:
settings.py
Git
JavaScript
HTML
logs
```

PayMongo likewise requires secret API keys to remain server-side and recommends environment variables or secret management. ([PayMongo][5])

---

# PHASE 23 — Logging Strategy

Payment logs should contain:

```text
order_id
payment_attempt_id
PayMongo intent ID
status transition
webhook type
HTTP response status
timestamp
correlation ID
```

Never log:

```text
PAN/card number
CVC
full sensitive payment payload
Authorization header
secret key
```

---

# PHASE 24 — Testing

This part should be extensive.

PayMongo provides a test environment with test API keys where no real transaction is processed. ([PayMongo][8])

## Unit tests

Test:

```text
order calculation
discount calculation
invalid quantities
invalid coupon
paid order cannot pay again
payment state transitions
webhook parsing
signature rejection
duplicate webhook handling
```

## Integration tests

Mock PayMongo:

```text
create intent success
create intent failure
timeout
HTTP 400
HTTP 401
HTTP 429
HTTP 500
```

---

# PHASE 25 — PayMongo Card Test Matrix

PayMongo currently provides test cards for several scenarios. ([PayMongo][8])

Your QA matrix should include at minimum:

| Scenario           | Expected behavior              |
| ------------------ | ------------------------------ |
| Successful card    | Order becomes paid             |
| 3DS card           | Authentication → return → paid |
| Expired card       | Inline friendly error          |
| Invalid CVC        | Inline friendly error          |
| Insufficient funds | Retry available                |
| Generic decline    | Retry available                |
| User cancels 3DS   | Checkout preserved             |
| Network timeout    | Verify status before retry     |
| Duplicate submit   | One actual order payment       |
| Duplicate webhook  | Process once                   |
| Browser refresh    | State restored                 |
| Close browser      | Payment reconciliation works   |

---

# PHASE 26 — PayMongo Test Cases

Examples documented by PayMongo include:

```text
4343434343434345
Successful — no 3DS

4120000000000007
3DS required

4200000000000018
Expired

4300000000000017
Invalid CVC

5100000000000198
Insufficient funds
```

These are for PayMongo test mode only. ([PayMongo][8])

---

# PHASE 27 — Race-Condition Tests

Test:

```text
User double-clicks Pay
```

```text
Webhook arrives twice
```

```text
Webhook arrives before redirect
```

```text
Redirect arrives before webhook
```

```text
User closes browser before webhook
```

```text
Two browser tabs pay the same order
```

```text
Provider succeeds while browser reports timeout
```

These are the tests that separate a demo payment integration from a production one.

---

# PHASE 28 — Success Page

Don't make it just:

```text
Payment successful!
```

Better:

```text
✓ PAYMENT CONFIRMED

Thank you, Juan.

Order
#PM-2026-00542

Amount
₱2,499.00

Payment
Visa •••• 4242

Email
juan@example.com

We've sent your order confirmation.

[ View Order ]
```

If fulfillment takes time:

```text
Payment confirmed
↓
Preparing your order
```

This communicates exactly what happened.

---

# PHASE 29 — Payment Admin Dashboard

Django admin should show:

```text
Order ID
Customer
Order total
Payment status
Payment method
PayMongo Intent
Created
Paid
Failure reason
Webhook status
```

Filters:

```text
Paid
Failed
Pending
Processing
Requires action
Refunded
```

Do not show raw card data.

---

# PHASE 30 — Reconciliation System

Add a management command:

```bash
python manage.py reconcile_payments
```

It finds:

```text
processing > 5 minutes
pending > 30 minutes
ambiguous webhook state
```

Then queries PayMongo and repairs local state.

This is a good safety net for production outages.

---

# PHASE 31 — Refund Architecture

Don't modify order totals to represent refunds.

Create:

```python
class Refund(models.Model):

    payment = models.ForeignKey(PaymentAttempt, ...)
    amount = models.PositiveBigIntegerField()

    provider_refund_id = models.CharField(...)
    reason = models.CharField(...)

    status = models.CharField(...)

    created_at = models.DateTimeField(...)
```

Possible statuses:

```text
pending
succeeded
failed
```

---

# PHASE 32 — Production Deployment

Recommended:

```text
Internet
   ↓
Cloudflare / load balancer
   ↓
HTTPS
   ↓
Nginx
   ↓
Gunicorn
   ↓
Django
   ↓
PostgreSQL
```

Optional:

```text
Redis
↓
Celery
```

for:

```text
email receipts
reconciliation
webhook side effects
analytics
notifications
```

Do not make payment confirmation itself dependent on an email worker.

---

# PHASE 33 — Go-Live Process

PayMongo recommends completing account verification, enabling the desired payment methods, securing keys, configuring webhooks, and then performing a small real live payment before full launch. ([PayMongo][9])

Our rollout should therefore be:

```text
Development
↓
Unit tests
↓
PayMongo test environment
↓
Staging HTTPS
↓
3DS testing
↓
Webhook testing
↓
Security review
↓
Live API keys
↓
₱small real transaction
↓
Refund test
↓
Production launch
```

---

# Recommended Final Architecture

I would ultimately build this:

```text
                    ┌──────────────┐
                    │ PostgreSQL   │
                    └──────▲───────┘
                           │
┌──────────┐        ┌──────┴────────┐
│ Browser  │◄──────►│ Django        │
│ Checkout │        │ Application   │
└────┬─────┘        └──────▲────────┘
     │                     │
     │ Payment Method      │ Secret API
     │ Public API key      │
     ▼                     ▼
┌───────────────────────────────────┐
│             PayMongo              │
│                                   │
│ Payment Intent                    │
│ Payment Method                    │
│ 3DS                               │
│ QR Ph                             │
│ GCash/Maya                        │
└─────────────────┬─────────────────┘
                  │
                  │ Webhook
                  ▼
            ┌─────────────┐
            │ Django      │
            │ Verification│
            └─────────────┘
```

# What I would build first

The cleanest implementation order is:

**V1**

```text
Django project
→ User/cart
→ Order model
→ Checkout UI
→ PayMongo Payment Intent
→ Card Payment Method
→ Card payment
→ 3DS handling
→ Webhook
→ Payment state machine
→ Success/retry screens
→ automated tests
```

**V1.1**

```text
QR Ph
→ live status polling
```

**V1.2**

```text
GCash
Maya
```

**V1.3**

```text
Refunds
receipts
admin payment dashboard
reconciliation
```

**V2**

```text
saved cards
subscriptions
advanced fraud rules
analytics
Celery
payment monitoring
```

## Strongest UX recommendation 🎯

For the first production version, I would launch with:

```text
CARD
+
QR PH
+
GCASH
+
MAYA
```

while keeping the checkout fully branded on your site.

Card data:

```text
Browser → PayMongo
```

Order/payment logic:

```text
Browser → Django
```

Payment truth:

```text
PayMongo → verified webhook → Django
```

That architecture gives you **low checkout friction without taking unsafe custody of raw card data**, while still supporting the bank authentication requirements that PayMongo documents for 3DS and e-wallet transactions. ([PayMongo][4])

The next practical step should be **Phase 1 implementation**: create the Django project, `orders` and `payments` apps, database models, PayMongo service class, `.env` configuration, URLs, and the first working custom card checkout. From there, we can implement it phase-by-phase rather than dropping a huge untested codebase all at once.

[1]: https://docs.paymongo.com/docs/payment-acceptance-introduction "Introduction"
[2]: https://docs.paymongo.com/docs/payment-acceptance-cards "Cards"
[3]: https://www.djangoproject.com/download/?utm_source=chatgpt.com "Download Django"
[4]: https://docs.paymongo.com/docs/payment-acceptance-key-concepts "Key concepts"
[5]: https://docs.paymongo.com/docs/payment-acceptance-best-practices "Best practices"
[6]: https://docs.paymongo.com/docs/payment-acceptance-quick-start?utm_source=chatgpt.com "Quick start"
[7]: https://docs.djangoproject.com/en/6.1/topics/security/?utm_source=chatgpt.com "Security in Django"
[8]: https://docs.paymongo.com/docs/payment-acceptance-testing "Testing"
[9]: https://docs.paymongo.com/docs/get-started-go-live-checklist "Go-live checklist"
