// Raqnith Checkout & QR Ph Payment Controller
(function () {
    "use strict";

    // Common Helpers
    function readJsonElement(id, fallback) {
        var el = document.getElementById(id);
        if (!el) return fallback;
        try {
            return JSON.parse(el.textContent);
        } catch (e) {
            return fallback;
        }
    }

    var errorMap = readJsonElement("paymongo-error-map", {});
    var defaultErrorMessage =
        readJsonElement("paymongo-error-map-default", null) ||
        "We couldn't complete your payment. Please try again.";

    function translateError(code) {
        if (!code) return defaultErrorMessage;
        return errorMap[code] || defaultErrorMessage;
    }

    function csrfToken() {
        var input = document.querySelector("input[name=\"csrfmiddlewaretoken\"]");
        return input ? input.value : "";
    }

    function apiHeaders() {
        var headers = { "Content-Type": "application/json" };
        var token = csrfToken();
        if (token) {
            headers["X-CSRFToken"] = token;
        }
        return headers;
    }

    function postJson(url, body) {
        return fetch(url, {
            method: "POST",
            headers: apiHeaders(),
            credentials: "same-origin",
            body: JSON.stringify(body),
        }).then(function (resp) {
            return resp.json().catch(function () {
                return null;
            }).then(function (payload) {
                if (!resp.ok) {
                    throw { httpStatus: resp.status, payload: payload };
                }
                return payload;
            });
        });
    }

    // ==========================================
    // 0. MOBILE ORDER SUMMARY ACCORDION
    // ==========================================
    var summaryToggle = document.getElementById("mobile-summary-toggle");
    var summaryPanel = document.getElementById("mobile-summary-panel");

    if (summaryToggle && summaryPanel) {
        summaryToggle.addEventListener("click", function () {
            var isHidden = summaryPanel.hidden;
            summaryPanel.hidden = !isHidden;
            summaryToggle.setAttribute("aria-expanded", String(isHidden));
            summaryToggle.classList.toggle("is-open", isHidden);
            var titleEl = summaryToggle.querySelector(".summary-toggle-title");
            if (titleEl) {
                titleEl.textContent = isHidden ? "Hide order summary" : "Show order summary";
            }
        });
    }

    // ==========================================
    // 1. INITIAL CHECKOUT FORM (/checkout/)
    // ==========================================
    var initialForm = document.getElementById("checkout-form");
    var checkoutIndex = document.getElementById("checkout-index");

    if (initialForm && checkoutIndex) {
        var emailInput = document.getElementById("email");
        var termsInput = document.getElementById("terms");
        var payButton = document.getElementById("pay-button");
        var mobilePayButton = document.getElementById("mobile-pay-button");
        var paymentError = document.getElementById("payment-error");

        function checkEmail(val) {
            return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test((val || "").trim());
        }

        function validateInitialForm() {
            var emailVal = emailInput ? emailInput.value.trim() : "";
            var isEmailValid = checkEmail(emailVal);
            var isTermsValid = termsInput ? termsInput.checked : true;

            if (emailInput) {
                emailInput.classList.toggle("valid", isEmailValid);
                emailInput.classList.toggle("invalid", emailVal.length > 0 && !isEmailValid);
                var errorEl = initialForm.querySelector('[data-error-for="email"]');
                if (errorEl) {
                    errorEl.textContent = (emailVal.length > 0 && !isEmailValid) ? "Please enter a valid email address." : "";
                }
            }

            var termsErrorEl = initialForm.querySelector('[data-error-for="terms"]');
            if (termsErrorEl) {
                termsErrorEl.textContent = isTermsValid ? "" : "You must agree to the terms and conditions to proceed.";
            }

            var isValid = isEmailValid && isTermsValid;
            if (payButton) {
                payButton.disabled = !isValid;
            }
            if (mobilePayButton) {
                mobilePayButton.disabled = !isValid;
            }
            return isValid;
        }

        if (emailInput) {
            emailInput.addEventListener("input", function () {
                if (paymentError) paymentError.hidden = true;
                validateInitialForm();
            });
        }

        if (termsInput) {
            termsInput.addEventListener("change", function () {
                if (paymentError) paymentError.hidden = true;
                validateInitialForm();
            });
        }

        function handleSubmit(e) {
            if (e) e.preventDefault();
            if (!validateInitialForm()) return;

            if (payButton) {
                payButton.disabled = true;
                var btnTextEl = payButton.querySelector(".btn-text");
                if (btnTextEl) btnTextEl.textContent = "Processing securely…";
                else payButton.textContent = "Processing securely…";
            }
            if (mobilePayButton) {
                mobilePayButton.disabled = true;
                mobilePayButton.textContent = "Processing…";
            }

            postJson("/orders/", {
                contact: { email: emailInput ? emailInput.value.trim() : "" },
                terms: termsInput ? termsInput.checked : true
            })
            .then(function (payload) {
                if (payload && payload.require_login && payload.redirect_url) {
                    window.location.href = payload.redirect_url;
                    return;
                }
                if (payload && payload.order_id) {
                    window.location.href = "/checkout/" + payload.order_id + "/";
                    return;
                }
                throw { payload: { detail: "Could not process order." } };
            })
            .catch(function (err) {
                if (payButton) {
                    payButton.disabled = false;
                    var origText = payButton.querySelector(".btn-text");
                    if (origText) origText.textContent = "Proceed to Payment";
                    else payButton.textContent = "Proceed to Payment";
                }
                if (mobilePayButton) {
                    mobilePayButton.disabled = false;
                    mobilePayButton.textContent = "Proceed to Pay";
                }
                var detailMsg = (err && err.payload && (err.payload.detail || (err.payload.errors && (err.payload.errors.email || err.payload.errors.terms)))) || defaultErrorMessage;
                if (paymentError) {
                    paymentError.textContent = detailMsg;
                    paymentError.hidden = false;
                    paymentError.scrollIntoView({ behavior: "smooth", block: "center" });
                }
                if (window.showToast) {
                    window.showToast(detailMsg, "error", 5000);
                }
            });
        }

        initialForm.addEventListener("submit", handleSubmit);

        validateInitialForm();
    }

    // ==========================================
    // 2. DEDICATED QR PAYMENT SCREEN (/checkout/<id>/)
    // ==========================================
    var orderCheckout = document.getElementById("order-checkout");
    if (orderCheckout) {
        var orderId = orderCheckout.getAttribute("data-order-id");
        var paymentId = orderCheckout.getAttribute("data-payment-id");
        var secondsRemaining = parseInt(orderCheckout.getAttribute("data-seconds-remaining") || "900", 10);
        var isExpired = orderCheckout.getAttribute("data-is-expired") === "true";
        var isPaid = orderCheckout.getAttribute("data-is-paid") === "true";

        var qrImg = document.getElementById("qr-code-img");
        var expiredOverlay = document.getElementById("qr-expired-overlay");
        var successOverlay = document.getElementById("qr-success-overlay");
        var countdownTimerEl = document.getElementById("countdown-timer");
        var statusText = document.getElementById("status-text");
        var pulsingDot = document.getElementById("pulsing-dot");
        var refreshQrBtn = document.getElementById("refresh-qr-btn");
        var errorBox = document.getElementById("payment-error-box");
        var downloadQrBtn = document.getElementById("btn-download-qr");
        var copyAmountBtn = document.getElementById("btn-copy-amount");
        var copyOrderBtn = document.getElementById("btn-copy-order");

        var pollTimer = null;
        var countdownInterval = null;

        function copyToClipboard(text, buttonEl, successText) {
            if (!navigator.clipboard || !navigator.clipboard.writeText) {
                var tempInput = document.createElement("input");
                tempInput.value = text;
                document.body.appendChild(tempInput);
                tempInput.select();
                document.execCommand("copy");
                document.body.removeChild(tempInput);
            } else {
                navigator.clipboard.writeText(text).catch(function () {});
            }

            if (buttonEl) {
                var oldHtml = buttonEl.innerHTML;
                buttonEl.classList.add("copied-pop");
                buttonEl.innerHTML = "<span>✓ Copied!</span>";
                setTimeout(function () {
                    buttonEl.innerHTML = oldHtml;
                    buttonEl.classList.remove("copied-pop");
                }, 2000);
            }
            if (window.showToast) {
                window.showToast("Copied to clipboard!", "success", 2000);
            }
        }

        if (copyAmountBtn) {
            copyAmountBtn.addEventListener("click", function () {
                var amt = copyAmountBtn.getAttribute("data-copy") || "";
                var totalEl = document.getElementById("qr-total-amount");
                if (totalEl) amt = totalEl.textContent.trim();
                copyToClipboard(amt, copyAmountBtn);
            });
        }

        if (copyOrderBtn) {
            copyOrderBtn.addEventListener("click", function () {
                var oid = copyOrderBtn.getAttribute("data-copy") || orderId;
                copyToClipboard(oid, copyOrderBtn);
            });
        }

        function formatTimer(secs) {
            if (secs <= 0) return "00:00";
            var m = Math.floor(secs / 60);
            var s = secs % 60;
            return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
        }

        function setExpiredState() {
            if (pollTimer) clearInterval(pollTimer);
            if (countdownInterval) clearInterval(countdownInterval);
            if (qrImg) qrImg.classList.add("dimmed");
            if (successOverlay) successOverlay.hidden = true;
            if (expiredOverlay) expiredOverlay.hidden = false;
            if (countdownTimerEl) countdownTimerEl.textContent = "00:00";
            if (statusText) statusText.textContent = "QR Code Expired";
            if (pulsingDot) pulsingDot.classList.add("inactive");
        }

        function setSuccessState(showNotification) {
            if (pollTimer) clearInterval(pollTimer);
            if (countdownInterval) clearInterval(countdownInterval);
            if (expiredOverlay) expiredOverlay.hidden = true;
            if (successOverlay) successOverlay.hidden = false;

            // Hide action buttons and timer immediately upon confirmation
            var qrActionsRow = document.querySelector(".qr-actions-row");
            if (qrActionsRow) qrActionsRow.hidden = true;
            var timerBadge = document.getElementById("timer-badge");
            if (timerBadge) timerBadge.hidden = true;
            var instructions = document.querySelector(".payment-guide-card");
            if (instructions) instructions.hidden = true;
            var wallets = document.querySelector(".supported-wallets-footer");
            if (wallets) wallets.hidden = true;
            var amountBanner = document.querySelector(".qr-amount-banner");
            if (amountBanner) amountBanner.hidden = true;

            if (statusText) statusText.textContent = "Payment Confirmed!";
            if (pulsingDot) {
                pulsingDot.classList.remove("inactive");
                pulsingDot.classList.add("success");
            }
            if (qrImg) qrImg.classList.add("dimmed");
            var checkoutTitle = document.getElementById("checkout-title");
            if (checkoutTitle) checkoutTitle.textContent = "Payment Confirmed";
            var backLink = document.querySelector(".back-link");
            if (backLink) backLink.hidden = true;

            // Update Stepper
            var step2 = document.querySelector(".stepper-list .step-item:nth-child(3)");
            if (step2) {
                step2.classList.remove("step-active");
                step2.classList.add("step-completed");
                var badge = step2.querySelector(".step-badge");
                if (badge) badge.textContent = "✓";
            }
            var step3 = document.querySelector(".stepper-list .step-item:nth-child(5)");
            if (step3) step3.classList.add("step-active");

            if (showNotification && window.showToast) {
                window.showToast("Payment confirmed! Your digital order is ready.", "success", 6000);
            }
        }

        function startCountdown(duration) {
            if (countdownInterval) clearInterval(countdownInterval);
            var remaining = duration;
            if (countdownTimerEl) countdownTimerEl.textContent = formatTimer(remaining);

            countdownInterval = setInterval(function () {
                remaining -= 1;
                if (countdownTimerEl) countdownTimerEl.textContent = formatTimer(remaining);
                if (remaining <= 0) {
                    setExpiredState();
                }
            }, 1000);
        }

        function pollPaymentStatus() {
            if (!paymentId || isExpired) return;
            if (pollTimer) clearInterval(pollTimer);

            pollTimer = setInterval(function () {
                fetch("/payments/" + paymentId + "/status/", {
                    method: "GET",
                    credentials: "same-origin"
                })
                .then(function (resp) { return resp.json(); })
                .then(function (data) {
                    if (!data) return;
                    if (data.status === "succeeded") {
                        setSuccessState(true);
                    } else if (data.status === "failed" || data.is_expired) {
                        setExpiredState();
                    }
                })
                .catch(function () {
                    // transient network error; keep polling
                });
            }, 3000);
        }

        function requestNewQr() {
            if (errorBox) errorBox.hidden = true;
            if (statusText) statusText.textContent = "Generating fresh QR code…";

            postJson("/payments/" + paymentId + "/retry/", { payment_method: "qrph" })
                .then(function (data) {
                    paymentId = data.payment_id;
                    orderCheckout.setAttribute("data-payment-id", paymentId);
                    if (qrImg && data.qr_url) {
                        qrImg.src = data.qr_url;
                        qrImg.classList.remove("dimmed");
                    }
                    if (downloadQrBtn && data.qr_url) {
                        downloadQrBtn.href = data.qr_url;
                    }
                    if (expiredOverlay) expiredOverlay.hidden = true;
                    if (successOverlay) successOverlay.hidden = true;
                    if (statusText) statusText.textContent = "Waiting for payment…";
                    if (pulsingDot) pulsingDot.classList.remove("inactive", "success");
                    isExpired = false;

                    var secs = data.seconds_remaining || 900;
                    startCountdown(secs);
                    pollPaymentStatus();
                })
                .catch(function (err) {
                    var errorMsg = (err && err.payload && err.payload.detail) || "Could not refresh QR code. Please reload.";
                    if (errorBox) {
                        errorBox.textContent = errorMsg;
                        errorBox.hidden = false;
                    }
                    if (window.showToast) {
                        window.showToast(errorMsg, "error", 5000);
                    }
                });
        }

        if (refreshQrBtn) {
            refreshQrBtn.addEventListener("click", requestNewQr);
        }

        if (isPaid) {
            setSuccessState(false);
        } else if (isExpired || secondsRemaining <= 0) {
            setExpiredState();
        } else {
            if (expiredOverlay) expiredOverlay.hidden = true;
            if (successOverlay) successOverlay.hidden = true;
            if (qrImg) qrImg.classList.remove("dimmed");
            startCountdown(secondsRemaining);
            pollPaymentStatus();
        }
    }

})();


