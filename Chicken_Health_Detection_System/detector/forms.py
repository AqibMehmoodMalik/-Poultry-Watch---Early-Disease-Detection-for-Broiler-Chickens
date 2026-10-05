from django import forms


class ImageUploadForm(forms.Form):
    image = forms.ImageField(label="Choose an image")


class VideoUploadForm(forms.Form):
    video = forms.FileField(label="Choose a video file")