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
    elif 'tiktok.com' in url:
        return 'tiktok'
    else:
        return 'unknown'

# Function to get YouTube video info using yt-dlp subprocess
def get_youtube_info(url):
    try:
        video_id = extract_youtube_id(url)
        if not video_id:
            raise ValueError("Could not extract YouTube video ID")
        
        # Create a unique filename for the JSON output
        json_file = os.path.join(TEMP_DIR, f"info_{video_id}_{uuid.uuid4().hex[:8]}.json")
        
        # Run yt-dlp to get video info
        cmd = [
            'yt-dlp',
            '--dump-json',
            '--no-playlist',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            '--referer', 'https://www.youtube.com/',
            '--no-check-certificate',
            '--geo-bypass-country', 'US',
            url,
            '-o', json_file
        ]
        
        # Add cookies file if it exists
        cookies_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
        if os.path.exists(cookies_file):
            cmd.extend(['--cookies', cookies_file])
        
        # Run the command
        process = subprocess.run(cmd, capture_output=True, text=True)
        
        # Check if the command was successful
        if process.returncode != 0:
            print(f"yt-dlp error: {process.stderr}")
            raise Exception(f"yt-dlp error: {process.stderr}")
        
        # Parse the JSON output
        info = json.loads(process.stdout)
        
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
                'size_mb': size_mb
            })
        
        # Get video details
        video_info = {
            'id': info.get('id', video_id),
            'title': info.get('title', 'YouTube Video'),
            'thumbnail': info.get('thumbnail', f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"),
            'author': info.get('uploader', 'YouTube Creator'),
            'length': info.get('duration', 0),
            'streams': streams
        }
        
        return video_info
        
    except Exception as e:
        print(f"YouTube info error: {e}")
        
        # Fallback to basic info
        try:
            # Get basic video info from oEmbed API (public, no key needed)
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            response = requests.get(oembed_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Referer': 'https://www.youtube.com/'
            })
            
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
                    'format_id': 'best',
                    'resolution': 'Best Quality',
                    'mime_type': 'video/mp4',
                    'fps': 30
                },
                {
                    'format_id': '18',
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
    
    elif platform in ['facebook', 'instagram', 'tiktok']:
        # For other platforms, we'll return a basic response
        # You can implement specific APIs for these platforms later
        return jsonify({
            'success': True,
            'platform': platform,
            'url': url,
            'video_info': {
                'title': f'{platform.capitalize()} Video',
                'thumbnail': None,
                'streams': [{
                    'format_id': 'best',
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
            
            # Build the yt-dlp command
            cmd = [
                'yt-dlp',
                '--no-playlist',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                '--referer', 'https://www.youtube.com/',
                '--no-check-certificate',
                '--geo-bypass-country', 'US'
            ]
            
            # Add cookies file if it exists
            cookies_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
            if os.path.exists(cookies_file):
                cmd.extend(['--cookies', cookies_file])
            
            # Add format if specified
            if format_id and format_id != 'best':
                cmd.extend(['-f', format_id])
            else:
                cmd.extend(['-f', 'best[height<=1080]'])
            
            # Add output template
            cmd.extend(['-o', f"{output_path}.%(ext)s"])
            
            # Add URL
            cmd.append(url)
            
            # Run the command
            process = subprocess.run(cmd, capture_output=True, text=True)
            
            # Check if the command was successful
            if process.returncode != 0:
                print(f"yt-dlp error: {process.stderr}")
                raise Exception(f"yt-dlp error: {process.stderr}")
            
            # Find the downloaded file
            downloaded_file = None
            for ext in ['mp4', 'webm', 'mkv']:
                test_filename = f"{output_path}.{ext}"
                if os.path.exists(test_filename):
                    downloaded_file = test_filename
                    break
            
            if not downloaded_file:
                raise Exception("Downloaded file not found")
            
            # Get just the filename without the path
            base_filename = os.path.basename(downloaded_file)
            
            # Return the download URL
            download_url = url_for('serve_file', filename=base_filename, _external=True)
            
            return jsonify({
                'success': True,
                'download_url': download_url,
                'filename': base_filename
            })
                
        except Exception as e:
            # Fallback to thumbnail download
            try:
                video_id = extract_youtube_id(url)
                if not video_id:
                    raise Exception("Could not extract YouTube video ID")
                
                # Get video info to get the title
                try:
                    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
                    response = requests.get(oembed_url, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    })
                    video_title = response.json().get('title', 'YouTube Video')
                except:
                    video_title = 'YouTube Video'
                
                # At least return the thumbnail as a fallback
                thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                thumbnail_response = requests.get(thumbnail_url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                })
                
                if thumbnail_response.status_code != 200:
                    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                    thumbnail_response = requests.get(thumbnail_url, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    })
                
                if thumbnail_response.status_code != 200:
                    raise Exception("Failed to download thumbnail as fallback")
                
                # Save the thumbnail
                thumbnail_filename = f"youtube_thumbnail_{video_id}.jpg"
                thumbnail_path = os.path.join(TEMP_DIR, thumbnail_filename)
                
                with open(thumbnail_path, 'wb') as f:
                    f.write(thumbnail_response.content)
                
                # Return the thumbnail URL
                download_url = url_for('serve_file', filename=thumbnail_filename, _external=True)
                
                return jsonify({
                    'success': True,
                    'download_url': download_url,
                    'filename': f"{video_title}.jpg",
                    'is_fallback': True,
                    'fallback_message': "Could not download video due to YouTube's bot protection. Thumbnail downloaded instead."
                })
            
            except Exception as fallback_error:
                return jsonify({'success': False, 'error': f'Failed to download YouTube video: {str(e)}. Fallback also failed: {str(fallback_error)}'})
    
    elif platform in ['facebook', 'instagram', 'tiktok']:
        # For other platforms, return an error for now
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
