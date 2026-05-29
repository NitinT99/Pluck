from flask import Flask, render_template, request, jsonify
import os
import re
import subprocess

app = Flask(__name__)

DEFAULT_OUTPUT_FOLDER = os.path.join(os.path.expanduser("~"), "Downloads")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/default-folder", methods=["GET"])
def get_default_folder():
    return jsonify({"folder": DEFAULT_OUTPUT_FOLDER})

@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    data = request.json
    folder = data.get("folder", DEFAULT_OUTPUT_FOLDER)
    try:
        if os.path.exists(folder):
            subprocess.Popen(f'explorer "{folder}"')
            return jsonify({"success": True})
        else:
            return jsonify({
                "success": False,
                "error": f"Folder not found: {folder}"
            })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/video-info", methods=["POST"])
def get_video_info():
    """Fetch video info before downloading — title, duration, uploader."""
    data = request.json
    url  = data.get("url", "").strip()

    if not url:
        return jsonify({"success": False, "error": "Please enter a URL"})

    if not any(domain in url for domain in [
        "youtube.com", "youtu.be", "music.youtube.com"
    ]):
        return jsonify({
            "success": False,
            "error": "Please enter a valid YouTube or YouTube Music URL"
        })

    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            duration = info.get("duration", 0)
            mins = duration // 60
            secs = duration % 60
            return jsonify({
                "success": True,
                "title":    info.get("title", "Unknown"),
                "uploader": info.get("uploader", "Unknown"),
                "duration": f"{mins}:{secs:02d}",
                "thumbnail": info.get("thumbnail", "")
            })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

def get_unique_filepath(output_folder, base_filename, extension=".mp3"):
    """Return unique filepath by adding counter if file exists."""
    filepath = os.path.join(output_folder, base_filename + extension)
    if not os.path.exists(filepath):
        return filepath, base_filename + extension
    counter = 1
    while True:
        new_filename = f"{base_filename} ({counter}){extension}"
        new_filepath = os.path.join(output_folder, new_filename)
        if not os.path.exists(new_filepath):
            return new_filepath, new_filename
        counter += 1

@app.route("/api/download-media", methods=["POST"])
def download_media():
    data          = request.json
    url           = data.get("url", "").strip()
    media_type    = data.get("media_type", "audio")
    quality       = data.get("quality", "best")
    output_folder = data.get("output_folder", DEFAULT_OUTPUT_FOLDER).strip()

    if not url:
        return jsonify({
            "success": False,
            "error": "Please enter a YouTube or YouTube Music URL"
        })

    if not any(domain in url for domain in [
        "youtube.com", "youtu.be", "music.youtube.com"
    ]):
        return jsonify({
            "success": False,
            "error": "Please enter a valid YouTube or YouTube Music URL"
        })

    os.makedirs(output_folder, exist_ok=True)

    try:
        import yt_dlp

        # Get video info first
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info     = ydl.extract_info(url, download=False)
            title    = info.get("title", "Unknown")
            duration = info.get("duration", 0)
            uploader = info.get("uploader", "Unknown")

        mins = duration // 60
        secs = duration % 60
        duration_str = f"{mins}:{secs:02d}"

        # Build unique output path
        ext = "mp3" if media_type == "audio" else "mp4"
        safe_title = re.sub(r'[<>:"/\\|?*]', '', title)
        _, unique_filename = get_unique_filepath(
            output_folder, safe_title, f".{ext}"
        )
        unique_filepath = os.path.join(output_folder, unique_filename)
        base_name = os.path.splitext(unique_filepath)[0]

        # Build yt-dlp options
        if media_type == "audio":
            quality_map = {
                "best": "bestaudio/best",
                "320":  "bestaudio[abr<=320]/bestaudio/best",
                "192":  "bestaudio[abr<=192]/bestaudio/best",
                "128":  "bestaudio[abr<=128]/bestaudio/best",
            }
            ydl_opts = {
                "format": quality_map.get(quality, "bestaudio/best"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": quality if quality != "best" else "320",
                }],
                "outtmpl": base_name + ".%(ext)s",
                "quiet": True,
                "no_warnings": True,
            }
        else:
            quality_map = {
                "best": "bestvideo+bestaudio/best",
                "2k":   "bestvideo[height<=1440]+bestaudio/best",
                "1080": "bestvideo[height<=1080]+bestaudio/best",
                "720":  "bestvideo[height<=720]+bestaudio/best",
                "480":  "bestvideo[height<=480]+bestaudio/best",
            }
            ydl_opts = {
                "format": quality_map.get(quality, "bestvideo+bestaudio/best"),
                "postprocessors": [{
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }],
                "outtmpl": base_name + ".%(ext)s",
                "quiet": True,
                "no_warnings": True,
                "merge_output_format": "mp4",
            }

        # Track file info
        file_info = {}
        def progress_hook(d):
            if d["status"] == "finished":
                file_info["filepath"] = d.get("filename", "")
                file_info["filesize"] = d.get("total_bytes") or \
                    d.get("total_bytes_estimate", 0)

        ydl_opts["progress_hooks"] = [progress_hook]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Find actual downloaded file
        filepath = file_info.get("filepath", "")
        if filepath and not os.path.exists(filepath):
            base = os.path.splitext(filepath)[0]
            for check_ext in [".mp3", ".mp4", ".m4a", ".webm"]:
                if os.path.exists(base + check_ext):
                    filepath = base + check_ext
                    break

        # Also check our unique path directly
        if not filepath or not os.path.exists(filepath):
            for check_ext in [".mp3", ".mp4", ".m4a", ".webm"]:
                if os.path.exists(base_name + check_ext):
                    filepath = base_name + check_ext
                    break

        filename = os.path.basename(filepath) if filepath else unique_filename

        # Format filesize
        filesize = os.path.getsize(filepath) if filepath and \
            os.path.exists(filepath) else 0
        if filesize > 1024 * 1024 * 1024:
            filesize_str = f"{filesize / (1024**3):.1f} GB"
        elif filesize > 1024 * 1024:
            filesize_str = f"{filesize / (1024**2):.1f} MB"
        else:
            filesize_str = f"{filesize / 1024:.1f} KB"

        return jsonify({
            "success":    True,
            "message":    f"{'Audio' if media_type == 'audio' else 'Video'} downloaded successfully!",
            "filename":   filename,
            "filepath":   filepath,
            "folder":     output_folder,
            "title":      title,
            "uploader":   uploader,
            "duration":   duration_str,
            "filesize":   filesize_str,
            "media_type": media_type
        })

    except Exception as e:
        error_msg = str(e)
        if "Private video" in error_msg:
            return jsonify({
                "success": False,
                "error": "This video is private and cannot be downloaded."
            })
        if "Sign in" in error_msg:
            return jsonify({
                "success": False,
                "error": "This video requires sign-in and cannot be downloaded."
            })
        if "unavailable" in error_msg.lower():
            return jsonify({
                "success": False,
                "error": "This video is unavailable or has been removed."
            })
        return jsonify({
            "success": False,
            "error": f"Download failed: {error_msg}"
        })

if __name__ == "__main__":
    app.run(debug=True, port=5001)