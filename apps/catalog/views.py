from django.views.generic import DetailView, ListView, TemplateView

from apps.catalog.models import Category, Product


class LandingPageView(TemplateView):
    template_name = "catalog/landing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        available_qs = Product.objects.filter(is_available=True)
        context["featured_products"] = available_qs.order_by("name")[:6]
        context["categories"] = Category.objects.all()
        context["total_products_count"] = available_qs.count()
        return context


class ProductListView(ListView):
    model = Product
    template_name = "catalog/product_list.html"
    context_object_name = "products"
    paginate_by = 12

    def get_queryset(self):
        qs = Product.objects.filter(is_available=True).select_related("category").order_by("name")
        category_slug = self.request.GET.get("category", "").strip()
        if category_slug and category_slug != "all":
            qs = qs.filter(category__slug=category_slug)

        self.search_query = self.request.GET.get("q", "").strip()
        if self.search_query:
            from django.db.models import Q

            qs = qs.filter(
                Q(name__icontains=self.search_query)
                | Q(description__icontains=self.search_query)
                | Q(category__name__icontains=self.search_query)
            )
        else:
            self.search_query = ""
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = Category.objects.all().order_by("name")
        context["selected_category"] = self.request.GET.get("category", "all").strip()
        context["total_count"] = Product.objects.filter(is_available=True).count()
        context["search_query"] = getattr(self, "search_query", "")
        return context


class ProductDetailView(DetailView):
    model = Product
    template_name = "catalog/product_detail.html"
    context_object_name = "product"

    def get_queryset(self):
        return Product.objects.filter(is_available=True)
