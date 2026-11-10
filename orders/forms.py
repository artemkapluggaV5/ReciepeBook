from django import forms
class CheckoutForm(forms.Form):
    email = forms.EmailField(max_length=254, label='Электронная почта', widget=forms.EmailInput(attrs={
        'placeholder': 'you@example.com', 'autocomplete': 'email', 'inputmode': 'email', 'aria-describedby': 'email-help'}))
    consent = forms.BooleanField(label='Я принимаю условия оферты')
    request_key = forms.UUIDField(widget=forms.HiddenInput)
    website = forms.CharField(required=False, widget=forms.HiddenInput)
    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        local, domain = email.rsplit('@', 1)
        return f'{local}@{domain.lower()}'
    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise forms.ValidationError('Не удалось обработать форму.')
        return ''
