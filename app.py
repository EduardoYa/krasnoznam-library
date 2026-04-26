from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
import sqlite3, os, uuid, json, re
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "library-secret-2026")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = "/data"
DB_NAME  = os.path.join(DATA_DIR, "library.db")
UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads")
ALLOWED_IMG = {"png","jpg","jpeg","gif","webp"}
ALLOWED_VID = {"mp4","webm","mov","avi"}
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "library2026")
UTC5 = timezone(timedelta(hours=5))

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed(filename, ftype="img"):
    if "." not in filename:
        return False
    ext = filename.rsplit(".",1)[1].lower()
    if ftype == "img":
        return ext in ALLOWED_IMG
    elif ftype == "vid":
        return ext in ALLOWED_VID
    return False

def is_valid_video_url(url):
    if "youtube.com" in url or "youtu.be" in url or "vimeo.com" in url:
        return True
    return False

def now5():
    return datetime.now(UTC5)

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        # Проверяем существует ли таблица
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='news'"
        )
        exists = cursor.fetchone()
        
        if not exists:
            # Создаем новую таблицу
            conn.execute("""CREATE TABLE news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title_ru TEXT, title_kz TEXT,
                body_ru TEXT, body_kz TEXT,
                images TEXT DEFAULT '[]',
                videos TEXT DEFAULT '[]',
                created_at TEXT, pinned INTEGER DEFAULT 0
            )""")
            
            # Добавляем примеры
            conn.executemany("""INSERT INTO news
                (title_ru,title_kz,body_ru,body_kz,images,videos,created_at) 
                VALUES (?,?,?,?,?,?,?)""", [
                ("Добро пожаловать на наш сайт!","Сайтымызға қош келдіңіз!",
                 "<p>Сельская библиотека села Краснознаменное открыла свой официальный сайт.</p>",
                 "<p>Краснознаменное ауылының ауылдық кітапханасы өзінің ресми сайтын ашты.</p>",
                 "[]", "[]", now5().strftime("%Y-%m-%d %H:%M")),
                ("Праздник Наурыз","Наурыз мерекесі",
                 "<p>Поздравляем всех жителей с праздником Наурыз!</p>",
                 "<p>Барлық тұрғындарды Наурыз мерекесімен құттықтаймыз!</p>",
                 "[]", "[]", now5().strftime("%Y-%m-%d %H:%M")),
            ])
        else:
            # Проверяем нужна ли миграция (если есть старое поле 'image')
            cursor = conn.execute("PRAGMA table_info(news)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'image' in columns and 'images' not in columns:
                # Нужна миграция - добавляем новые колонки
                try:
                    conn.execute("ALTER TABLE news ADD COLUMN images TEXT DEFAULT '[]'")
                    conn.execute("ALTER TABLE news ADD COLUMN videos TEXT DEFAULT '[]'")
                    
                    # Мигрируем старые картинки
                    old_news = conn.execute("SELECT id, image FROM news WHERE image IS NOT NULL").fetchall()
                    for row in old_news:
                        images = [{"type": "upload", "url": row['image']}] if row['image'] else []
                        conn.execute(
                            "UPDATE news SET images = ? WHERE id = ?",
                            (json.dumps(images), row['id'])
                        )
                except:
                    pass
            elif 'images' not in columns:
                # Добавляем новые колонки если их нет
                try:
                    conn.execute("ALTER TABLE news ADD COLUMN images TEXT DEFAULT '[]'")
                except:
                    pass
                try:
                    conn.execute("ALTER TABLE news ADD COLUMN videos TEXT DEFAULT '[]'")
                except:
                    pass

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

@app.route("/")
def index():
    with get_db() as conn:
        news = conn.execute("SELECT * FROM news ORDER BY pinned DESC, id DESC LIMIT 6").fetchall()
    return render_template("index.html", news=news)

@app.route("/news")
def news_page():
    with get_db() as conn:
        news = conn.execute("SELECT * FROM news ORDER BY pinned DESC, id DESC").fetchall()
    return render_template("news.html", news=news)

@app.route("/news/<int:nid>")
def news_detail(nid):
    with get_db() as conn:
        item = conn.execute("SELECT * FROM news WHERE id=?", (nid,)).fetchone()
    if not item:
        return redirect(url_for("news_page"))
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
    with get_db() as conn:
        news = conn.execute("SELECT * FROM news ORDER BY id DESC").fetchall()
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
        
        images = []
        # Загруженные изображения
        image_files = request.files.getlist("images[]")
        for file in image_files:
            if file and file.filename and allowed(file.filename, "img"):
                try:
                    ext = file.filename.rsplit(".",1)[1].lower()
                    fname = f"{uuid.uuid4().hex}.{ext}"
                    file.save(os.path.join(UPLOAD_FOLDER, fname))
                    images.append({"type": "upload", "url": fname})
                except:
                    pass
        
        # URL изображений
        image_urls = request.form.get("image_urls", "").strip().split('\n')
        for url in image_urls:
            url = url.strip()
            if url and url.startswith("http"):
                images.append({"type": "url", "url": url})
        
        videos = []
        # Загруженные видео
        video_files = request.files.getlist("videos[]")
        for file in video_files:
            if file and file.filename and allowed(file.filename, "vid"):
                try:
                    ext = file.filename.rsplit(".",1)[1].lower()
                    fname = f"{uuid.uuid4().hex}.{ext}"
                    file.save(os.path.join(UPLOAD_FOLDER, fname))
                    videos.append({"type": "upload", "url": fname})
                except:
                    pass
        
        # URL видео
        video_urls = request.form.get("video_urls", "").strip().split('\n')
        for url in video_urls:
            url = url.strip()
            if url and is_valid_video_url(url):
                videos.append({"type": "url", "url": url})
        
        try:
            with get_db() as conn:
                conn.execute("""INSERT INTO news 
                    (title_ru,title_kz,body_ru,body_kz,images,videos,created_at,pinned)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (title_ru, title_kz, body_ru, body_kz, 
                     json.dumps(images), json.dumps(videos),
                     now5().strftime("%Y-%m-%d %H:%M"), pinned))
            return redirect(url_for("admin_panel"))
        except Exception as e:
            return f"Ошибка при сохранении: {str(e)}", 500
    
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
        
        images = []
        image_files = request.files.getlist("images[]")
        for file in image_files:
            if file and file.filename and allowed(file.filename, "img"):
                try:
                    ext = file.filename.rsplit(".",1)[1].lower()
                    fname = f"{uuid.uuid4().hex}.{ext}"
                    file.save(os.path.join(UPLOAD_FOLDER, fname))
                    images.append({"type": "upload", "url": fname})
                except:
                    pass
        
        image_urls = request.form.get("image_urls", "").strip().split('\n')
        for url in image_urls:
            url = url.strip()
            if url and url.startswith("http"):
                images.append({"type": "url", "url": url})
        
        videos = []
        video_files = request.files.getlist("videos[]")
        for file in video_files:
            if file and file.filename and allowed(file.filename, "vid"):
                try:
                    ext = file.filename.rsplit(".",1)[1].lower()
                    fname = f"{uuid.uuid4().hex}.{ext}"
                    file.save(os.path.join(UPLOAD_FOLDER, fname))
                    videos.append({"type": "upload", "url": fname})
                except:
                    pass
        
        video_urls = request.form.get("video_urls", "").strip().split('\n')
        for url in video_urls:
            url = url.strip()
            if url and is_valid_video_url(url):
                videos.append({"type": "url", "url": url})
        
        try:
            with get_db() as conn:
                conn.execute("""UPDATE news 
                    SET title_ru=?,title_kz=?,body_ru=?,body_kz=?,images=?,videos=?,pinned=? 
                    WHERE id=?""",
                    (title_ru, title_kz, body_ru, body_kz, 
                     json.dumps(images), json.dumps(videos), pinned, nid))
            return redirect(url_for("admin_panel"))
        except Exception as e:
            return f"Ошибка при обновлении: {str(e)}", 500
    
    item_dict = dict(item)
    try:
        item_dict['images'] = json.loads(item['images'] or '[]') if item['images'] else []
        item_dict['videos'] = json.loads(item['videos'] or '[]') if item['videos'] else []
    except:
        item_dict['images'] = []
        item_dict['videos'] = []
    
    return render_template("admin_edit.html", item=item_dict)

@app.route("/admin/delete/<int:nid>", methods=["POST"])
@require_admin
def admin_delete(nid):
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM news WHERE id=?", (nid,))
        return redirect(url_for("admin_panel"))
    except:
        return redirect(url_for("admin_panel"))

@app.route("/upload/<path:filename>")
def download_file(filename):
    from flask import send_from_directory
    try:
        return send_from_directory(UPLOAD_FOLDER, filename)
    except:
        return "Файл не найден", 404

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
