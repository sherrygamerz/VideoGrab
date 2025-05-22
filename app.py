import os
import re
import json
import requests
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
from pytube import YouTube
import tempfile
import uuid
import logging
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create temp directory for downloads if it doesn't exist
TEMP_DIR = os.path.join(tempfile.gettempdir(), 'videograb_downloads')
os.makedirs(TEMP_DIR, exist_ok=True)

# Clean up old files periodically (files older than 1 hour will be removed)
def cleanup_old_files():
    import time
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

# YouTube video downloader
def download_youtube(url):
    try:
        yt = YouTube(url)
        video_info = {
            'title': yt.title,
            'author': yt.author,
            'length': yt.length,
            'thumbnail': yt.thumbnail_url,
            'streams': []
        }
        
        # Get available streams
        streams = yt.streams.filter(progressive=True).order_by('resolution').desc()
        
        for stream in streams:
            video_info['streams'].append({
                'itag': stream.itag,
                'resolution': stream.resolution,
                'mime_type': stream.mime_type,
                'fps': stream.fps,
                'size_mb': round(stream.filesize / (1024 * 1024), 2)
            })
        
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
        # Use a different approach for Facebook since it requires more complex handling
        # This is a simplified version that may need to be updated based on Facebook's changes
        
        # Make a request to get the HTML content
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        
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
        
        return {
            'success': True,
            'platform': 'facebook',
            'video_info': {
                'title': title,
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
        # Instagram requires authentication for most operations
        # This is a simplified version that may need to be updated
        
        # Extract the shortcode from the URL
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.strip('/').split('/')
        
        if len(path_parts) < 2 or path_parts[0] != 'p':
            return {
                'success': False,
                'platform': 'instagram',
                'error': "Invalid Instagram URL. Please use a direct post URL."
            }
        
        shortcode = path_parts[1]
        
        # Make a request to the Instagram API
        api_url = f"https://www.instagram.com/p/{shortcode}/?__a=1"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(api_url, headers=headers)
        
        if response.status_code != 200:
            return {
                'success': False,
                'platform': 'instagram',
                'error': f"Failed to fetch the post: {response.status_code}"
            }
        
        try:
            data = response.json()
        except:
            # If JSON parsing fails, try an alternative approach
            # Look for the JSON data in the HTML
            response = requests.get(f"https://www.instagram.com/p/{shortcode}/", headers=headers)
            json_pattern = r'<script type="text/javascript">window\._sharedData = (.*?);</script>'
            json_match = re.search(json_pattern, response.text)
            
            if not json_match:
                return {
                    'success': False,
                    'platform': 'instagram',
                    'error': "Could not extract data from Instagram"
                }
            
            data = json.loads(json_match.group(1))
        
        # Extract video URL from the JSON data
        # Note: Instagram's structure changes frequently, so this might need updates
        try:
            post_data = data['graphql']['shortcode_media']
            is_video = post_data.get('is_video', False)
            
            if not is_video:
                return {
                    'success': False,
                    'platform': 'instagram',
                    'error': "This post does not contain a video"
                }
            
            video_url = post_data.get('video_url')
            if not video_url:
                return {
                    'success': False,
                    'platform': 'instagram',
                    'error': "Could not find video URL"
                }
            
            title = post_data.get('edge_media_to_caption', {}).get('edges', [{}])[0].get('node', {}).get('text', 'Instagram Video')
            thumbnail = post_data.get('display_url')
            
            return {
                'success': True,
                'platform': 'instagram',
                'video_info': {
                    'title': title[:100] + '...' if len(title) > 100 else title,
                    'thumbnail': thumbnail,
                    'streams': [{
                        'quality': 'Standard',
                        'url': video_url
                    }]
                }
            }
        except Exception as e:
            logger.error(f"Instagram JSON parsing error: {str(e)}")
            return {
                'success': False,
                'platform': 'instagram',
                'error': f"Could not extract video information: {str(e)}"
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
            if not itag:
                return jsonify({
                    'success': False,
                    'error': 'No itag provided for YouTube video'
                })
            
            yt = YouTube(url)
            stream = yt.streams.get_by_itag(int(itag))
            
            if not stream:
                return jsonify({
                    'success': False,
                    'error': 'Selected stream not available'
                })
            
            stream.download(output_path=TEMP_DIR, filename=filename)
            
            return jsonify({
                'success': True,
                'download_url': url_for('serve_file', filename=filename),
                'filename': f"{yt.title}.mp4"
            })
        
        elif platform in ['facebook', 'instagram']:
            if not stream_url:
                return jsonify({
                    'success': False,
                    'error': f'No stream URL provided for {platform} video'
                })
            
            # Download the video from the stream URL
            response = requests.get(stream_url, stream=True)
            
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
