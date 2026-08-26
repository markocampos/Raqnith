from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from apps.seller.forms import SellerApplicationForm


class SellerApplyView(View):
    """Apply as Seller, a public page where third-party creators apply.

    Applications land in the admin for review. Nothing is published to the
    storefront automatically; the store curates approved creators.
    """

    template_name = "seller/apply.html"

    def get(self, request):
        return self._render(request)

    def post(self, request):
        # Hidden honeypot. Bots fill it, humans never see it. Pretend success.
        if request.POST.get("website"):
            return redirect(f"{reverse('seller:apply')}?sent=1")

        form = SellerApplicationForm(request.POST)
        if not form.is_valid():
            return self._render(request, form=form, status=400)

        form.save()
        messages.success(
            request,
            "Application received! Our team will review it and email you within 2 to 3 business days.",
        )
        return redirect(f"{reverse('seller:apply')}?sent=1")

    def _render(self, request, form=None, status=200):
        sent = request.GET.get("sent") == "1"
        if sent:
            form = None
        return render(
            request,
            self.template_name,
            {"form": form or SellerApplicationForm(), "sent": sent},
            status=status,
        )
