from django import forms

from apps.catalog.models import Product


class AddToCartForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.all())

    def clean_product(self):
        product = self.cleaned_data["product"]
        if not product.is_available:
            raise forms.ValidationError("This product is not available.")
        return product
