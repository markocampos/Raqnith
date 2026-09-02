// Virtus UI & Mobile Interaction Controller
(function () {
    "use strict";

    function initUserDropdown() {
        var menu = document.getElementById("user-menu-dropdown");
        var toggleBtn = document.getElementById("user-menu-toggle");
        var panel = document.getElementById("user-dropdown-panel");

        if (!menu || !toggleBtn || !panel) return;

        function closeMenu() {
            menu.classList.remove("is-open");
            toggleBtn.setAttribute("aria-expanded", "false");
        }

        function openMenu() {
            menu.classList.add("is-open");
            toggleBtn.setAttribute("aria-expanded", "true");
        }

        function toggleMenu(e) {
            e.stopPropagation();
            var isOpen = menu.classList.contains("is-open");
            if (isOpen) {
                closeMenu();
            } else {
                openMenu();
            }
        }

        toggleBtn.addEventListener("click", toggleMenu);

        // Close when clicking/tapping outside
        document.addEventListener("click", function (e) {
            if (!menu.contains(e.target)) {
                closeMenu();
            }
        });

        // Close on Escape key
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape" || e.keyCode === 27) {
                if (menu.classList.contains("is-open")) {
                    closeMenu();
                    toggleBtn.focus();
                }
            }
        });

        // Close when focus moves outside the menu
        document.addEventListener("focusin", function (e) {
            if (menu.classList.contains("is-open") && !menu.contains(e.target)) {
                closeMenu();
            }
        });
    }

    function initCartAnimations() {
        var cartBadge = document.getElementById("header-cart-badge");
        var cartBtn = document.getElementById("header-cart-button");

        if (!cartBadge || !cartBtn) return;

        // Provide tactile press feedback for mobile devices
        cartBtn.addEventListener("touchstart", function () {
            cartBtn.classList.add("is-pressed");
        }, { passive: true });

        cartBtn.addEventListener("touchend", function () {
            cartBtn.classList.remove("is-pressed");
        }, { passive: true });

        cartBtn.addEventListener("touchcancel", function () {
            cartBtn.classList.remove("is-pressed");
        }, { passive: true });

        // If items are present, trigger a smooth spring badge pop on initial load
        var count = parseInt(cartBadge.textContent.trim(), 10);
        if (!isNaN(count) && count > 0) {
            cartBadge.classList.remove("animate-badge-pop");
            // void offsetWidth to force re-flow
            void cartBadge.offsetWidth;
            cartBadge.classList.add("animate-badge-pop");
        }
    }

    // ==========================================
    // TOAST NOTIFICATION SYSTEM
    // ==========================================
    var SVG_ICONS = {
        success: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="toast-icon-svg"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>',
        error: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="toast-icon-svg"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>',
        danger: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="toast-icon-svg"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>',
        warning: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="toast-icon-svg"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg>',
        info: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="toast-icon-svg"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="16" y2="12"/><line x1="12" x2="12.01" y1="8" y2="8"/></svg>',
        close: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" x2="6" y1="6" y2="18"/><line x1="6" x2="18" y1="6" y2="18"/></svg>'
    };

    function getToastContainer() {
        var container = document.getElementById("toast-container");
        if (!container) {
            container = document.createElement("div");
            container.id = "toast-container";
            container.className = "toast-container";
            container.setAttribute("aria-live", "polite");
            container.setAttribute("aria-atomic", "true");
            document.body.appendChild(container);
        }
        return container;
    }

    function initToastElement(toastEl, duration) {
        if (!toastEl || toastEl._toastInitialized) return;
        toastEl._toastInitialized = true;

        var delay = duration;
        if (typeof delay === "undefined") {
            delay = parseInt(toastEl.getAttribute("data-delay") || "5000", 10);
        }

        var isDismissed = false;
        var timer = null;
        var startTime = 0;
        var remainingTime = delay;
        var progressBar = toastEl.querySelector(".toast-progress-bar");
        var closeBtn = toastEl.querySelector(".toast-close");

        function dismiss() {
            if (isDismissed) return;
            isDismissed = true;
            if (timer) clearTimeout(timer);
            toastEl.classList.add("is-dismissing");
            setTimeout(function () {
                if (toastEl.parentNode) {
                    toastEl.parentNode.removeChild(toastEl);
                }
            }, 300);
        }

        if (closeBtn) {
            closeBtn.addEventListener("click", function (e) {
                e.stopPropagation();
                dismiss();
            });
        }

        if (delay > 0) {
            toastEl.classList.add("is-timed");
            if (progressBar) {
                progressBar.style.animationDuration = delay + "ms";
            }

            function startTimer() {
                startTime = Date.now();
                timer = setTimeout(dismiss, remainingTime);
            }

            function pauseTimer() {
                if (timer) {
                    clearTimeout(timer);
                    timer = null;
                    var elapsed = Date.now() - startTime;
                    remainingTime = Math.max(0, remainingTime - elapsed);
                }
            }

            startTimer();

            toastEl.addEventListener("mouseenter", pauseTimer);
            toastEl.addEventListener("mouseleave", function () {
                if (remainingTime > 0) {
                    startTimer();
                } else {
                    dismiss();
                }
            });

            toastEl.addEventListener("touchstart", pauseTimer, { passive: true });
            toastEl.addEventListener("touchend", function () {
                if (remainingTime > 0) {
                    startTimer();
                } else {
                    dismiss();
                }
            }, { passive: true });
        }
    }

    function initExistingToasts() {
        var toasts = document.querySelectorAll(".toast-item");
        for (var i = 0; i < toasts.length; i++) {
            initToastElement(toasts[i]);
        }
    }

    /**
     * Public showToast API
     * @param {string} message - Text message or safe HTML
     * @param {string} [type='info'] - 'success', 'error', 'danger', 'warning', 'info'
     * @param {number} [duration=5000] - Auto-dismiss timeout in ms (0 for sticky)
     */
    function showToast(message, type, duration) {
        if (!message) return null;
        var safeType = (type || "info").toLowerCase();
        if (safeType === "danger") safeType = "error";
        if (!SVG_ICONS[safeType]) safeType = "info";

        var timeout = (typeof duration === "number") ? duration : 5000;
        var container = getToastContainer();

        var toast = document.createElement("div");
        toast.className = "toast-item toast-" + safeType;
        toast.setAttribute("role", safeType === "error" ? "alert" : "status");
        toast.setAttribute("data-delay", String(timeout));

        var iconSvg = SVG_ICONS[safeType] || SVG_ICONS.info;
        var closeSvg = SVG_ICONS.close;

        toast.innerHTML = [
            '<div class="toast-icon">' + iconSvg + '</div>',
            '<div class="toast-body"><span class="toast-message">' + message + '</span></div>',
            '<button type="button" class="toast-close" aria-label="Close notification" title="Close">' + closeSvg + '</button>',
            '<div class="toast-progress-track"><div class="toast-progress-bar"></div></div>'
        ].join("");

        container.appendChild(toast);
        initToastElement(toast, timeout);
        return toast;
    }

    function initGlobalCopyButtons() {
        document.addEventListener("click", function (e) {
            var btn = e.target.closest(".btn-copy-mini, .btn-copy-id, [data-copy]");
            if (!btn || btn.id === "btn-copy-amount" || btn.id === "btn-copy-order") return;
            var text = btn.getAttribute("data-copy");
            if (!text) return;
            e.preventDefault();
            e.stopPropagation();

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

            var oldHtml = btn.innerHTML;
            btn.innerHTML = '<span style="font-size: 10px; font-weight: bold; color: #166534;">✓</span>';
            setTimeout(function () {
                btn.innerHTML = oldHtml;
            }, 1500);

            if (window.showToast) {
                window.showToast("Copied to clipboard: " + text.slice(0, 16) + (text.length > 16 ? "…" : ""), "success", 2000);
            }
        });
    }

    function initAddToCartLoading() {
        document.addEventListener("submit", function (e) {
            var form = e.target;
            if (!form.classList.contains("form-add-to-cart") && !form.classList.contains("product-main-add-form")) return;
            var btn = form.querySelector('button[type="submit"]');
            if (!btn || btn.disabled) return;
            btn.disabled = true;
            btn.setAttribute("aria-busy", "true");
            var original = btn.innerHTML;
            btn.dataset.originalHtml = original;
            btn.innerHTML = '<span class="btn-spinner" aria-hidden="true" style="width:14px;height:14px;border:2px solid rgba(255,255,255,0.4);border-top-color:#fff;border-radius:50%;display:inline-block;animation:spin 0.6s linear infinite;vertical-align:middle;"></span> <span>Adding…</span>';
            // re-enable after 4s fallback if navigation fails
            setTimeout(function(){ if(btn){ btn.disabled=false; btn.removeAttribute("aria-busy"); if(btn.dataset.originalHtml) btn.innerHTML=btn.dataset.originalHtml; }}, 4000);
        });
    }

    function initPromoInlineError() {
        // Promo UI renders twice (desktop sidebar + mobile summary accordion),
        // so bind every .promo-form instance instead of a single id.
        var promoForms = document.querySelectorAll(".promo-form");
        if (!promoForms.length) return;

        var promoToastText = "";
        var toastMsgs = document.querySelectorAll(".toast-message");
        for(var i=0;i<toastMsgs.length;i++){
            var t = toastMsgs[i].textContent || "";
            if(t.toLowerCase().indexOf("promo") !== -1){
                promoToastText = t;
                break;
            }
        }

        Array.prototype.forEach.call(promoForms, function(promoForm){
            var promoInput = promoForm.querySelector(".promo-input");
            var promoError = promoForm.querySelector(".promo-inline-error");
            if (!promoInput || !promoError) return;

            promoForm.addEventListener("submit", function(e){
                if(!promoInput.value.trim()){
                    e.preventDefault();
                    promoError.textContent = "Please enter a promo code.";
                    promoError.hidden = false;
                    promoInput.classList.add("invalid");
                    promoInput.focus();
                    if(window.showToast) window.showToast("Please enter a promo code.", "warning", 3000);
                    return;
                }
                promoError.hidden = true;
                promoInput.classList.remove("invalid");
                var btn = promoForm.querySelector(".btn-apply-promo");
                if(btn){ btn.disabled=true; btn.textContent="Applying…"; }
            });
            promoInput.addEventListener("input", function(){ promoError.hidden=true; promoInput.classList.remove("invalid"); });

            if(promoToastText){
                promoError.textContent = promoToastText;
                promoError.hidden = false;
                promoInput.classList.add("invalid");
            }
        });
    }

    // Expose global Toast helper
    window.showToast = showToast;
    window.Virtus = window.Virtus || {};
    window.Virtus.showToast = showToast;

    function initScrollIndicator() {
        var indicator = document.querySelector(".hero-scroll-indicator");
        if (!indicator) return;
        var featured = document.getElementById("featured-products");
        if (!featured) return;
        indicator.addEventListener("click", function () {
            featured.scrollIntoView({ behavior: "smooth" });
        });
    }

    function initSectionVideoClip() {
        var video = document.querySelector(".hiw-bg-video");
        if (!video) return;

        var startTime = 1;
        var endTime = 15;

        function checkTime() {
            if (video.currentTime >= endTime || video.currentTime < startTime) {
                video.currentTime = startTime;
                video.play().catch(function () {});
            }
        }

        video.addEventListener("loadedmetadata", function () {
            video.currentTime = startTime;
        });

        video.addEventListener("timeupdate", checkTime);

        if (video.readyState >= 1) {
            video.currentTime = startTime;
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            initUserDropdown();
            initCartAnimations();
            initExistingToasts();
            initGlobalCopyButtons();
            initAddToCartLoading();
            initPromoInlineError();
            initScrollIndicator();
            initSectionVideoClip();
        });
    } else {
        initUserDropdown();
        initCartAnimations();
        initExistingToasts();
        initGlobalCopyButtons();
        initAddToCartLoading();
        initPromoInlineError();
        initScrollIndicator();
        initSectionVideoClip();
    }
})();
