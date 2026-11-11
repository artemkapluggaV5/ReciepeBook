from django import forms
class CheckoutForm(forms.Form):
    consent = forms.BooleanField(label='Я принимаю условия оферты')
    request_key = forms.UUIDField(widget=forms.HiddenInput)
    website = forms.CharField(required=False, widget=forms.HiddenInput)
    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise forms.ValidationError('Не удалось обработать форму.')
        return ''
