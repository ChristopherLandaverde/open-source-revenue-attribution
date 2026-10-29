from django import forms

from contracts import ENTITIES

MAX_FILE_BYTES = 10 * 1024 * 1024


class ImportForm(forms.Form):
    """The four import files. Any of them may be left out: the validator reports MISSING_FILE."""

    accounts = forms.FileField(required=False, label="accounts.csv")
    contacts = forms.FileField(required=False, label="contacts.csv")
    opportunities = forms.FileField(required=False, label="opportunities.csv")
    touchpoints = forms.FileField(required=False, label="touchpoints.csv")
    strict = forms.BooleanField(
        required=False,
        label="Strict: refuse the whole import if any row or file is refused",
    )

    def clean(self):
        cleaned = super().clean()
        if self.data.get("action") == "demo":
            return cleaned
        uploads = {e: cleaned.get(e) for e in ENTITIES if cleaned.get(e)}
        if not uploads:
            raise forms.ValidationError(
                "Choose at least one CSV file, or import the demo data set instead."
            )
        texts = {}
        for entity, upload in uploads.items():
            if upload.size > MAX_FILE_BYTES:
                self.add_error(entity, f"{upload.name} is larger than 10 MB.")
                continue
            try:
                texts[entity] = upload.read().decode("utf-8-sig")
            except UnicodeDecodeError:
                self.add_error(entity, f"{upload.name} is not UTF-8 text. Save it as UTF-8 CSV.")
        cleaned["texts"] = texts
        cleaned["names"] = [uploads[e].name for e in ENTITIES if e in uploads]
        return cleaned
