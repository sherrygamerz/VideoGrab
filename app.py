import os
import re
import json
import requests
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import tempfile
import uuid
import logging
from urllib.parse import urlparse, parse_qs
import time

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create temp directory for downloads if it doesn't exist
TEMP_DIR = os.path.join(tempfile.gettempdir(), 'videograb_downloads')
os.makedirs(TEMP_DIR, exist_ok=True)

# Browser-like headers to avoid detection
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Referer': 'https://www.google.com/',
    'DNT': '1',  # Do Not Track
}

# Clean up old files periodically (files older than 1 hour will be removed)
def cleanup_old_files():
    current_time = time.time()
    for filename in os.listdir(TEMP_DIR):
        file_path = os.path.join(TEMP_DIR, filename)
        # If file is older than 1 hour, remove it
        if os.path.isfile(file_path) and os.stat(file_path).st_mtime < current_time - 3600:
            os.remove(file_path)

# Helper function to identify the platform from URL
def identify_platform(url):
    if not url:
        return None
        
    domain = urlparse(url).netloc.lower()
    
    if 'youtube.com' in domain or 'youtu.be' in domain:
        return 'youtube'
    elif 'facebook.com' in domain or 'fb.com' in domain or 'fb.watch' in domain:
        return 'facebook'
    elif 'instagram.com' in domain:
        return 'instagram'
    else:
        return None

# Extract YouTube video ID from URL
def extract_youtube_id(url):
    if 'youtube.com/watch' in url:
        query = parse_qs(urlparse(url).query)
        return query.get('v', [None])[0]
    elif 'youtu.be/' in url:
        return url.split('youtu.be/')[1].split('?')[0]
    elif 'youtube.com/shorts/' in url:
        return url.split('youtube.com/shorts/')[1].split('?')[0]
    return None

# YouTube video downloader using direct API approach
def download_youtube(url):
    try:
        video_id = extract_youtube_id(url)
        if not video_id:
            return {
                'success': False,
                'platform': 'youtube',
                'error': 'Could not extract YouTube video ID'
            }
        
        # Get video info using YouTube's oEmbed API
        oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        oembed_response = requests.get(oembed_url, headers=HEADERS)
        
        if oembed_response.status_code != 200:
            return {
                'success': False,
                'platform': 'youtube',
                'error': f"Failed to get video info: {oembed_response.status_code}"
            }
        
        oembed_data = oembed_response.json()
        title = oembed_data.get('title', 'YouTube Video')
        author = oembed_data.get('author_name', 'Unknown')
        thumbnail = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
        
        # Get available streams using a more reliable approach
        # For simplicity, we'll provide fixed quality options that are commonly available
        streams = [
            {
                'itag': 'high',
                'resolution': '720p',
                'mime_type': 'video/mp4',
                'fps': 30,
                'size_mb': 15.0  # Estimated size
            },
            {
                'itag': 'medium',
                'resolution': '360p',
                'mime_type': 'video/mp4',
                'fps': 30,
                'size_mb': 8.0  # Estimated size
            },
            {
                'itag': 'low',
                'resolution': '144p',
                'mime_type': 'video/mp4',
                'fps': 30,
                'size_mb': 3.0  # Estimated size
            }
        ]
        
        video_info = {
            'title': title,
            'author': author,
            'thumbnail': thumbnail,
            'streams': streams,
            'id': video_id
        }
        
        return {
            'success': True,
            'platform': 'youtube',
            'video_info': video_info
        }
    except Exception as e:
        logger.error(f"YouTube download error: {str(e)}")
        return {
            'success': False,
            'platform': 'youtube',
            'error': str(e)
        }

# Facebook video downloader
def download_facebook(url):
    try:
        # Make a request to get the HTML content with browser-like headers
        response = requests.get(url, headers=HEADERS)
        
        if response.status_code != 200:
            return {
                'success': False,
                'platform': 'facebook',
                'error': f"Failed to fetch the page: {response.status_code}"
            }
        
        # Look for HD video URL in the HTML content
        hd_pattern = r'hd_src:"([^"]+)"'
        sd_pattern = r'sd_src:"([^"]+)"'
        
        hd_match = re.search(hd_pattern, response.text)
        sd_match = re.search(sd_pattern, response.text)
        
        # If the above patterns don't work, try alternative patterns
        if not hd_match and not sd_match:
            hd_pattern = r'"hd_src":"([^"]+)"'
            sd_pattern = r'"sd_src":"([^"]+)"'
            
            hd_match = re.search(hd_pattern, response.text)
            sd_match = re.search(sd_pattern, response.text)
        
        video_urls = []
        
        if hd_match:
            video_urls.append({
                'quality': 'HD',
                'url': hd_match.group(1).replace('\\', '')
            })
        
        if sd_match:
            video_urls.append({
                'quality': 'SD',
                'url': sd_match.group(1).replace('\\', '')
            })
        
        # If still no URLs found, try another approach
        if not video_urls:
            # Try to find any video URL in the page
            video_pattern = r'(https://video[^"\']+\.mp4[^"\']*)'
            video_matches = re.findall(video_pattern, response.text)
            
            for i, url in enumerate(video_matches):
                video_urls.append({
                    'quality': f'Quality {i+1}',
                    'url': url.replace('\\', '')
                })
        
        if not video_urls:
            return {
                'success': False,
                'platform': 'facebook',
                'error': "Could not find video URL in the page"
            }
        
        # Try to get the title
        title_pattern = r'<title>(.*?)</title>'
        title_match = re.search(title_pattern, response.text)
        title = title_match.group(1) if title_match else "Facebook Video"
        
        # Try to get thumbnail
        thumbnail_pattern = r'og:image" content="([^"]+)"'
        thumbnail_match = re.search(thumbnail_pattern, response.text)
        thumbnail = thumbnail_match.group(1) if thumbnail_match else None
        
        return {
            'success': True,
            'platform': 'facebook',
            'video_info': {
                'title': title,
                'thumbnail': thumbnail,
                'streams': video_urls
            }
        }
    except Exception as e:
        logger.error(f"Facebook download error: {str(e)}")
        return {
            'success': False,
            'platform': 'facebook',
            'error': str(e)
        }

# Instagram video downloader
def download_instagram(url):
    try:
        # Make a request to the Instagram URL with browser-like headers
        response = requests.get(url, headers=HEADERS)
        
        if response.status_code != 200:
            return {
                'success': False,
                'platform': 'instagram',
                'error': f"Failed to fetch the post: {response.status_code}"
            }
        
        # Look for video URL in the HTML
        video_pattern = r'"video_url":"([^"]+)"'
        video_match = re.search(video_pattern, response.text)
        
        if not video_match:
            # Try alternative pattern
            video_pattern = r'property="og:video" content="([^"]+)"'
            video_match = re.search(video_pattern, response.text)
        
        if not video_match:
            return {
                'success': False,
                'platform': 'instagram',
                'error': "Could not find video URL in the page"
            }
        
        video_url = video_match.group(1).replace('\\u0026', '&')
        
        # Get title/caption
        title_pattern = r'"edge_media_to_caption":\s*{\s*"edges":\s*\[\s*{\s*"node":\s*{\s*"text":\s*"([^"]+)"'
        title_match = re.search(title_pattern, response.text)
        
        if not title_match:
            # Try alternative pattern
            title_pattern = r'<meta property="og:title" content="([^"]+)"'
            title_match = re.search(title_pattern, response.text)
        
        title = title_match.group(1) if title_match else "Instagram Video"
        
        # Get thumbnail
        thumbnail_pattern = r'"display_url":"([^"]+)"'
        thumbnail_match = re.search(thumbnail_pattern, response.text)
        
        if not thumbnail_match:
            # Try alternative pattern
            thumbnail_pattern = r'property="og:image" content="([^"]+)"'
            thumbnail_match = re.search(thumbnail_pattern, response.text)
        
        thumbnail = thumbnail_match.group(1).replace('\\u0026', '&') if thumbnail_match else None
        
        return {
            'success': True,
            'platform': 'instagram',
            'video_info': {
                'title': title,
                'thumbnail': thumbnail,
                'streams': [{
                    'quality': 'Standard',
                    'url': video_url
                }]
            }
        }
    except Exception as e:
        logger.error(f"Instagram download error: {str(e)}")
        return {
            'success': False,
            'platform': 'instagram',
            'error': str(e)
        }

@app.route('/')
def index():
    # Clean up old files
    cleanup_old_files()
    return render_template('index.html')

@app.route('/api/info', methods=['POST'])
def get_video_info():
    url = request.form.get('url')
    if not url:
        return jsonify({
            'success': False,
            'error': 'No URL provided'
        })
    
    platform = identify_platform(url)
    
    if not platform:
        return jsonify({
            'success': False,
            'error': 'Unsupported platform. Please use YouTube, Facebook, or Instagram URLs.'
        })
    
    if platform == 'youtube':
        result = download_youtube(url)
    elif platform == 'facebook':
        result = download_facebook(url)
    elif platform == 'instagram':
        result = download_instagram(url)
    
    return jsonify(result)

@app.route('/api/download', methods=['POST'])
def download_video():
    url = request.form.get('url')
    itag = request.form.get('itag')  # For YouTube
    stream_url = request.form.get('stream_url')  # For Facebook/Instagram
    
    if not url:
        return jsonify({
            'success': False,
            'error': 'No URL provided'
        })
    
    platform = identify_platform(url)
    
    if not platform:
        return jsonify({
            'success': False,
            'error': 'Unsupported platform'
        })
    
    try:
        # Generate a unique filename
        filename = f"{platform}_{uuid.uuid4().hex}.mp4"
        file_path = os.path.join(TEMP_DIR, filename)
        
        if platform == 'youtube':
            video_id = extract_youtube_id(url)
            if not video_id:
                return jsonify({
                    'success': False,
                    'error': 'Could not extract YouTube video ID'
                })
            
            # For YouTube, we'll use a different approach
            # Instead of trying to download directly (which is increasingly difficult),
            # we'll redirect to a reliable third-party service
            
            # Create a YouTube download service URL
            if itag == 'high':
                quality = '720'
            elif itag == 'medium':
                quality = '360'
            else:
                quality = '144'
                
            # Use y2mate or similar service (this is just an example)
            download_service_url = f"https://www.y2mate.com/youtube/{video_id}"
            
            return jsonify({
                'success': True,
                'redirect': True,
                'service_url': download_service_url,
                'message': 'Redirecting to download service...'
            })
            
        elif platform in ['facebook', 'instagram']:
            if not stream_url:
                return jsonify({
                    'success': False,
                    'error': f'No stream URL provided for {platform} video'
                })
            
            # Download the video from the stream URL
            response = requests.get(stream_url, stream=True, headers=HEADERS)
            
            if response.status_code != 200:
                return jsonify({
                    'success': False,
                    'error': f'Failed to download {platform} video: {response.status_code}'
                })
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
            
            return jsonify({
                'success': True,
                'download_url': url_for('serve_file', filename=filename),
                'filename': f"{platform}_video.mp4"
            })
    
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/download/<filename>')
def serve_file(filename):
    file_path = os.path.join(TEMP_DIR, filename)
    
    if not os.path.exists(file_path):
        return "File not found", 404
    
    # Get the original filename from the query parameter
    original_filename = request.args.get('name', 'video.mp4')
    
    return send_file(file_path, as_attachment=True, download_name=original_filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
