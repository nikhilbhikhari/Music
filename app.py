from flask import Flask, request, jsonify, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime
import requests
from mutagen import File
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3
import os
import tempfile

app = Flask(__name__)
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///music.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class Song(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    singer = db.Column(db.String(100), nullable=False)
    song_url = db.Column(db.String(500), nullable=False)
    image_url = db.Column(db.String(500), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def extract_metadata(url):
    try:
        app.logger.info(f"Starting metadata extraction for URL: {url}")
        
        # Download the file to a temporary location
        response = requests.get(url, stream=True)
        if not response.ok:
            app.logger.error(f"Failed to download file. Status code: {response.status_code}")
            return None

        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_file:
            for chunk in response.iter_content(chunk_size=8192):
                temp_file.write(chunk)
            temp_path = temp_file.name

        try:
            app.logger.info(f"Temporary file created at: {temp_path}")
            
            # Try to read the file with mutagen
            audio = File(temp_path)
            
            if audio is None:
                app.logger.error("Failed to read audio file with mutagen")
                return None

            # Extract metadata
            title = None
            artist = None
            year = None
            image_url = None

            # Try different methods to get metadata
            if hasattr(audio, 'tags'):
                app.logger.info("Audio file has tags, attempting to extract metadata")
                
                if isinstance(audio, MP3):
                    try:
                        id3 = ID3(temp_path)
                        if 'APIC:' in id3:
                            app.logger.info("Found APIC tag, extracting cover art")
                            apic = id3['APIC:'].data
                            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as img_file:
                                img_file.write(apic)
                                image_url = img_file.name
                                app.logger.info(f"Cover art extracted to: {image_url}")
                    except Exception as e:
                        app.logger.warning(f"Failed to extract cover art: {str(e)}")

                try:
                    easy = EasyID3(temp_path)
                    title = easy.get('title', [None])[0]
                    artist = easy.get('artist', [None])[0]
                    date = easy.get('date', [None])[0]
                    if date:
                        year = int(date.split('-')[0])
                    app.logger.info(f"Extracted metadata using EasyID3: title={title}, artist={artist}, year={year}")
                except Exception as e:
                    app.logger.warning(f"Failed to extract metadata using EasyID3: {str(e)}")

            # Fallback to basic tags if EasyID3 failed
            if not title and hasattr(audio, 'tags'):
                title = audio.tags.get('TIT2', [None])[0]
            if not artist and hasattr(audio, 'tags'):
                artist = audio.tags.get('TPE1', [None])[0]
            if not year and hasattr(audio, 'tags'):
                year_str = audio.tags.get('TDRC', [None])[0]
                if year_str:
                    year = int(year_str.split('-')[0])
            
            app.logger.info(f"Final extracted metadata: title={title}, artist={artist}, year={year}")

            # Clean up temporary files
            os.unlink(temp_path)
            if image_url:
                os.unlink(image_url)

            return {
                'title': title or 'Unknown Title',
                'singer': artist or 'Unknown Artist',
                'image_url': 'https://via.placeholder.com/150',  # Default image if no cover art
                'year': year or datetime.now().year
            }

        except Exception as e:
            app.logger.error(f"Error processing audio file: {str(e)}")
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            return None

    except Exception as e:
        app.logger.error(f"Error downloading file: {str(e)}")
        return None

@app.route('/extract_metadata', methods=['POST'])
def handle_extract_metadata():
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            app.logger.error("No URL provided in request")
            return jsonify({'error': 'URL is required'}), 400

        url = data['url']
        app.logger.info(f"Received request to extract metadata from URL: {url}")

        # Validate URL
        if not url.startswith(('http://', 'https://')):
            app.logger.error(f"Invalid URL format: {url}")
            return jsonify({'error': 'Invalid URL format'}), 400

        # Extract metadata
        metadata = extract_metadata(url)
        if metadata is None:
            app.logger.error("Failed to extract metadata")
            return jsonify({'error': 'Failed to extract metadata from the audio file'}), 500

        app.logger.info(f"Successfully extracted metadata: {metadata}")
        return jsonify(metadata)

    except Exception as e:
        app.logger.error(f"Unexpected error in extract_metadata route: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred'}), 500

@app.route('/api/songs', methods=['GET'])
def get_songs():
    try:
        songs = Song.query.all()
        return jsonify([{
            'id': song.id,
            'title': song.title,
            'singer': song.singer,
            'song_url': song.song_url,
            'image_url': song.image_url,
            'year': song.year
        } for song in songs])
    except Exception as e:
        app.logger.error(f"Error getting songs: {str(e)}")
        return jsonify({'error': 'An error occurred'}), 500

@app.route('/api/songs/search', methods=['GET'])
def search_songs():
    try:
        query = request.args.get('q', '').lower()
        field = request.args.get('field', 'all')
        
        if field == 'year':
            songs = Song.query.filter(Song.year == int(query)).all()
        elif field == 'title':
            songs = Song.query.filter(Song.title.ilike(f'%{query}%')).all()
        elif field == 'singer':
            songs = Song.query.filter(Song.singer.ilike(f'%{query}%')).all()
        else:
            songs = Song.query.filter(
                db.or_(
                    Song.title.ilike(f'%{query}%'),
                    Song.singer.ilike(f'%{query}%'),
                    Song.year.ilike(f'%{query}%')
                )
            ).all()
        
        return jsonify([{
            'id': song.id,
            'title': song.title,
            'singer': song.singer,
            'song_url': song.song_url,
            'image_url': song.image_url,
            'year': song.year
        } for song in songs])
    except Exception as e:
        app.logger.error(f"Error searching songs: {str(e)}")
        return jsonify({'error': 'An error occurred'}), 500

@app.route('/api/songs', methods=['POST'])
def add_song():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        required_fields = ['title', 'singer', 'song_url', 'image_url', 'year']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        new_song = Song(
            title=data['title'],
            singer=data['singer'],
            song_url=data['song_url'],
            image_url=data['image_url'],
            year=int(data['year'])
        )
        db.session.add(new_song)
        db.session.commit()
        return jsonify({'message': 'Song added successfully', 'id': new_song.id}), 201
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error adding song: {str(e)}")
        return jsonify({'error': 'Failed to add song'}), 500

@app.route('/api/songs/<int:song_id>', methods=['DELETE'])
def delete_song(song_id):
    try:
        song = Song.query.get_or_404(song_id)
        db.session.delete(song)
        db.session.commit()
        return jsonify({'message': 'Song deleted successfully'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting song: {str(e)}")
        return jsonify({'error': 'Failed to delete song'}), 500

@app.route('/api/songs/<int:song_id>', methods=['PUT'])
def edit_song(song_id):
    try:
        song = Song.query.get_or_404(song_id)
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Update song details
        if 'title' in data:
            song.title = data['title']
        if 'singer' in data:
            song.singer = data['singer']
        if 'song_url' in data:
            song.song_url = data['song_url']
        if 'image_url' in data:
            song.image_url = data['image_url']
        if 'year' in data:
            song.year = int(data['year'])
        
        db.session.commit()
        return jsonify({'message': 'Song updated successfully'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating song: {str(e)}")
        return jsonify({'error': 'Failed to update song'}), 500

@app.route('/')
def dashboard():
    dashboard_html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Music Player Dashboard</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
                background: #f5f5f5;
            }
            .header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
            }
            .add-song, .song-list {
                background: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                margin-bottom: 20px;
            }
            .form-group {
                margin-bottom: 15px;
            }
            label {
                display: block;
                margin-bottom: 5px;
                font-weight: bold;
            }
            input[type="text"] {
                width: 100%;
                padding: 10px;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 16px;
            }
            button {
                padding: 10px 20px;
                background: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 16px;
            }
            button:hover {
                background: #45a049;
            }
            .song-item {
                padding: 15px;
                border-bottom: 1px solid #eee;
                display: flex;
                align-items: center;
                gap: 15px;
            }
            .song-item img {
                width: 60px;
                height: 60px;
                object-fit: cover;
                border-radius: 4px;
            }
            .song-info {
                flex: 1;
            }
            .song-actions {
                display: flex;
                gap: 10px;
            }
            .delete-btn {
                background: #f44336;
            }
            .delete-btn:hover {
                background: #d32f2f;
            }
            .edit-btn {
                background: #2196F3;
            }
            .edit-btn:hover {
                background: #1976D2;
            }
            .search-box {
                margin-bottom: 20px;
            }
            .search-box input {
                width: 100%;
                padding: 10px;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 16px;
            }
            .message {
                padding: 10px;
                margin-bottom: 15px;
                border-radius: 4px;
            }
            .error {
                background: #ffebee;
                color: #c62828;
            }
            .success {
                background: #e8f5e9;
                color: #2e7d32;
            }
            .extract-btn {
                background: #FF9800;
            }
            .extract-btn:hover {
                background: #F57C00;
            }
            .metadata-fields {
                display: none;
                margin-top: 15px;
                padding: 15px;
                background: #f8f9fa;
                border-radius: 4px;
            }
            .metadata-fields.show {
                display: block;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Music Player Dashboard</h1>
            <button onclick="window.location.reload()">Refresh</button>
        </div>

        <div class="add-song">
            <h2>Add New Song</h2>
            <form id="addSongForm">
                <div class="form-group">
                    <label for="song_url">Song URL</label>
                    <input type="text" id="song_url" name="song_url" required>
                </div>
                <div class="form-group">
                    <label for="image_url">Image URL (Optional)</label>
                    <input type="text" id="image_url" name="image_url">
                </div>
                <button type="button" class="extract-btn" onclick="extractMetadata()">Extract Metadata</button>
                
                <div id="metadataFields" class="metadata-fields">
                    <div class="form-group">
                        <label for="title">Title</label>
                        <input type="text" id="title" name="title" readonly>
                    </div>
                    <div class="form-group">
                        <label for="singer">Artist</label>
                        <input type="text" id="singer" name="singer" readonly>
                    </div>
                    <div class="form-group">
                        <label for="year">Year</label>
                        <input type="text" id="year" name="year" readonly>
                    </div>
                    <button type="submit">Add Song</button>
                </div>
            </form>
        </div>

        <div class="song-list">
            <h2>All Songs</h2>
            <div class="search-box">
                <input type="text" id="searchInput" placeholder="Search songs...">
            </div>
            <div id="songsList"></div>
        </div>

        <script>
            let songs = [];

            async function extractMetadata() {
                const songUrl = document.getElementById('song_url').value;
                if (!songUrl) {
                    showMessage('Please enter a song URL', 'error');
                    return;
                }

                try {
                    const response = await fetch('/extract_metadata', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ url: songUrl })
                    });

                    const data = await response.json();

                    if (response.ok) {
                        document.getElementById('title').value = data.title || '';
                        document.getElementById('singer').value = data.singer || '';
                        document.getElementById('year').value = data.year || '';
                        document.getElementById('metadataFields').classList.add('show');
                        showMessage('Metadata extracted successfully!', 'success');
                    } else {
                        throw new Error(data.error || 'Failed to extract metadata');
                    }
                } catch (error) {
                    showMessage(error.message, 'error');
                }
            }

            async function loadSongs() {
                try {
                    const response = await fetch('/api/songs');
                    songs = await response.json();
                    displaySongs(songs);
                } catch (error) {
                    showMessage('Error loading songs: ' + error.message, 'error');
                }
            }

            function displaySongs(songsToDisplay) {
                const songsList = document.getElementById('songsList');
                songsList.innerHTML = songsToDisplay.map(song => `
                    <div class="song-item" data-id="${song.id}">
                        <img src="${song.image_url}" alt="${song.title}">
                        <div class="song-info">
                            <strong>${song.title}</strong> - ${song.singer} (${song.year})
                        </div>
                        <div class="song-actions">
                            <button class="edit-btn" onclick="editSong(${song.id})">Edit</button>
                            <button class="delete-btn" onclick="deleteSong(${song.id})">Delete</button>
                        </div>
                    </div>
                `).join('');
            }

            async function addSong(event) {
                event.preventDefault();
                const form = event.target;
                const formData = {
                    title: form.title.value,
                    singer: form.singer.value,
                    song_url: form.song_url.value,
                    image_url: form.image_url.value || 'https://via.placeholder.com/150',
                    year: parseInt(form.year.value)
                };

                try {
                    const response = await fetch('/api/songs', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify(formData)
                    });

                    if (response.ok) {
                        showMessage('Song added successfully!', 'success');
                        form.reset();
                        document.getElementById('metadataFields').classList.remove('show');
                        loadSongs();
                    } else {
                        const error = await response.json();
                        throw new Error(error.error || 'Failed to add song');
                    }
                } catch (error) {
                    showMessage(error.message, 'error');
                }
            }

            async function deleteSong(songId) {
                if (!confirm('Are you sure you want to delete this song?')) return;

                try {
                    const response = await fetch(`/api/songs/${songId}`, {
                        method: 'DELETE'
                    });

                    if (response.ok) {
                        showMessage('Song deleted successfully!', 'success');
                        loadSongs();
                    } else {
                        const error = await response.json();
                        throw new Error(error.error || 'Failed to delete song');
                    }
                } catch (error) {
                    showMessage(error.message, 'error');
                }
            }

            async function editSong(songId) {
                const song = songs.find(s => s.id === songId);
                if (!song) return;

                const newTitle = prompt('Enter new title:', song.title);
                const newSinger = prompt('Enter new artist:', song.singer);
                const newYear = prompt('Enter new year:', song.year);

                if (!newTitle || !newSinger || !newYear) return;

                try {
                    const response = await fetch(`/api/songs/${songId}`, {
                        method: 'PUT',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            title: newTitle,
                            singer: newSinger,
                            year: parseInt(newYear)
                        })
                    });

                    if (response.ok) {
                        showMessage('Song updated successfully!', 'success');
                        loadSongs();
                    } else {
                        const error = await response.json();
                        throw new Error(error.error || 'Failed to update song');
                    }
                } catch (error) {
                    showMessage(error.message, 'error');
                }
            }

            function showMessage(message, type) {
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${type}`;
                messageDiv.textContent = message;
                document.body.insertBefore(messageDiv, document.body.firstChild);
                setTimeout(() => messageDiv.remove(), 5000);
            }

            // Search functionality
            document.getElementById('searchInput').addEventListener('input', (e) => {
                const searchTerm = e.target.value.toLowerCase();
                const filteredSongs = songs.filter(song => 
                    song.title.toLowerCase().includes(searchTerm) ||
                    song.singer.toLowerCase().includes(searchTerm) ||
                    song.year.toString().includes(searchTerm)
                );
                displaySongs(filteredSongs);
            });

            // Initialize
            document.getElementById('addSongForm').addEventListener('submit', addSong);
            loadSongs();
        </script>
    </body>
    </html>
    '''
    return dashboard_html

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
