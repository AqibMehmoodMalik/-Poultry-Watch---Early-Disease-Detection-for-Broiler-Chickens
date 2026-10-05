from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("image/", views.upload_image, name="upload_image"),
    path("video/", views.upload_video, name="upload_video"),
    path("live/", views.live_stream_page, name="live_stream_page"),
    path("live/feed/", views.video_feed, name="video_feed"),
]