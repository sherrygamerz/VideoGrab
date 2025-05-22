from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import os
import re
import uuid
import json
import requests
import time
import tempfile
import shutil
from urllib.parse import urlparse, parse_qs

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

# Function to get YouTube video info using yt-dlp (more reliable than pytube)
def get_youtube_info(url):
    try:
        # First try with pytube
        from pytube import YouTube
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
        
        return video_info
        
    except Exception as e:
        print(f"Pytube error: {e}")
        
        # Fallback to direct YouTube API approach
        try:
            video_id = extract_youtube_id(url)
            if not video_id:
                raise ValueError("Could not extract YouTube video ID")
            
            # Get basic video info from oEmbed API (public, no key needed)
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            response = requests.get(oembed_url)
            if response.status_code != 200:
                raise Exception(f"Failed to get video info: HTTP {response.status_code}")
            
            oembed_data = response.json()
            
            # Get thumbnail
            thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
            thumbnail_check = requests.head(thumbnail_url)
            if thumbnail_check.status_code != 200:
                thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
            
            # Create a simplified stream list with common resolutions
            streams = [
                {
                    'itag': '22',
                    'resolution': '720p',
                    'mime_type': 'video/mp4',
                    'fps': 30
                },
                {
                    'itag': '18',
                    'resolution': '360p',
                    'mime_type': 'video/mp4',
                    'fps': 30
                }
            ]
            
            video_info = {
                'id': video_id,
                'title': oembed_data.get('title', 'YouTube Video'),
                'thumbnail': thumbnail_url,
                'author': oembed_data.get('author_name', 'YouTube Creator'),
                'length': 0,  # We don't have this info from oembed
                'streams': streams
            }
            
            return video_info
            
        except Exception as fallback_error:
            print(f"Fallback error: {fallback_error}")
            raise Exception(f"Failed to get YouTube video info: {str(e)}. Fallback also failed: {str(fallback_error)}")

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
    itag = request.form.get('itag')  # For YouTube specific quality
    
    if not url:
        return jsonify({'success': False, 'error': 'No URL provided'})
    
    platform = detect_platform(url)
    
    if platform == 'youtube':
        try:
            # Try with pytube first
            try:
                from pytube import YouTube
                yt = YouTube(url)
                
                # Select stream based on itag if provided, otherwise highest resolution
                if itag and itag.isdigit():
                    stream = yt.streams.get_by_itag(int(itag))
                else:
                    stream = yt.streams.filter(progressive=True).order_by('resolution').desc().first()
                
                if not stream:
                    raise Exception("No suitable stream found")
                
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
                
            except Exception as pytube_error:
                print(f"Pytube download error: {pytube_error}")
                raise Exception(f"Failed to download with pytube: {str(pytube_error)}")
                
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
