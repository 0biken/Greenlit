from django import forms


class SignupForm(forms.Form):
    """Extra fields on sign-up, added to allauth's own (ACCOUNT_SIGNUP_FORM_CLASS)."""

    name = forms.CharField(max_length=200, required=False)

    def signup(self, request, user) -> None:
        user.name = self.cleaned_data.get("name", "").strip()
        user.save(update_fields=["name", "updated_at"])
