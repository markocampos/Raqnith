from django import forms
from django.contrib.auth import authenticate, get_user_model, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

User = get_user_model()


class UserRegistrationForm(forms.ModelForm):
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "First name", "autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Last name", "autocomplete": "family-name"}),
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "autocomplete": "email"}),
    )
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(
            attrs={"placeholder": "Choose a username", "autocomplete": "username"}
        ),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"placeholder": "Create a strong password", "autocomplete": "new-password"}
        ),
        required=True,
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"placeholder": "Confirm your password", "autocomplete": "new-password"}
        ),
        required=True,
        label="Confirm Password",
    )

    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name")

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not username:
            raise ValidationError("Username is required.")
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("A user with that username already exists.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if not email:
            raise ValidationError("Email is required.")
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        if password and password_confirm:
            if password != password_confirm:
                self.add_error("password_confirm", "Passwords do not match.")
            else:
                user = User(
                    username=cleaned_data.get("username", ""),
                    email=cleaned_data.get("email", ""),
                )
                try:
                    validate_password(password, user)
                except ValidationError as error:
                    self.add_error("password", error)

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class UserLoginForm(forms.Form):
    username_or_email = forms.CharField(
        required=True,
        label="Username or Email",
        widget=forms.TextInput(
            attrs={"placeholder": "Enter your username or email", "autocomplete": "username"}
        ),
    )
    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(
            attrs={"placeholder": "Enter your password", "autocomplete": "current-password"}
        ),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        username_or_email = cleaned_data.get("username_or_email", "").strip()
        password = cleaned_data.get("password", "")

        if username_or_email and password:
            user_obj = (
                User.objects.filter(email__iexact=username_or_email).first()
                or User.objects.filter(username__iexact=username_or_email).first()
            )

            if user_obj:
                authenticated_user = authenticate(
                    self.request,
                    username=user_obj.username,
                    password=password,
                )
            else:
                authenticated_user = None

            if authenticated_user is None:
                raise ValidationError("Invalid username/email or password.")
            elif not authenticated_user.is_active:
                raise ValidationError("This account is currently disabled.")

            self.user_cache = authenticated_user

        return cleaned_data

    def get_user(self):
        return self.user_cache


class UserProfileForm(forms.ModelForm):
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "First name"}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Last name"}),
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com"}),
    )

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if not email:
            raise ValidationError("Email is required.")
        exists = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists()
        if exists:
            raise ValidationError("This email is already in use by another account.")
        return email


class ChangePasswordForm(forms.Form):
    current_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={"placeholder": "Current password"}),
    )
    new_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={"placeholder": "New password"}),
    )
    confirm_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={"placeholder": "Confirm new password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        current_password = self.cleaned_data.get("current_password")
        if not self.user.check_password(current_password):
            raise ValidationError("Incorrect current password.")
        return current_password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")

        if new_password and confirm_password:
            if new_password != confirm_password:
                self.add_error("confirm_password", "New passwords do not match.")
            else:
                try:
                    validate_password(new_password, self.user)
                except ValidationError as error:
                    self.add_error("new_password", error)

        return cleaned_data

    def save(self, request=None):
        new_password = self.cleaned_data["new_password"]
        self.user.set_password(new_password)
        self.user.save()
        if request:
            update_session_auth_hash(request, self.user)
        return self.user
