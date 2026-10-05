from django.shortcuts import render

# Create your views here.
import os
import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.http import StreamingHttpResponse
from django.shortcuts import render

from . import model_loader
from .forms import ImageUploadForm, VideoUploadForm


def home(request):
    return render(request, "detector/home.html")


def upload_image(request):
    result = None

    if request.method == "POST":
        form = ImageUploadForm(request.POST, request.FILES)
        if form.is_valid():
            image_file = request.FILES["image"]

            uploads_dir = os.path.join(settings.MEDIA_ROOT, "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            fs = FileSystemStorage(location=uploads_dir)
            filename = fs.save(image_file.name, image_file)
            input_path = fs.path(filename)

            output_name = f"result_{uuid.uuid4().hex[:8]}_{filename}"
            results_dir = os.path.join(settings.MEDIA_ROOT, "results")
            os.makedirs(results_dir, exist_ok=True)
            output_path = os.path.join(results_dir, output_name)

            summary = model_loader.detect_image(input_path, output_path)

            result = {
                "input_url": settings.MEDIA_URL + "uploads/" + filename,
                "output_url": settings.MEDIA_URL + "results/" + output_name,
                "summary": summary,
            }
    else:
        form = ImageUploadForm()

    return render(request, "detector/image_upload.html", {"form": form, "result": result})


def upload_video(request):
    result = None

    if request.method == "POST":
        form = VideoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            video_file = request.FILES["video"]

            uploads_dir = os.path.join(settings.MEDIA_ROOT, "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            fs = FileSystemStorage(location=uploads_dir)
            filename = fs.save(video_file.name, video_file)
            input_path = fs.path(filename)

            output_name = f"result_{uuid.uuid4().hex[:8]}.mp4"
            results_dir = os.path.join(settings.MEDIA_ROOT, "results")
            os.makedirs(results_dir, exist_ok=True)
            output_path = os.path.join(results_dir, output_name)

            # NOTE: this runs synchronously — the request will wait until
            # the whole video is processed. Fine for short clips / a demo.
            # For long CCTV footage in production, move this into a
            # background task queue (e.g. Celery) and show a "processing..."
            # status page instead.
            summary = model_loader.process_video(input_path, output_path)

            result = {
                "output_url": settings.MEDIA_URL + "results/" + output_name,
                "summary": summary,
            }
    else:
        form = VideoUploadForm()

    return render(request, "detector/video_upload.html", {"form": form, "result": result})


def live_stream_page(request):
    source = request.GET.get("source", "0")
    return render(request, "detector/live_stream.html", {"source": source})


def video_feed(request):
    source = request.GET.get("source", "0")
    return StreamingHttpResponse(
        model_loader.generate_live_frames(source),
        content_type="multipart/x-mixed-replace; boundary=frame",
    )