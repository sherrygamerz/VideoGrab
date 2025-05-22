from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import os
import re
import uuid
import json
import requests
from urllib.parse import urlparse, parse_qs
import tempfile
import shutil
from pytube import YouTube
from pytube.exceptions import RegexMatchError, VideoUnavailable

app = Flask(__name__)

# Create a temporary directory for downloads
TEMP_DIR = os.path.join(tempfile.gettempdir(), 'videograb_downloads')
os.makedirs(TEMP_DIR, exist_ok=True)

# Clean up old files
def cleanup_old_files():
    try:
        for filename in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, filename)
            # Remove files older than 1 hour (you can adjust this)
            if os.path.isfile(file_path) and (time.time() - os.path.getmtime(file_path)) > 3600:
                os.remove(file_path)
    except Exception as e:
        print(f"Cleanup error: {e}")

# Helper function to extract video ID from YouTube URL
def extract_youtube_id(url):
    # Regular YouTube URL
    youtube_regex = r'(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
    match = re.search(youtube_regex, url)
    if match:
        return match.group(1)
    
    # Try parsing URL parameters
    parsed_url = urlparse(url)
    if 'youtube.com' in parsed_url.netloc:
        query_params = parse_qs(parsed_url.query)
        if 'v' in query_params:
            return query_params['v'][0]
    
    return None

# Detect platform from URL
def detect_platform(url):
    if 'youtube.com' in url or 'youtu.be' in url:
        return 'youtube'
    elif 'facebook.com' in url or 'fb.watch' in url:
        return 'facebook'
    elif 'instagram.com' in url:
        return 'instagram'
    else:
        return 'unknown'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/info', methods=['POST'])
def get_video_info():
    url = request.form.get('url')
    if not url:
        return jsonify({'success': False, 'error': 'No URL provided'})
    
    platform = detect_platform(url)
    
    if platform == 'youtube':
        try:
            # Use pytube to get video info
            yt = YouTube(url)
            
            # Get available streams
            streams = []
            for stream in yt.streams.filter(progressive=True).order_by('resolution').desc():
                # Calculate approximate size in MB
                size_mb = stream.filesize / (1024 * 1024)
                
                streams.append({
                    'itag': stream.itag,
                    'resolution': stream.resolution,
                    'mime_type': stream.mime_type,
                    'fps': stream.fps,
                    'size_mb': round(size_mb, 2)
                })
            
            # Get video details
            video_info = {
                'id': extract_youtube_id(url),
                'title': yt.title,
                'thumbnail': yt.thumbnail_url,
                'author': yt.author,
                'length': yt.length,
                'streams': streams
            }
            
            return jsonify({
                'success': True,
                'platform': platform,
                'url': url,
                'video_info': video_info
            })
            
        except (RegexMatchError, VideoUnavailable) as e:
            return jsonify({'success': False, 'error': f'Invalid YouTube URL or video unavailable: {str(e)}'})
        except Exception as e:
            return jsonify({'success': False, 'error': f'Failed to get YouTube video info: {str(e)}'})
    
    elif platform in ['facebook', 'instagram']:
        # For Facebook and Instagram, we'll return a basic response
        # You can implement specific APIs for these platforms later
        return jsonify({
            'success': True,
            'platform': platform,
            'url': url,
            'video_info': {
                'title': f'{platform.capitalize()} Video',
                'thumbnail': None,
                'streams': [{
                    'resolution': 'Best Quality',
                    'mime_type': 'video/mp4'
                }]
            }
        })
    
    else:
        return jsonify({'success': False, 'error': 'Unsupported platform'})

@app.route('/api/download', methods=['POST'])
def download_video():
    url = request.form.get('url')
    itag = request.form.get('itag')  # For YouTube specific quality
    
    if not url:
        return jsonify({'success': False, 'error': 'No URL provided'})
    
    platform = detect_platform(url)
    
    if platform == 'youtube':
        try:
            # Use pytube to download
            yt = YouTube(url)
            
            # Select stream based on itag if provided, otherwise highest resolution
            if itag and itag.isdigit():
                stream = yt.streams.get_by_itag(int(itag))
            else:
                stream = yt.streams.filter(progressive=True).order_by('resolution').desc().first()
            
            if not stream:
                return jsonify({'success': False, 'error': 'No suitable stream found'})
            
            # Generate a unique filename
            filename = f"{yt.title.replace(' ', '_')[:50]}_{uuid.uuid4().hex[:8]}.{stream.subtype}"
            safe_filename = re.sub(r'[^\w\-_\.]', '_', filename)
            output_path = os.path.join(TEMP_DIR, safe_filename)
            
            # Download the video
            stream.download(output_path=TEMP_DIR, filename=safe_filename)
            
            # Return the download URL
            download_url = url_for('serve_file', filename=safe_filename, _external=True)
            
            return jsonify({
                'success': True,
                'download_url': download_url,
                'filename': safe_filename
            })
            
        except Exception as e:
            return jsonify({'success': False, 'error': f'Failed to download YouTube video: {str(e)}'})
    
    elif platform in ['facebook', 'instagram']:
        # For Facebook and Instagram, return an error for now
        return jsonify({'success': False, 'error': f'{platform.capitalize()} downloads not yet implemented'})
    
    else:
        return jsonify({'success': False, 'error': 'Unsupported platform'})

@app.route('/download/<filename>')
def serve_file(filename):
    """Serve the downloaded file to the user"""
    file_path = os.path.join(TEMP_DIR, filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    else:
        return "File not found", 404

if __name__ == '__main__':
    import time
    # Run cleanup on startup
    cleanup_old_files()
    app.run(debug=True)
