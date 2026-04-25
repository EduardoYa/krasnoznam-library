from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
import sqlite3, os, uuid, json, re
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "library-secret-2026")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME  = os.path.join(BASE_DIR, "library.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_IMG_EXT = {"png","jpg","jpeg","gif","webp"}
ALLOWED_VID_EXT = {"mp4","webm"}
ALLOWED_EXT = ALLOWED_IMG_EXT | ALLOWED_VID_EXT
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "library2026")
UTC5 = timezone(timedelta(hours=5))

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed(filename, file_type="any"):
    if "." not in filename:
        return False
    ext = filename.rsplit(".",1)[1].lower()
    if file_type == "image":
        return ext in ALLOWED_IMG_EXT
    elif file_type == "video":
        return ext in ALLOWED_VID_EXT
    return ext in ALLOWED_EXT

def extract_youtube_id(url):
    """Извлечь YouTube ID из различных форматов URL"""
    patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]+)',
        r'(?:https?://)?(?:www\.)?youtu\.be/([a-zA-Z0-9_-]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def extract_vimeo_id(url):
    """Извлечь Vimeo ID из URL"""
    pattern = r'(?:https?://)?(?:www\.)?vimeo\.com/(\d+)'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def get_video_type_and_id(url):
    """Определить тип видео и получить ID для встраивания"""
    youtube_id = extract_youtube_id(url)
    if youtube_id:
        return ('youtube', youtube_id)
    
    vimeo_id = extract_vimeo_id(url)
    if vimeo_id:
        return ('vimeo', vimeo_id)
    
    return (None, None)

def now5():
    return datetime.now(UTC5)

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        # Основная таблица новостей
        conn.execute("""CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title_ru TEXT, title_kz TEXT,
            body_ru TEXT, body_kz TEXT,
            created_at TEXT, pinned INTEGER DEFAULT 0
        )""")
        
        # Таблица для изображений (до 10 на новость)
        conn.execute("""CREATE TABLE IF NOT EXISTS news_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER NOT NULL,
            image_url TEXT NOT NULL,
            image_type TEXT DEFAULT 'upload',
            position INTEGER DEFAULT 0,
            FOREIGN KEY(news_id) REFERENCES news(id) ON DELETE CASCADE
        )""")
        
        # Таблица для видео (до 5 на новость)
        conn.execute("""CREATE TABLE IF NOT EXISTS news_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER NOT NULL,
            video_url TEXT NOT NULL,
            video_type TEXT DEFAULT 'upload',
            video_id TEXT,
            embed_type TEXT,
            position INTEGER DEFAULT 0,
            FOREIGN KEY(news_id) REFERENCES news(id) ON DELETE CASCADE
        )""")
        
        # Проверяем есть ли уже новости, если нет - добавляем примеры
        if conn.execute("SELECT count(*) FROM news").fetchone()[0] == 0:
            conn.executemany("""INSERT INTO news
                (title_ru,title_kz,body_ru,body_kz,created_at) VALUES (?,?,?,?,?)""", [
                ("Добро пожаловать на наш сайт!","Сайтымызға қош келдіңіз!",
                 "Сельская библиотека села Краснознаменное открыла свой официальный сайт. Здесь вы найдёте актуальные новости, график работы и информацию о наших услугах.",
                 "Краснознаменное ауылының ауылдық кітапханасы өзінің ресми сайтын ашты. Мұнда сіз өзекті жаңалықтарды, жұмыс кестесін және қызметтеріміз туралы ақпаратты таба аласыз.",
                 now5().strftime("%Y-%m-%d %H:%M")),
                ("Праздник Наурыз","Наурыз мерекесі",
                 "Поздравляем всех жителей с праздником Наурыз! Пусть этот день принесёт радость, мир и процветание каждому дому.",
                 "Барлық тұрғындарды Наурыз мерекесімен құттықтаймыз! Бұл күн әр үйге қуаныш, бейбітшілік және молшылық әкелсін.",
                 now5().strftime("%Y-%m-%d %H:%M")),
            ])

init_db()

def require_admin(f):
    from functools import wraps
    @wraps(f)
    def dec(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return dec

@app.route("/login", methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_panel"))
        error = True
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

def get_news_with_media(news_id=None):
    """Получить новости с изображениями и видео"""
    with get_db() as conn:
        if news_id:
            news_list = conn.execute("SELECT * FROM news WHERE id=?", (news_id,)).fetchall()
        else:
            news_list = conn.execute("SELECT * FROM news ORDER BY pinned DESC, id DESC").fetchall()
        
        for item in news_list:
            images = conn.execute(
                "SELECT * FROM news_images WHERE news_id=? ORDER BY position", 
                (item['id'],)
            ).fetchall()
            videos = conn.execute(
                "SELECT * FROM news_videos WHERE news_id=? ORDER BY position", 
                (item['id'],)
            ).fetchall()
            item['images'] = list(images) if images else []
            item['videos'] = list(videos) if videos else []
    
    return news_list

@app.route("/")
def index():
    news = get_news_with_media()
    news = [dict(n) for n in news[:6]]
    return render_template("index.html", news=news)

@app.route("/news")
def news_page():
    news = get_news_with_media()
    news = [dict(n) for n in news]
    return render_template("news.html", news=news)

@app.route("/news/<int:nid>")
def news_detail(nid):
    news_list = get_news_with_media(nid)
    if not news_list:
        return redirect(url_for("news_page"))
    item = dict(news_list[0])
    return render_template("news_detail.html", item=item)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/schedule")
def schedule():
    return render_template("schedule.html")

@app.route("/admin")
@require_admin
def admin_panel():
    news = get_news_with_media()
    news = [dict(n) for n in news]
    return render_template("admin.html", news=news)

@app.route("/admin/add", methods=["GET","POST"])
@require_admin
def admin_add():
    if request.method == "POST":
        title_ru = request.form.get("title_ru","").strip()
        title_kz = request.form.get("title_kz","").strip()
        body_ru  = request.form.get("body_ru","").strip()
        body_kz  = request.form.get("body_kz","").strip()
        pinned   = 1 if request.form.get("pinned") else 0
        
        with get_db() as conn:
            cursor = conn.execute("""INSERT INTO news (title_ru,title_kz,body_ru,body_kz,created_at,pinned)
                VALUES (?,?,?,?,?,?)""",
                (title_ru, title_kz, body_ru, body_kz, now5().strftime("%Y-%m-%d %H:%M"), pinned))
            news_id = cursor.lastrowid
            
            # ===== ОБРАБОТКА ИЗОБРАЖЕНИЙ =====
            # 1. Загруженные файлы изображений
            image_files = request.files.getlist("image_files[]")
            position = 0
            for file in image_files:
                if file and file.filename and allowed(file.filename, "image"):
                    ext = file.filename.rsplit(".",1)[1].lower()
                    fname = f"{uuid.uuid4().hex}.{ext}"
                    file.save(os.path.join(UPLOAD_FOLDER, fname))
                    conn.execute(
                        "INSERT INTO news_images (news_id, image_url, image_type, position) VALUES (?,?,?,?)",
                        (news_id, fname, 'upload', position)
                    )
                    position += 1
            
            # 2. URL изображений
            image_urls_str = request.form.get("image_urls", "").strip()
            if image_urls_str:
                image_urls = [url.strip() for url in image_urls_str.split('\n') if url.strip()]
                for url in image_urls[:10-position]:  # Максимум 10 изображений
                    conn.execute(
                        "INSERT INTO news_images (news_id, image_url, image_type, position) VALUES (?,?,?,?)",
                        (news_id, url, 'url', position)
                    )
                    position += 1
            
            # ===== ОБРАБОТКА ВИДЕО =====
            # 1. Загруженные файлы видео
            video_files = request.files.getlist("video_files[]")
            position = 0
            for file in video_files:
                if file and file.filename and allowed(file.filename, "video"):
                    ext = file.filename.rsplit(".",1)[1].lower()
                    fname = f"{uuid.uuid4().hex}.{ext}"
                    file.save(os.path.join(UPLOAD_FOLDER, fname))
                    conn.execute(
                        "INSERT INTO news_videos (news_id, video_url, video_type, position) VALUES (?,?,?,?)",
                        (news_id, fname, 'upload', position)
                    )
                    position += 1
            
            # 2. URL видео
            video_urls_str = request.form.get("video_urls", "").strip()
            if video_urls_str:
                video_urls = [url.strip() for url in video_urls_str.split('\n') if url.strip()]
                for url in video_urls[:5-position]:  # Максимум 5 видео
                    embed_type, video_id = get_video_type_and_id(url)
                    conn.execute(
                        "INSERT INTO news_videos (news_id, video_url, video_type, embed_type, video_id, position) VALUES (?,?,?,?,?,?)",
                        (news_id, url, 'url', embed_type, video_id, position)
                    )
                    position += 1
        
        return redirect(url_for("admin_panel"))
    return render_template("admin_add.html")

@app.route("/admin/edit/<int:nid>", methods=["GET","POST"])
@require_admin
def admin_edit(nid):
    with get_db() as conn:
        item = conn.execute("SELECT * FROM news WHERE id=?", (nid,)).fetchone()
    
    if not item:
        return redirect(url_for("admin_panel"))
    
    if request.method == "POST":
        title_ru = request.form.get("title_ru","").strip()
        title_kz = request.form.get("title_kz","").strip()
        body_ru  = request.form.get("body_ru","").strip()
        body_kz  = request.form.get("body_kz","").strip()
        pinned   = 1 if request.form.get("pinned") else 0
        
        with get_db() as conn:
            conn.execute("""UPDATE news SET title_ru=?,title_kz=?,body_ru=?,body_kz=?,pinned=? WHERE id=?""",
                (title_ru,title_kz,body_ru,body_kz,pinned,nid))
            
            # Удаляем старые изображения
            conn.execute("DELETE FROM news_images WHERE news_id=?", (nid,))
            
            # Добавляем новые изображения
            image_files = request.files.getlist("image_files[]")
            position = 0
            for file in image_files:
                if file and file.filename and allowed(file.filename, "image"):
                    ext = file.filename.rsplit(".",1)[1].lower()
                    fname = f"{uuid.uuid4().hex}.{ext}"
                    file.save(os.path.join(UPLOAD_FOLDER, fname))
                    conn.execute(
                        "INSERT INTO news_images (news_id, image_url, image_type, position) VALUES (?,?,?,?)",
                        (nid, fname, 'upload', position)
                    )
                    position += 1
            
            image_urls_str = request.form.get("image_urls", "").strip()
            if image_urls_str:
                image_urls = [url.strip() for url in image_urls_str.split('\n') if url.strip()]
                for url in image_urls[:10-position]:
                    conn.execute(
                        "INSERT INTO news_images (news_id, image_url, image_type, position) VALUES (?,?,?,?)",
                        (nid, url, 'url', position)
                    )
                    position += 1
            
            # Удаляем старые видео
            conn.execute("DELETE FROM news_videos WHERE news_id=?", (nid,))
            
            # Добавляем новые видео
            video_files = request.files.getlist("video_files[]")
            position = 0
            for file in video_files:
                if file and file.filename and allowed(file.filename, "video"):
                    ext = file.filename.rsplit(".",1)[1].lower()
                    fname = f"{uuid.uuid4().hex}.{ext}"
                    file.save(os.path.join(UPLOAD_FOLDER, fname))
                    conn.execute(
                        "INSERT INTO news_videos (news_id, video_url, video_type, position) VALUES (?,?,?,?)",
                        (nid, fname, 'upload', position)
                    )
                    position += 1
            
            video_urls_str = request.form.get("video_urls", "").strip()
            if video_urls_str:
                video_urls = [url.strip() for url in video_urls_str.split('\n') if url.strip()]
                for url in video_urls[:5-position]:
                    embed_type, video_id = get_video_type_and_id(url)
                    conn.execute(
                        "INSERT INTO news_videos (news_id, video_url, video_type, embed_type, video_id, position) VALUES (?,?,?,?,?,?)",
                        (nid, url, 'url', embed_type, video_id, position)
                    )
                    position += 1
        
        return redirect(url_for("admin_panel"))
    
    item = dict(item)
    with get_db() as conn:
        images = conn.execute("SELECT * FROM news_images WHERE news_id=? ORDER BY position", (nid,)).fetchall()
        videos = conn.execute("SELECT * FROM news_videos WHERE news_id=? ORDER BY position", (nid,)).fetchall()
        item['images'] = [dict(i) for i in images]
        item['videos'] = [dict(v) for v in videos]
    
    return render_template("admin_edit.html", item=item)

@app.route("/admin/delete/<int:nid>", methods=["POST"])
@require_admin
def admin_delete(nid):
    with get_db() as conn:
        conn.execute("DELETE FROM news WHERE id=?", (nid,))
    return redirect(url_for("admin_panel"))

@app.route("/health")
def health():
    """Проверка здоровья приложения для Railway"""
    return {"status": "healthy"}, 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
