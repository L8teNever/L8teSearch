import shutil
import time
from flask import Flask, render_template, request, jsonify, Response
import requests
from bs4 import BeautifulSoup
import concurrent.futures
import re
import json
import os
from datetime import datetime
from urllib.parse import quote
from collections import Counter
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['APP_NAME'] = 'L8teSearch'

UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DATA_FOLDER = 'data'
os.makedirs(DATA_FOLDER, exist_ok=True)
PROJECTS_FILE = os.path.join(DATA_FOLDER, 'projects.json')

def load_projects_from_disk():
    if os.path.exists(PROJECTS_FILE):
        with open(PROJECTS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_projects_to_disk(projects):
    if os.path.exists(PROJECTS_FILE):
        shutil.copy2(PROJECTS_FILE, PROJECTS_FILE + ".bak")
    with open(PROJECTS_FILE, 'w') as f:
        json.dump(projects, f, indent=4)

def search_in_url(url, keywords):
    try:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for script in soup(["script", "style"]):
            script.extract()
            
        text = soup.get_text()
        
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        results = []
        for keyword in keywords:
            matches = re.finditer(re.escape(keyword), text, re.IGNORECASE)
            
            snippets = []
            for match in matches:
                start = max(0, match.start() - 60)
                end = min(len(text), match.end() + 60)
                snippet = text[start:end].replace('\n', ' ')
                snippets.append(f"...{snippet}...")
                if len(snippets) >= 5:
                    break
            
            if snippets:
                results.append({
                    'keyword': keyword,
                    'count': len(list(re.finditer(re.escape(keyword), text, re.IGNORECASE))),
                    'snippets': snippets
                })
        
        return {
            'url': url,
            'status': 'success',
            'title': soup.title.string if soup.title else url,
            'findings': results
        }
    except Exception as e:
        return {
            'url': url,
            'status': 'error',
            'message': str(e)
        }

@app.route('/')
@app.route('/dashboard')
@app.route('/library')
@app.route('/notes')
@app.route('/notes/<path:note_id>')
@app.route('/mindmap')
@app.route('/reader')
def index(note_id=None):
    return render_template('index.html')


@app.route('/search', methods=['POST'])
def search():
    data = request.json
    urls = data.get('urls', [])
    keywords = data.get('keywords', [])
    
    if not urls or not keywords:
        return jsonify({'error': 'Please provide both URLs and keywords'}), 400
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_url = {executor.submit(search_in_url, url, keywords): url for url in urls}
        results = [future.result() for future in concurrent.futures.as_completed(future_to_url)]
        
    return jsonify(results)

@app.route('/projects', methods=['GET'])
def get_projects():
    return jsonify(load_projects_from_disk())

@app.route('/projects', methods=['POST'])
def save_project():
    data = request.json
    name = data.get('name')
    if not name:
        return jsonify({'error': 'Project name is required'}), 400
    
    projects = load_projects_from_disk()
    if name not in projects:
        projects[name] = {
            'urls': data.get('urls', []),
            'keywords': data.get('keywords', ''),
            'notes': [],
            'mindmap': data.get('mindmap', [])
        }
    else:
        if 'urls' in data: projects[name]['urls'] = data['urls']
        if 'keywords' in data: projects[name]['keywords'] = data['keywords']
        if 'mindmap' in data: projects[name]['mindmap'] = data['mindmap']
    
    save_projects_to_disk(projects)
    return jsonify({'status': 'success'})

@app.route('/add_url', methods=['POST'])
def add_url_to_project():
    data = request.json
    project_name = data.get('project')
    new_url = data.get('url')
    
    if not project_name or not new_url:
        return jsonify({'error': 'Missing data'}), 400
        
    projects = load_projects_from_disk()
    if project_name in projects:
        if new_url not in projects[project_name]['urls']:
            projects[project_name]['urls'].append(new_url)
            save_projects_to_disk(projects)
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Project not found'}), 404


@app.route('/projects/<name>', methods=['DELETE'])
def delete_project(name):
    projects = load_projects_from_disk()
    if name in projects:
        del projects[name]
        save_projects_to_disk(projects)
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Project not found'}), 404

@app.route('/add_note', methods=['POST'])
def add_note():
    data = request.json
    project_name = data.get('project')
    text = data.get('text')
    url = data.get('url')
    title = data.get('title')
    
    projects = load_projects_from_disk()
    if project_name in projects:
        if 'notes' not in projects[project_name]:
            projects[project_name]['notes'] = []
            
        new_note = {
            'id': str(datetime.now().timestamp()),
            'text': text,
            'url': url,
            'title': title,
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'category': 'Unsortiert'  # Default category
        }
        projects[project_name]['notes'].append(new_note)
        save_projects_to_disk(projects)
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Project not found'}), 404

@app.route('/delete_note', methods=['POST'])
def delete_note():
    data = request.json
    project_name = data.get('project')
    note_id = data.get('id')
    
    projects = load_projects_from_disk()
    if project_name in projects and 'notes' in projects[project_name]:
        projects[project_name]['notes'] = [n for n in projects[project_name]['notes'] if n.get('id') != note_id]
        save_projects_to_disk(projects)
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Note not found'}), 404

@app.route('/edit_note', methods=['POST'])
def edit_note():
    data = request.json
    project_name = data.get('project')
    note_id = data.get('id')
    new_text = data.get('text')
    new_category = data.get('category')
    new_tags = data.get('tags')
    
    projects = load_projects_from_disk()
    if project_name in projects and 'notes' in projects[project_name]:
        for note in projects[project_name]['notes']:
            if note.get('id') == note_id:
                if new_text is not None:
                    note['text'] = new_text
                if new_category is not None:
                    note['category'] = new_category
                if new_tags is not None:
                    note['tags'] = new_tags
                save_projects_to_disk(projects)
                return jsonify({'status': 'success'})

    return jsonify({'error': 'Note not found'}), 404

@app.route('/move_note', methods=['POST'])
def move_note():
    data = request.json
    project_name = data.get('project')
    note_id = data.get('id')
    direction = data.get('direction') # 'up' or 'down'

    projects = load_projects_from_disk()
    if project_name in projects and 'notes' in projects[project_name]:
        notes = projects[project_name]['notes']
        index = next((i for i, n in enumerate(notes) if n.get('id') == note_id), None)
        
        if index is not None:
            if direction == 'up' and index > 0:
                notes[index], notes[index-1] = notes[index-1], notes[index]
                save_projects_to_disk(projects)
                return jsonify({'status': 'success'})
            elif direction == 'down' and index < len(notes) - 1:
                notes[index], notes[index+1] = notes[index+1], notes[index]
                save_projects_to_disk(projects)
                return jsonify({'status': 'success'})
                
    return jsonify({'status': 'no_change'})

@app.route('/auto_group', methods=['POST'])
def auto_group_notes():
    data = request.json
    project_name = data.get('project')
    
    projects = load_projects_from_disk()
    if project_name not in projects or 'notes' not in projects[project_name]:
        return jsonify({'error': 'Project empty'}), 404

    notes = projects[project_name]['notes']
    if not notes:
        return jsonify({'status': 'no_notes'})

    # 1. Simple Keyword Extraction
    stop_words = {
        'und', 'oder', 'aber', 'den', 'die', 'das', 'der', 'dem', 'des', 'ein', 'eine', 'einer', 
        'in', 'im', 'auf', 'aus', 'von', 'mit', 'für', 'bei', 'zum', 'zur', 'dass', 'ist', 'sind', 
        'war', 'wird', 'werden', 'nicht', 'auch', 'sich', 'als', 'wie', 'es', 'an', 'zu', 'hat', 
        'heute', 'dies', 'diese', 'jenes', 'the', 'and', 'or', 'of', 'to', 'in', 'a', 'is', 'for'
    }
    
    # Collect all words to find common themes
    all_words = []
    for note in notes:
        # Clean text: lowercase, remove special chars
        clean_text = re.sub(r'[^\w\s]', '', (note.get('text', '') + ' ' + note.get('title', '')).lower())
        words = [w for w in clean_text.split() if len(w) > 4 and w not in stop_words]
        all_words.extend(words)
    
    # Find words that appear frequently (potential topics)
    word_counts = Counter(all_words)
    # Filter for words that appear in at least 2 different notes would be better, 
    # but strictly counting occurrences is a good proxy for "Topic"
    common_topics = [word for word, count in word_counts.most_common(10) if count > 1]
    
    changes = 0
    for note in notes:
        # Only regroup 'Unsortiert' to avoid messing up manual work? 
        # User asked for "smart grouping", implies doing the job for them. 
        # Let's be aggressive but respect existing proper categories if possible.
        # Actually, let's just categorize everything that matches a hot topic.
        
        current_cat = note.get('category', 'Unsortiert')
        
        # Check if note matches a topic
        note_content = (note.get('text', '') + ' ' + note.get('title', '')).lower()
        
        best_topic = None
        for topic in common_topics:
            if topic in note_content:
                best_topic = topic
                break # Assign to the most frequent/important topic found first
        
        if best_topic:
            # Capitalize topic for display
            new_cat = f"Thema: {best_topic.capitalize()}"
            if current_cat != new_cat:
                note['category'] = new_cat
                changes += 1
        elif current_cat == 'Unsortiert':
            # If no topic found, maybe keep Unsortiert
            pass

    if changes > 0:
        save_projects_to_disk(projects)
        return jsonify({'status': 'success', 'changes': changes})
    else:
        return jsonify({'status': 'no_changes'})

@app.route('/upload_image', methods=['POST'])
def upload_image():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    project_name = request.form.get('project')
    
    if file.filename == '' or not project_name:
        return jsonify({'error': 'Missing data'}), 400
        
    if file:
        filename = secure_filename(f"{int(datetime.now().timestamp())}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        projects = load_projects_from_disk()
        if project_name in projects:
            if 'notes' not in projects[project_name]:
                projects[project_name]['notes'] = []
                
            projects[project_name]['notes'].append({
                'id': str(datetime.now().timestamp()),
                'text': "Bild hochgeladen",
                'url': f"/static/uploads/{filename}",
                'title': file.filename,
                'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'category': 'Bilder',
                'type': 'image'
            })
            save_projects_to_disk(projects)
            return jsonify({'status': 'success'})
            
    return jsonify({'error': 'Upload failed'}), 500

@app.route('/add_image_note', methods=['POST'])
def add_image_note():
    data = request.json
    project_name = data.get('project')
    image_src = data.get('src')
    page_url = data.get('pageUrl')
    
    projects = load_projects_from_disk()
    if project_name in projects:
        if 'notes' not in projects[project_name]:
            projects[project_name]['notes'] = []
            
        projects[project_name]['notes'].append({
            'id': str(datetime.now().timestamp()),
            'text': "Bild aus dem Web",
            'url': image_src,
            'title': "Web Image",
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'category': 'Bilder',
            'type': 'image',
            'source_page': page_url
        })
        save_projects_to_disk(projects)
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Project not found'}), 404

@app.route('/note_editor')
def note_editor_view():
    project_name = request.args.get('project')
    note_id = request.args.get('id')
    
    if not project_name or not note_id:
        return "Missing parameters", 400
        
    projects = load_projects_from_disk()
    if project_name not in projects:
        return "Project not found", 404
        
    target_note = None
    for note in projects[project_name].get('notes', []):
        if note.get('id') == note_id:
            target_note = note
            break
            
    if not target_note:
        return "Note not found", 404
        
    return render_template('note_editor.html', project=project_name, note=target_note)

@app.route('/export/<name>', methods=['GET'])
def export_project(name):
    projects = load_projects_from_disk()
    if name not in projects:
        return "Project not found", 404
        
    project = projects[name]
    output = f"# Projekt: {name}\n\n"
    output += f"Exportiert am: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
    
    output += "## 📚 Quellen / URLs\n"
    for url in project.get('urls', []):
        output += f"- {url}\n"
    
    output += "\n## 📝 Notizen\n"
    for note in project.get('notes', []):
        output += f"### {note.get('title', 'Quelle')}\n"
        output += f"> \"{note.get('text')}\"\n\n"
        output += f"*Quelle: {note.get('url')} ({note.get('date')})*\n\n---\n\n"

    output += "\n## 🎓 Literaturverzeichnis / Quellen\n"
    seen_urls = set()
    for note in project.get('notes', []):
        url = note.get('url')
        if url and url not in seen_urls:
            seen_urls.add(url)
            title = note.get('title', 'Ohne Titel')
            date = note.get('date', 'unbekannt')
            output += f"- {title}. Verfügbar unter: {url} (Abgerufen am: {date})\n"
            
    # Also add urls that might strictly be in 'urls' list but have no notes yet
    for url in project.get('urls', []):
         if url not in seen_urls:
             seen_urls.add(url)
             output += f"- Verfügbar unter: {url} (Gespeichert im Projekt)\n"

    return Response(
        output,
        mimetype="text/markdown",
        headers={"Content-disposition": f"attachment; filename={name}_export.md"}
    )

@app.route('/proxy')
def proxy():
    url = request.args.get('url')
    keywords = request.args.get('keywords', '').split(',')
    project_name = request.args.get('project', '')
    reader_mode = request.args.get('reader', 'false')
    
    if not url:
        return "No URL provided", 400

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
        }
        response = requests.get(url, headers=headers, timeout=8, allow_redirects=True)
        response.raise_for_status()
        
        projects = load_projects_from_disk()
        project_urls = projects.get(project_name, {}).get('urls', [])
        
        # Reader Mode Processing
        content = response.text
        if reader_mode == 'true':
            try:
                soup = BeautifulSoup(content, 'html.parser')
                # Strip clutter
                for tag in soup(['nav', 'header', 'footer', 'aside', 'script', 'style', 'iframe', 'noscript', 'form']):
                    tag.decompose()
                
                # Unwrap main content to ensure visibility if container was hidden
                body = soup.find('body')
                if body:
                    # Very simple text extraction/cleaning
                    # In a real reader mode we'd algorithmically find the article, 
                    # but here we just clean the body
                    for tag in body.find_all(True):
                        del tag['class']
                        del tag['style']
                    
                    content = str(body)
                    # Add simple readable style
                    content = f"""
                    <div style="max-width: 800px; margin: 0 auto; padding: 40px; font-family: 'Inter', sans-serif; line-height: 1.6; font-size: 18px; color: #333; background: #fff;">
                        {content}
                    </div>
                    """
            except Exception as e:
                print(f"Reader mode failed: {e}")

        # Sidebar & Navigation Logic
        reader_btn_text = "📖 Reader Modus: AN" if reader_mode == 'true' else "👁️ Reader Modus: AUS"
        new_reader_state = 'false' if reader_mode == 'true' else 'true'
        
        current_index = -1
        try:
             current_index = project_urls.index(url)
        except: pass
        
        prev_url = project_urls[current_index - 1] if current_index > 0 else None
        next_url = project_urls[current_index + 1] if current_index < len(project_urls) - 1 else None

        safe_keywords = quote(",".join(keywords))
        safe_project = quote(project_name)

        # Injection for Selection Bar and Highlight Bar inside the iframe
        injection = f"""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;800&display=swap');
            
            .custom-highlight {{
                background-color: #ffeb3b !important;
                color: #000 !important;
                padding: 2px 0;
                box-shadow: 0 0 5px rgba(0,0,0,0.3);
                border-radius: 2px;
                font-weight: bold;
                display: inline;
            }}

            body {{ 
                margin: 0 !important; 
                width: 100% !important;
                position: relative;
            }}
        </style>

        <script>
            let selectedText = '';
            document.addEventListener('mouseup', function() {{
                const selection = window.getSelection().toString().trim();
                if (selection.length > 0) {{
                    selectedText = selection;
                    window.parent.postMessage({{ action: 'textSelected', hasSelection: true }}, '*');
                }} else {{
                    window.parent.postMessage({{ action: 'textSelected', hasSelection: false }}, '*');
                }}
            }});

            // Listen for save trigger from parent header
            window.addEventListener('message', function(event) {{
                if (event.data.action === 'triggerSave') {{
                    const projectName = "{project_name}";
                    const currentUrl = "{url}";
                    
                    if (!selectedText) return;

                    fetch('/add_note', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{
                            project: projectName,
                            text: selectedText,
                            url: currentUrl,
                            title: document.title
                        }})
                    }}).then(r => r.json()).then(data => {{
                        if (data.status === 'success') {{
                            window.parent.postMessage({{ action: 'saveDone' }}, '*');
                        }}
                    }});
                }}
            }});

            document.addEventListener('keydown', function(e) {{
                if (e.ctrlKey && e.key === 'Enter') {{
                    window.parent.postMessage({{ action: 'triggerSave' }}, '*');
                }}
            }});
        </script>
        """

        if reader_mode != 'true':
            effective_keywords = [] if 'google.' in url else keywords
            for kw in effective_keywords:
                if not kw or not kw.strip(): continue
                clean_kw = kw.strip()
                pattern = re.compile(f'(?i)(?![^<]*>){re.escape(clean_kw)}')
                content = pattern.sub(f'<mark class="custom-highlight">{clean_kw}</mark>', content)

        base_url = f"{response.url.split('://')[0]}://{response.url.split('://')[1].split('/')[0]}"
        content = content.replace('src="/', f'src="{base_url}/')
        content = content.replace('href="/', f'href="{base_url}/')

        return content + injection

    except Exception as e:
        return f"Error loading page: {str(e)}", 500

@app.route('/stream')
def stream():
    def event_stream():
        last_mtime = 0
        while True:
            if os.path.exists(PROJECTS_FILE):
                try:
                    mtime = os.path.getmtime(PROJECTS_FILE)
                    if mtime > last_mtime:
                        last_mtime = mtime
                        projects = load_projects_from_disk()
                        yield f"data: {json.dumps(projects)}\n\n"
                except OSError:
                    pass
            time.sleep(0.5)
    return Response(event_stream(), mimetype="text/event-stream")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=9999)

