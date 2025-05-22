from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import os
import re
import uuid
import json
import requests
import time
import tempfile
import shutil
import subprocess
from urllib.parse import urlparse, parse_qs
import yt_dlp

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

# Function to get YouTube video info using yt-dlp
def get_youtube_info(url):
    try:
        # Configure yt-dlp options
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'format': 'best',
            'extract_flat': True,
        }
        
        # Get video info
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        # Extract available formats
        formats = info.get('formats', [])
        
        # Filter for video formats with both video and audio (progressive)
        progressive_formats = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
        
        # Sort by resolution
        progressive_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
        
        # Create streams list
        streams = []
        for fmt in progressive_formats:
            # Skip formats without resolution info
            if not fmt.get('height'):
                continue
                
            # Calculate approximate size in MB if filesize is available
            size_mb = None
            if fmt.get('filesize'):
                size_mb = round(fmt.get('filesize') / (1024 * 1024), 2)
            
            streams.append({
                'format_id': fmt.get('format_id'),
                'resolution': f"{fmt.get('height')}p",
                'mime_type': fmt.get('ext', 'mp4'),
                'fps': fmt.get('fps'),
                'size_mb': size_mb,
                'url': fmt.get('url')
            })
        
        # Get video details
        video_info = {
            'id': info.get('id', extract_youtube_id(url)),
            'title': info.get('title', 'YouTube Video'),
            'thumbnail': info.get('thumbnail', f"https://img.youtube.com/vi/{extract_youtube_id(url)}/maxresdefault.jpg"),
            'author': info.get('uploader', 'YouTube Creator'),
            'length': info.get('duration', 0),
            'streams': streams
        }
        
        return video_info
        
    except Exception as e:
        print(f"yt-dlp error: {e}")
        raise Exception(f"Failed to get YouTube video info: {str(e)}")

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
            video_info = get_youtube_info(url)
            
            return jsonify({
                'success': True,
                'platform': platform,
                'url': url,
                'video_info': video_info
            })
            
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
    format_id = request.form.get('format_id')  # For YouTube specific quality
    
    if not url:
        return jsonify({'success': False, 'error': 'No URL provided'})
    
    platform = detect_platform(url)
    
    if platform == 'youtube':
        try:
            # Generate a unique filename base
            video_id = extract_youtube_id(url)
            filename_base = f"youtube_{video_id}_{uuid.uuid4().hex[:8]}"
            output_path = os.path.join(TEMP_DIR, filename_base)
            
            # Configure yt-dlp options
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'outtmpl': f"{output_path}.%(ext)s",
            }
            
            # Add format if specified
            if format_id:
                ydl_opts['format'] = format_id
            else:
                # Default to best quality with video and audio
                ydl_opts['format'] = 'best[height<=1080]'
            
            # Download the video
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                # Get the filename that was actually used
                filename = ydl.prepare_filename(info)
                
            # Check if file exists
            if not os.path.exists(filename):
                # Try with extension
                for ext in ['mp4', 'webm', 'mkv']:
                    test_filename = f"{output_path}.{ext}"
                    if os.path.exists(test_filename):
                        filename = test_filename
                        break
                else:
                    raise Exception("Downloaded file not found")
            
            # Get just the filename without the path
            base_filename = os.path.basename(filename)
            
            # Return the download URL
            download_url = url_for('serve_file', filename=base_filename, _external=True)
            
            return jsonify({
                'success': True,
                'download_url': download_url,
                'filename': base_filename
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

@app.route('/health')
def health_check():
    """Health check endpoint for Render"""
    return "OK", 200

if __name__ == '__main__':
    # Run cleanup on startup
    cleanup_old_files()
    app.run(debug=True)
