from django import forms
class CheckoutForm(forms.Form):
    consent = forms.BooleanField(label='Я принимаю условия оферты')
    request_key = forms.UUIDField(widget=forms.HiddenInput)
    website = forms.CharField(required=False, widget=forms.HiddenInput)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from payments.receipts import receipts_enabled
        if receipts_enabled():
            self.fields['receipt_email'] = forms.EmailField(
                label='Электронная почта для чека', max_length=254,
                widget=forms.EmailInput(attrs={'autocomplete': 'email', 'inputmode': 'email',
                    'aria-describedby': 'receipt-email-help', 'placeholder': 'you@example.com'}))
    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise forms.ValidationError('Не удалось обработать форму.')
        return ''
