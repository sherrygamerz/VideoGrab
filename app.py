from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import os
import uuid
import time
import tempfile
import shutil
import subprocess
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Create a temporary directory for file conversions
TEMP_DIR = os.path.join(tempfile.gettempdir(), 'fileconverter_files')
os.makedirs(TEMP_DIR, exist_ok=True)

# Clean up old files
def cleanup_old_files():
    try:
        for filename in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, filename)
            # Remove files older than 1 hour
            if os.path.isfile(file_path) and (time.time() - os.path.getmtime(file_path)) > 3600:
                os.remove(file_path)
    except Exception as e:
        print(f"Cleanup error: {e}")

# Get supported conversion formats
def get_supported_formats():
    return {
        'image': {
            'input': ['jpg', 'jpeg', 'png', 'bmp', 'gif', 'webp'],
            'output': ['jpg', 'png', 'webp', 'gif', 'bmp']
        },
        'audio': {
            'input': ['mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac'],
            'output': ['mp3', 'wav', 'ogg', 'flac', 'aac']
        },
        'video': {
            'input': ['mp4', 'avi', 'mov', 'mkv', 'webm', 'flv'],
            'output': ['mp4', 'avi', 'mov', 'webm', 'gif']
        },
        'document': {
            'input': ['pdf', 'docx', 'doc', 'txt', 'rtf', 'odt'],
            'output': ['pdf', 'txt']
        }
    }

# Detect file type
def detect_file_type(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    formats = get_supported_formats()
    
    for category, format_info in formats.items():
        if ext in format_info['input']:
            return category, ext
    
    return 'unknown', ext

# Convert file using appropriate method
def convert_file(input_path, output_format):
    filename = os.path.basename(input_path)
    file_category, input_format = detect_file_type(filename)
    
    if file_category == 'unknown':
        raise ValueError(f"Unsupported input format: {input_format}")
    
    formats = get_supported_formats()
    if output_format not in formats[file_category]['output']:
        raise ValueError(f"Unsupported output format for {file_category}: {output_format}")
    
    # Generate output filename
    output_filename = f"{uuid.uuid4().hex}.{output_format}"
    output_path = os.path.join(TEMP_DIR, output_filename)
    
    # Perform conversion based on file category
    if file_category == 'image':
        return convert_image(input_path, output_path, output_format)
    elif file_category == 'audio':
        return convert_audio(input_path, output_path, output_format)
    elif file_category == 'video':
        return convert_video(input_path, output_path, output_format)
    elif file_category == 'document':
        return convert_document(input_path, output_path, output_format)
    else:
        raise ValueError(f"Conversion not supported for {file_category}")

# Image conversion using Pillow
def convert_image(input_path, output_path, output_format):
    try:
        from PIL import Image
        img = Image.open(input_path)
        
        # Convert to RGB if saving as jpg and has transparency
        if output_format.lower() in ['jpg', 'jpeg'] and img.mode == 'RGBA':
            img = img.convert('RGB')
            
        img.save(output_path, format=output_format.upper())
        return output_path
    except Exception as e:
        raise Exception(f"Image conversion failed: {str(e)}")

# Audio conversion using FFmpeg
def convert_audio(input_path, output_path, output_format):
    try:
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-y',  # Overwrite output file if it exists
            output_path
        ]
        
        process = subprocess.run(cmd, capture_output=True, text=True)
        
        if process.returncode != 0:
            raise Exception(f"FFmpeg error: {process.stderr}")
            
        return output_path
    except Exception as e:
        raise Exception(f"Audio conversion failed: {str(e)}")

# Video conversion using FFmpeg
def convert_video(input_path, output_path, output_format):
    try:
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-y',  # Overwrite output file if it exists
        ]
        
        # Special handling for GIF
        if output_format.lower() == 'gif':
            cmd.extend([
                '-vf', 'fps=10,scale=320:-1:flags=lanczos',
                '-c:v', 'gif'
            ])
        
        cmd.append(output_path)
        
        process = subprocess.run(cmd, capture_output=True, text=True)
        
        if process.returncode != 0:
            raise Exception(f"FFmpeg error: {process.stderr}")
            
        return output_path
    except Exception as e:
        raise Exception(f"Video conversion failed: {str(e)}")

# Document conversion
def convert_document(input_path, output_path, output_format):
    try:
        # For PDF to text
        if output_format.lower() == 'txt' and input_path.lower().endswith('.pdf'):
            import PyPDF2
            
            with open(input_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                text = ""
                for page_num in range(len(reader.pages)):
                    text += reader.pages[page_num].extract_text()
            
            with open(output_path, 'w', encoding='utf-8') as txt_file:
                txt_file.write(text)
                
            return output_path
            
        # Other document conversions would go here
        # This would require additional libraries like LibreOffice
        
        raise ValueError(f"Document conversion from {os.path.splitext(input_path)[1]} to {output_format} not supported")
    except Exception as e:
        raise Exception(f"Document conversion failed: {str(e)}")

@app.route('/')
def index():
    return render_template('index.html', formats=get_supported_formats())

@app.route('/api/formats', methods=['GET'])
def api_formats():
    return jsonify(get_supported_formats())

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file part'})
        
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No selected file'})
        
    if file:
        filename = secure_filename(file.filename)
        file_category, input_format = detect_file_type(filename)
        
        if file_category == 'unknown':
            return jsonify({'success': False, 'error': f'Unsupported file format: {input_format}'})
            
        # Save the uploaded file
        temp_filename = f"{uuid.uuid4().hex}.{input_format}"
        temp_path = os.path.join(TEMP_DIR, temp_filename)
        file.save(temp_path)
        
        # Get file info
        file_size = os.path.getsize(temp_path)
        
        return jsonify({
            'success': True,
            'file_info': {
                'id': temp_filename,
                'name': filename,
                'size': file_size,
                'type': file_category,
                'format': input_format,
                'supported_outputs': get_supported_formats()[file_category]['output']
            }
        })

@app.route('/api/convert', methods=['POST'])
def convert_file_api():
    file_id = request.form.get('file_id')
    output_format = request.form.get('output_format')
    
    if not file_id or not output_format:
        return jsonify({'success': False, 'error': 'Missing file_id or output_format'})
    
    input_path = os.path.join(TEMP_DIR, file_id)
    
    if not os.path.exists(input_path):
        return jsonify({'success': False, 'error': 'File not found'})
    
    try:
        output_path = convert_file(input_path, output_format)
        output_filename = os.path.basename(output_path)
        
        # Get original filename without extension
        original_name = request.form.get('original_name', 'converted')
        if '.' in original_name:
            original_name = original_name.rsplit('.', 1)[0]
        
        download_filename = f"{original_name}.{output_format}"
        
        return jsonify({
            'success': True,
            'download_url': url_for('serve_file', filename=output_filename, download_name=download_filename, _external=True),
            'filename': download_filename
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/download/<filename>')
def serve_file(filename):
    """Serve the converted file to the user"""
    download_name = request.args.get('download_name', filename)
    file_path = os.path.join(TEMP_DIR, filename)
    
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name=download_name)
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
