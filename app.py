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

# RapidAPI YouTube API Key
RAPIDAPI_KEY = "16c6178069mshcf2c2d8c7f50fccp1037f4jsn9cb06df7637a"
RAPIDAPI_HOST = "youtube138.p.rapidapi.com"

# Browser-like headers to avoid detection
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Referer': 'https://www.google.com/',
    'DNT': '1',  # Do Not Track
}

# RapidAPI headers
RAPIDAPI_HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": RAPIDAPI_HOST
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

# YouTube video downloader using RapidAPI
def download_youtube(url):
    try:
        video_id = extract_youtube_id(url)
        if not video_id:
            return {
                'success': False,
                'platform': 'youtube',
                'error': 'Could not extract YouTube video ID'
            }
        
        # Get video details from RapidAPI
        api_url = f"https://youtube138.p.rapidapi.com/video/details/"
        querystring = {"id": video_id}
        
        response = requests.get(api_url, headers=RAPIDAPI_HEADERS, params=querystring)
        
        if response.status_code != 200:
            return {
                'success': False,
                'platform': 'youtube',
                'error': f"Failed to get video info: {response.status_code}"
            }
        
        video_data = response.json()
        
        # Get video streams from RapidAPI
        streams_url = f"https://youtube138.p.rapidapi.com/video/streams/"
        streams_response = requests.get(streams_url, headers=RAPIDAPI_HEADERS, params=querystring)
        
        if streams_response.status_code != 200:
            return {
                'success': False,
                'platform': 'youtube',
                'error': f"Failed to get video streams: {streams_response.status_code}"
            }
        
        streams_data = streams_response.json()
        
        # Extract relevant information
        title = video_data.get('title', 'YouTube Video')
        author = video_data.get('author', {}).get('title', 'Unknown')
        thumbnail = video_data.get('thumbnails', [{}])[-1].get('url') if video_data.get('thumbnails') else None
        duration = video_data.get('lengthSeconds', 0)
        
        # Process streams
        available_streams = []
        
        # Add adaptive formats (usually better quality)
        if 'adaptiveFormats' in streams_data:
            for stream in streams_data['adaptiveFormats']:
                if stream.get('mimeType', '').startswith('video/'):
                    quality = stream.get('qualityLabel', 'Unknown')
                    itag = stream.get('itag', '')
                    url = stream.get('url', '')
                    mime_type = stream.get('mimeType', '').split(';')[0]
                    fps = stream.get('fps', 30)
                    
                    # Calculate approximate size in MB (bitrate * duration / 8 / 1024 / 1024)
                    bitrate = stream.get('bitrate', 0)
                    size_mb = round((bitrate * int(duration)) / 8 / 1024 / 1024, 2)
                    
                    if url:  # Only add if URL is available
                        available_streams.append({
                            'itag': itag,
                            'resolution': quality,
                            'mime_type': mime_type,
                            'fps': fps,
                            'size_mb': size_mb,
                            'url': url
                        })
        
        # Add formats (combined audio and video)
        if 'formats' in streams_data:
            for stream in streams_data['formats']:
                quality = stream.get('qualityLabel', 'Unknown')
                itag = stream.get('itag', '')
                url = stream.get('url', '')
                mime_type = stream.get('mimeType', '').split(';')[0]
                fps = stream.get('fps', 30)
                
                # Calculate approximate size in MB
                bitrate = stream.get('bitrate', 0)
                size_mb = round((bitrate * int(duration)) / 8 / 1024 / 1024, 2)
                
                if url:  # Only add if URL is available
                    available_streams.append({
                        'itag': itag,
                        'resolution': quality,
                        'mime_type': mime_type,
                        'fps': fps,
                        'size_mb': size_mb,
                        'url': url
                    })
        
        # Sort streams by resolution (highest first)
        available_streams.sort(key=lambda x: x.get('size_mb', 0), reverse=True)
        
        # Limit to top 5 streams to avoid overwhelming the user
        available_streams = available_streams[:5]
        
        video_info = {
            'title': title,
            'author': author,
            'thumbnail': thumbnail,
            'length': int(duration),
            'streams': available_streams,
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
    stream_url = request.form.get('stream_url')  # Direct stream URL
    
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
        
        if not stream_url:
            return jsonify({
                'success': False,
                'error': 'No stream URL provided'
            })
        
        # Download the video from the stream URL
        response = requests.get(stream_url, stream=True, headers=HEADERS)
        
        if response.status_code != 200:
            return jsonify({
                'success': False,
                'error': f'Failed to download video: {response.status_code}'
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
