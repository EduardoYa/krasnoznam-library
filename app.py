from flask import Flask, render_template, request, session, redirect, url_for, send_from_directory
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
import sqlite3, os, uuid, json
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

# Создаем папки если их нет
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed(filename, ftype="img"):
    """Проверяет расширение файла"""
    if "." not in filename:
        return False
    ext = filename.rsplit(".",1)[1].lower()
    if ftype == "img":
        return ext in ALLOWED_IMG
    elif ftype == "vid":
        return ext in ALLOWED_VID
    return False

def is_valid_video_url(url):
    """Проверяет является ли URL видео YouTube или Vimeo"""
    return "youtube.com" in url or "youtu.be" in url or "vimeo.com" in url

def now5():
    """Текущее время в UTC+5"""
    return datetime.now(UTC5)

@contextmanager
def get_db():
    """Безопасное подключение к БД"""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[DB ERROR] {e}")
        raise
    finally:
        conn.close()

def init_db():
    """Инициализация БД с правильной структурой"""
    try:
        with get_db() as conn:
            # Проверяем существует ли таблица news
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='news'"
            )
            table_exists = cursor.fetchone()
            
            if not table_exists:
                # СОЗДАЕМ НОВУЮ ТАБЛИЦУ
                conn.execute("""CREATE TABLE IF NOT EXISTS news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title_ru TEXT NOT NULL,
                    title_kz TEXT,
                    body_ru TEXT,
                    body_kz TEXT,
                    images TEXT DEFAULT '[]',
                    videos TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    pinned INTEGER DEFAULT 0
                )""")
                
                # Добавляем начальные примеры
                conn.executemany(
                    """INSERT INTO news 
                    (title_ru, title_kz, body_ru, body_kz, images, videos, created_at) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            "Добро пожаловать на наш сайт!",
                            "Сайтымызға қош келдіңіз!",
                            "Сельская библиотека села Краснознаменное открыла свой официальный сайт.",
                            "Краснознаменное ауылының ауылдық кітапханасы өзінің ресми сайтын ашты.",
                            "[]",
                            "[]",
                            now5().strftime("%Y-%m-%d %H:%M")
                        ),
                        (
                            "Праздник Наурыз",
                            "Наурыз мерекесі",
                            "Поздравляем всех жителей с праздником Наурыз!",
                            "Барлық тұрғындарды Наурыз мерекесімен құттықтаймыз!",
                            "[]",
                            "[]",
                            now5().strftime("%Y-%m-%d %H:%M")
                        )
                    ]
                )
                print("[✓] Таблица создана с примерами")
            else:
                # ТАБЛИЦА УЖЕ СУЩЕСТВУЕТ - ПРОВЕРЯЕМ СТРУКТУРУ
                cursor = conn.execute("PRAGMA table_info(news)")
                columns = {row[1] for row in cursor.fetchall()}
                
                # Добавляем колонки если их нет
                if 'images' not in columns:
                    conn.execute("ALTER TABLE news ADD COLUMN images TEXT DEFAULT '[]'")
                    print("[✓] Добавлена колонка images")
                
                if 'videos' not in columns:
                    conn.execute("ALTER TABLE news ADD COLUMN videos TEXT DEFAULT '[]'")
                    print("[✓] Добавлена колонка videos")
                
                # Если есть старое поле 'image' - мигрируем данные
                if 'image' in columns and 'images' in columns:
                    try:
                        old_news = conn.execute(
                            "SELECT id, image FROM news WHERE image IS NOT NULL AND image != ''"
                        ).fetchall()
                        
                        for row in old_news:
                            old_image = row['image']
                            images = json.dumps([{"type": "upload", "url": old_image}])
                            conn.execute(
                                "UPDATE news SET images = ? WHERE id = ?",
                                (images, row['id'])
                            )
                        
                        if old_news:
                            print(f"[✓] Мигрировано {len(old_news)} старых изображений")
                    except Exception as e:
                        print(f"[!] Ошибка миграции: {e}")
    
    except Exception as e:
        print(f"[ERROR] Инициализация БД: {e}")

init_db()

def require_admin(f):
    """Декоратор проверки админ-сессии"""
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

# ============ ОСНОВНЫЕ МАРШРУТЫ ============

@app.route("/login", methods=["GET", "POST"])
def login():
    """Вход в админ-панель"""
    error = None
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        if password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_panel"))
        error = True
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    """Выход из админ-панели"""
    session.clear()
    return redirect(url_for("index"))

@app.route("/")
def index():
    """Главная страница"""
    try:
        with get_db() as conn:
            news = conn.execute(
                "SELECT * FROM news ORDER BY pinned DESC, id DESC LIMIT 6"
            ).fetchall()
        return render_template("index.html", news=news)
    except Exception as e:
        print(f"[ERROR] index: {e}")
        return "Ошибка при загрузке новостей", 500

@app.route("/news")
def news_page():
    """Страница со всеми новостями"""
    try:
        with get_db() as conn:
            news = conn.execute(
                "SELECT * FROM news ORDER BY pinned DESC, id DESC"
            ).fetchall()
        return render_template("news.html", news=news)
    except Exception as e:
        print(f"[ERROR] news_page: {e}")
        return "Ошибка при загрузке новостей", 500

@app.route("/news/<int:nid>")
def news_detail(nid):
    """Страница одной новости"""
    try:
        with get_db() as conn:
            item = conn.execute("SELECT * FROM news WHERE id=?", (nid,)).fetchone()
        
        if not item:
            return redirect(url_for("news_page"))
        
        return render_template("news_detail.html", item=item)
    except Exception as e:
        print(f"[ERROR] news_detail: {e}")
        return redirect(url_for("news_page"))

@app.route("/about")
def about():
    """О нас"""
    return render_template("about.html")

@app.route("/schedule")
def schedule():
    """График работы"""
    return render_template("schedule.html")

# ============ АДМИН-ПАНЕЛЬ ============

@app.route("/admin")
@require_admin
def admin_panel():
    """Админ-панель со всеми новостями"""
    try:
        with get_db() as conn:
            news = conn.execute("SELECT * FROM news ORDER BY id DESC").fetchall()
        return render_template("admin.html", news=news)
    except Exception as e:
        print(f"[ERROR] admin_panel: {e}")
        return "Ошибка при загрузке панели", 500

@app.route("/admin/add", methods=["GET", "POST"])
@require_admin
def admin_add():
    """Добавление новой новости"""
    if request.method == "POST":
        try:
            # ПОЛУЧАЕМ ТЕКСТ
            title_ru = request.form.get("title_ru", "").strip()
            title_kz = request.form.get("title_kz", "").strip()
            body_ru = request.form.get("body_ru", "").strip()
            body_kz = request.form.get("body_kz", "").strip()
            pinned = 1 if request.form.get("pinned") else 0
            
            # ОБРАБОТКА ИЗОБРАЖЕНИЙ
            images = []
            
            # Загруженные изображения с ПК
            image_files = request.files.getlist("images[]")
            for file in image_files:
                if file and file.filename:
                    if allowed(file.filename, "img"):
                        try:
                            ext = file.filename.rsplit(".", 1)[1].lower()
                            fname = f"{uuid.uuid4().hex}.{ext}"
                            filepath = os.path.join(UPLOAD_FOLDER, fname)
                            file.save(filepath)
                            images.append({"type": "upload", "url": fname})
                            print(f"[✓] Сохранено изображение: {fname}")
                        except Exception as e:
                            print(f"[!] Ошибка сохранения изображения: {e}")
            
            # URL изображений
            image_urls = request.form.get("image_urls", "").strip()
            if image_urls:
                for url in image_urls.split('\n'):
                    url = url.strip()
                    if url and (url.startswith("http://") or url.startswith("https://")):
                        images.append({"type": "url", "url": url})
                        print(f"[✓] Добавлена URL картинка: {url}")
            
            # ОБРАБОТКА ВИДЕО
            videos = []
            
            # Загруженные видео с ПК
            video_files = request.files.getlist("videos[]")
            for file in video_files:
                if file and file.filename:
                    if allowed(file.filename, "vid"):
                        try:
                            ext = file.filename.rsplit(".", 1)[1].lower()
                            fname = f"{uuid.uuid4().hex}.{ext}"
                            filepath = os.path.join(UPLOAD_FOLDER, fname)
                            file.save(filepath)
                            videos.append({"type": "upload", "url": fname})
                            print(f"[✓] Сохранено видео: {fname}")
                        except Exception as e:
                            print(f"[!] Ошибка сохранения видео: {e}")
            
            # URL видео (YouTube, Vimeo)
            video_urls = request.form.get("video_urls", "").strip()
            if video_urls:
                for url in video_urls.split('\n'):
                    url = url.strip()
                    if url and is_valid_video_url(url):
                        videos.append({"type": "url", "url": url})
                        print(f"[✓] Добавлена URL видео: {url}")
            
            # СОХРАНЯЕМ В БД
            with get_db() as conn:
                conn.execute("""INSERT INTO news 
                    (title_ru, title_kz, body_ru, body_kz, images, videos, created_at, pinned)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        title_ru, title_kz, body_ru, body_kz,
                        json.dumps(images), json.dumps(videos),
                        now5().strftime("%Y-%m-%d %H:%M"),
                        pinned
                    ))
            
            print(f"[✓] Новость сохранена: {title_ru}")
            return redirect(url_for("admin_panel"))
        
        except Exception as e:
            print(f"[ERROR] admin_add POST: {e}")
            return f"Ошибка при сохранении: {str(e)}", 500
    
    return render_template("admin_add.html")

@app.route("/admin/edit/<int:nid>", methods=["GET", "POST"])
@require_admin
def admin_edit(nid):
    """Редактирование новости"""
    try:
        with get_db() as conn:
            item = conn.execute("SELECT * FROM news WHERE id=?", (nid,)).fetchone()
        
        if not item:
            return redirect(url_for("admin_panel"))
        
        if request.method == "POST":
            try:
                # ПОЛУЧАЕМ ТЕКСТ
                title_ru = request.form.get("title_ru", "").strip()
                title_kz = request.form.get("title_kz", "").strip()
                body_ru = request.form.get("body_ru", "").strip()
                body_kz = request.form.get("body_kz", "").strip()
                pinned = 1 if request.form.get("pinned") else 0
                
                # ОБРАБОТКА ИЗОБРАЖЕНИЙ (как в add)
                images = []
                image_files = request.files.getlist("images[]")
                for file in image_files:
                    if file and file.filename and allowed(file.filename, "img"):
                        try:
                            ext = file.filename.rsplit(".", 1)[1].lower()
                            fname = f"{uuid.uuid4().hex}.{ext}"
                            file.save(os.path.join(UPLOAD_FOLDER, fname))
                            images.append({"type": "upload", "url": fname})
                        except Exception as e:
                            print(f"[!] Ошибка сохранения изображения: {e}")
                
                image_urls = request.form.get("image_urls", "").strip()
                if image_urls:
                    for url in image_urls.split('\n'):
                        url = url.strip()
                        if url and (url.startswith("http://") or url.startswith("https://")):
                            images.append({"type": "url", "url": url})
                
                # ОБРАБОТКА ВИДЕО (как в add)
                videos = []
                video_files = request.files.getlist("videos[]")
                for file in video_files:
                    if file and file.filename and allowed(file.filename, "vid"):
                        try:
                            ext = file.filename.rsplit(".", 1)[1].lower()
                            fname = f"{uuid.uuid4().hex}.{ext}"
                            file.save(os.path.join(UPLOAD_FOLDER, fname))
                            videos.append({"type": "upload", "url": fname})
                        except Exception as e:
                            print(f"[!] Ошибка сохранения видео: {e}")
                
                video_urls = request.form.get("video_urls", "").strip()
                if video_urls:
                    for url in video_urls.split('\n'):
                        url = url.strip()
                        if url and is_valid_video_url(url):
                            videos.append({"type": "url", "url": url})
                
                # ОБНОВЛЯЕМ В БД
                with get_db() as conn:
                    conn.execute("""UPDATE news 
                        SET title_ru=?, title_kz=?, body_ru=?, body_kz=?, images=?, videos=?, pinned=?
                        WHERE id=?""",
                        (
                            title_ru, title_kz, body_ru, body_kz,
                            json.dumps(images), json.dumps(videos),
                            pinned, nid
                        ))
                
                print(f"[✓] Новость обновлена: {title_ru}")
                return redirect(url_for("admin_panel"))
            
            except Exception as e:
                print(f"[ERROR] admin_edit POST: {e}")
                return f"Ошибка при обновлении: {str(e)}", 500
        
        # GET - показываем форму редактирования
        item_dict = dict(item)
        try:
            item_dict['images'] = json.loads(item['images'] or '[]')
            item_dict['videos'] = json.loads(item['videos'] or '[]')
        except:
            item_dict['images'] = []
            item_dict['videos'] = []
        
        return render_template("admin_edit.html", item=item_dict)
    
    except Exception as e:
        print(f"[ERROR] admin_edit: {e}")
        return redirect(url_for("admin_panel"))

@app.route("/admin/delete/<int:nid>", methods=["POST"])
@require_admin
def admin_delete(nid):
    """Удаление новости"""
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM news WHERE id=?", (nid,))
        print(f"[✓] Новость удалена: {nid}")
        return redirect(url_for("admin_panel"))
    except Exception as e:
        print(f"[ERROR] admin_delete: {e}")
        return redirect(url_for("admin_panel"))

# ============ СТАТИЧЕСКИЕ ФАЙЛЫ ============

@app.route("/upload/<path:filename>")
def upload_file(filename):
    """Отправка загруженных файлов (картинки, видео)"""
    try:
        return send_from_directory(UPLOAD_FOLDER, filename)
    except Exception as e:
        print(f"[ERROR] upload_file {filename}: {e}")
        return "Файл не найден", 404

# ============ ЗАПУСК ПРИЛОЖЕНИЯ ============

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
