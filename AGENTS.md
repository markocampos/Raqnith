# AGENTS.md — Raqnith Marketplace Guide

> **For all agents working on this codebase: Build the user-facing marketplace, not the backend.**
> This document defines what the *buyer* sees, feels, and trusts. No infrastructure jargon should leak into the UI.

---

## 1. Mission: Safe Marketplace for Digital Products

**Raqnith is a curated digital product marketplace** — developer kits, boilerplates, templates, and digital assets for instant download.

The buyer should understand in 5 seconds:
- This is a **real marketplace** with purchasable products (not a demo/payment test)
- Buying is **instant, familiar, and safe** — same QR Ph / GCash / Maya they use daily
- They will get what they paid for **immediately**, with proof

**Core user:** Anyone in the Philippines buying a digital product. Assume first-time visitor, on mobile, skeptical of new stores.

---

## 2. What the Buyer Sees — UI Map Only

Never expose internals (`Payment Intent`, `webhook`, `PayMongo API`, `centavos`, `3D Secure`, `reconciliation`). Buyers see:

```
Landing → Browse Catalog → Product Detail → Cart → Checkout → Confirmation → Order History (Profile)
```

| Page | Buyer Question | Must Answer Instantly |
|------|---------------|-----------------------|
| **Header** | Can I navigate and trust this store? | Logo, Home, Products, Cart (count), Sign In / Register |
| **Hero** | What is Raqnith? | "Digital products, instant checkout with QR Ph & e-wallets" + 2 CTAs: Browse / Create Account |
| **Metrics Bar (hero)** | Why trust this new place? | 3 proof pills — see §3 |
| **Featured Products** | Is this marketplace alive? | 6+ real cards with price, category, image, "In Stock", Add to Cart + Details |
| **Why Raqnith / How It Works / Trust** | Is checkout safe and easy? | PH-specific, no jargon. 3 steps: Select → Scan → Instant Access |
| **Testimonials** | Do others buy here? | Social proof, PH names/cities, 5-star |
| **Cart** | What am I buying? | Line items, total, trust footer (GCash/Maya/banks/SSL) |
| **Checkout** | Is my money safe? | Order summary, email for delivery, QR Ph preview, terms, Pay button with total |
| **Confirmation / Receipt** | Did I get it? | Order ID, paid badge, download, email sent, receipt download |

**Rule:** If a label/section would confuse a non-developer buying an e-book, remove it.

---

## 3. Core Value Props — Use These Exact Pillars Everywhere

Use consistently in hero, product pages, cart, checkout, footer, and empty states. Icons are already wired (`zap`, `qr-code`, `shield-check`).

**1. Instant Delivery**
- `Direct downloads & receipts`
- Detail: "Your download + receipt are ready the second payment confirms. No waiting, no manual approval."
- Show on: hero metrics, product card footer, cart guarantee box, checkout guarantee box, success page

**2. QR Ph & E-Wallets**
- `GCash, Maya & 40+ PH banks`
- Detail: "Scan with any PH banking app — GCash, Maya, BPI, BDO, UnionBank, ShopeePay, GoTyme, SeaBank and 40+ more. Zero fees, official QR Ph standard."
- Show on: hero metrics, QR badge card on checkout, payment method strip, footer payment icons, trust banner

**3. 100% Protected**
- `Bank-grade encrypted checkout`
- Detail: "BSP-regulated payment channels via PayMongo. 256-bit SSL. We never see or store your card/bank details."
- Show on: hero metrics, trust banner, checkout security chip, footer legal column

**Never write:** "Payment Intent", "webhook", "PayMongo Checkout", "test card", "centavos". Write: "Secure checkout powered by PayMongo".

---

## 4. Safe Space Validation — How We Prove Trust in the UI

A new marketplace must *prove* safety visually. Every page should layer at least 2 of these:

### A. Familiar Rails Signal
- Show real PH payment logos: `GCash`, `Maya`, `BPI`, `BDO`, `UnionBank` as pills/chips — not abstract "e-wallet"
- Copy: "Pay the way you already pay — scan with your usual app"
- Checkout badge: `QR Ph • Zero Fee • Instant Confirm` (green, not blue)

### B. Encryption & Privacy Signal
- Footer `Trust & Legal`: Privacy Policy, Terms, Payment Security (all linked)
- Micro-copy near email/pay button: "🔒 Encrypted & never shared. Receipt sent to this email."
- Trust banner (`section-trust`): "Your Information Stays Safe & Private" → "BSP-regulated channels… We never see, store, or share your sensitive data."

### C. Proof of Fulfillment Signal
- After pay: order ID `#PM-2026-xxxxx`, amount, method, `Paid` badge, `Download` + `View Receipt` (profile also stores history)
- Profile → Orders: table/cards with date, items, amount, status `Paid/Pending/Failed`, actions `Pay Now / View Receipt / Reorder`
- Email hint: "We've sent your confirmation to juan@email.com"

### D. Human / Social Signal
- 3 testimonials with PH context (Mark/Cebu/Manila) — keep on landing, add carousel later
- "Curated Catalog" tag + `In Stock` pill + product count (`View Full Catalog (24 items)`) → marketplace is stocked, not empty
- Empty states: friendly + CTA (`No products found — Browse latest`) not blank grid

**Agents must:** Add one trust signal for every new buyer-facing feature. Ask before shipping: "If I were a first-time buyer, would this page make me feel safe to pay ₱499?"

---

## 5. Engagement Strategy — Making a New Marketplace Feel Alive

Problem: New store looks empty. Solution: Design for activity, not just inventory.

**1. Discovery first, account second**
- Guest can browse → cart → checkout without forced register
- Hero CTA `Browse Products` is primary (white), `Create Free Account` secondary (glass) — never block browsing
- Cart + checkout show soft nudge: "Have account? Sign in to track orders" — not a wall

**2. Keep catalog browsing frictionless**
- Category pills (`All`, `Templates`, `Kits`, etc.) with counts, sticky on mobile
- Product card: visual banner + category tag + instant stock pill + 2 actions (`Add to Cart` primary, `Details` secondary)
- Hover feedback, but touch-optimized: `min-height 42-48px`, `active:scale(0.97)` on all buttons

**3. Reduce doubt at decision moment**
- Price card: large `₱499` + badge `PHP` + hint `One-time purchase • Instant access`
- Perks row under product: `⚡ Instant Download` `🛡️ Secure Checkout` `📄 Receipt Included` as pills
- Guarantee strip: "30-day support • Verified seller • Instant delivery" on cart & checkout

**4. Post-purchase loop**
- Success page is celebration + utility: `✓ Payment Confirmed`, order summary, email note, `View Order` + `Browse More` — not dead end
- Profile dashboard surfaces next step: `Continue shopping`, `Reorder`, `Download again`

**5. Never show backend states to buyers**
- Translate internally `pending/failed/processing` → buyer language:
  - `Pending` → "Waiting for payment — Scan QR to complete"
  - `Failed` → "Payment didn't go through — Try another method, your cart is saved"
  - `Processing` → "Confirming your payment… please don't close"
- No error codes. Only human help: "Check your CVC", "Try another card", "Need help? Contact support"

---

## 6. UX Rules for Agents — Do / Don't

| Do | Don't |
|----|-------|
| Write "Pay ₱499 with QR Ph — Scan with GCash/Maya" | Write "Create Payment Intent" |
| Show `GCash`, `Maya`, `BPI` pills | Show `PayMongo`, `API`, `webhook` |
| Mobile-first, single-page checkout with sticky pay bar | Multi-step wizard with 5 "Continue" clicks |
| Inline validation with `✓` / `❌ Check your email` | Alert box after full form submit |
| Keep cart + coupon + address on retry | Send buyer back to empty cart on failure |
| Button `disabled + Processing…` + spinner on double-click | Allow double `PAY NOW` submits |
| Success page with order # + receipt + download | Just "Payment successful!" |
| Empty state with icon + CTA | Blank grid or "0 products" |

**Copy tone:** Warm, short, PH-friendly. Second person ("Your download is ready"), not technical ("Order fulfilled"). Use `₱` with comma: `₱2,499.00`.

**Accessibility & mobile:** All CTAs `min-height 36-48px`, `touch-action:manipulation`, visible focus, no horizontal overflow. Logo already responsive (48px desktop → 28px small phone) — keep it.

---

## 7. Page-by-Page Checklist for Implementation

**Header (`base.html`):** Logo responsive, `Home` `Products` `Cart` `Sign In` `Register` — no overflow on 320px. Cart badge always visible.
**Footer:** Tagline "Instant digital products with frictionless PH payments. Powered by PayMongo, QR Ph, GCash, Maya…" + columns `Explore / Account / Trust & Legal` + copyright.
**Landing (`catalog/landing.html`):** Hero (title + subtitle + 2 CTAs + 3 metrics), Featured (6 cards), Why Raqnith (4 features), How It Works (3 steps), Trust Banner (4 chips + privacy/terms links), Testimonials (3), CTA Banner.
**Catalog (`catalog/product_list.html`):** Title + count pill, category nav, perks bar, grid (1 col mobile → 2 tablet → 3/4 desktop), card banner + price + `Add to Cart`/`Details`.
**Product Detail (`catalog/product_detail.html`):** Breadcrumb, visual banner + perks card, panel with title/category/price card + features row + `Add to Cart` + payment strip + back link.
**Cart (`cart/detail.html`):** Header with count, grid items + guarantee box, sticky summary with total + `Checkout` primary + `Continue shopping` + payment badges. Empty state with browse CTA.
**Checkout (`checkout/index.html`):** Stepper, mobile accordion + desktop sidebar, contact + billing forms with email domain pills/typo guard, promo box, QR badge preview, terms checkbox, desktop button + mobile sticky pay bar. Trust footer `🔒 256-bit SSL • PayMongo • Instant confirm`.
**QR/Confirming/Return/Retry/Payment (`checkout/payment.html`, `payments/*`):** Status bar with pulsing dot + timer, QR frame with corners, save/copy amount actions, amount banner, guide tabs (QR vs manual), wallet chips, expired/success overlays.
**Orders (`orders/success.html`, `receipt.html`, `detail.html`):** Celebration card, order meta, download/receipt actions, trust strip.
**Accounts (`accounts/login.html`, `register.html`, `profile.html`, `settings.html`):** Logo badge, social-proof subtitle ("Join 1,000+ buyers"), error alerts, 2-col form rows, terms notice, security notice.
**Seller Apply (`seller/apply.html`):** Public page, no login wall. Third-party creators apply here; the store reviews in admin and curates listings (no self-serve product creation). Phased form: About You → Your Brand → What You Sell with progress bar, inline per-phase validation, Back/Continue buttons and Submit only on the last phase. Warm human copy, no em dashes. Success panel with review timeline + Browse CTA. Footer `Explore` links here as "Apply as Seller".

**New work:** Reuse existing CSS components in `static/css/site.css` (e.g., `.product-card-modern`, `.checkout-section-card`, `.security-chip`, `.pay-chip`). Do not invent new payment terminology.

---

## 8. Validation Before Ship

Before any PR, verify buyer sees:

- [ ] Can a first-time visitor state what Raqnith sells + how they pay in <7s?
- [ ] Are the 3 pillars visible above the fold and at checkout?
- [ ] Does every pay button show the exact total (`Pay ₱499`)?
- [ ] Is there a visible trust signal within 200px of the pay button?
- [ ] Does mobile (320/375/768) have no overflow, logo ≤40px, buttons ≥32px?
- [ ] Does success/receipt prove delivery (ID + download + email)?
- [ ] Is guest checkout possible?

If any fail, treat as blocking.

---

## Appendix — Where Backend Docs Live Now

The PayMongo integration blueprint (Payment Intents, 3DS, webhooks, reconciliation, testing) has been moved out of this file to `docs/payments.md` (create if needed). UI agents should not need it to ship marketplace features. Backend agents may reference it, but **never surface its language in templates**.

