from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
import sqlite3, os, uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "library-secret-2026")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME  = os.path.join(BASE_DIR, "library.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png","jpg","jpeg","gif","webp","mp4","webm"}
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "library2026")
UTC5 = timezone(timedelta(hours=5))

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed(filename):
    return "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED_EXT

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
        conn.execute("""CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title_ru TEXT, title_kz TEXT,
            body_ru TEXT,  body_kz TEXT,
            image TEXT, created_at TEXT, pinned INTEGER DEFAULT 0
        )""")
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
        image_path = None
        file = request.files.get("image")
        if file and file.filename and allowed(file.filename):
            ext = file.filename.rsplit(".",1)[1].lower()
            fname = f"{uuid.uuid4().hex}.{ext}"
            file.save(os.path.join(UPLOAD_FOLDER, fname))
            image_path = fname
        with get_db() as conn:
            conn.execute("""INSERT INTO news (title_ru,title_kz,body_ru,body_kz,image,created_at,pinned)
                VALUES (?,?,?,?,?,?,?)""",
                (title_ru, title_kz, body_ru, body_kz, image_path,
                 now5().strftime("%Y-%m-%d %H:%M"), pinned))
        return redirect(url_for("admin_panel"))
    return render_template("admin_add.html")

@app.route("/admin/edit/<int:nid>", methods=["GET","POST"])
@require_admin
def admin_edit(nid):
    with get_db() as conn:
        item = conn.execute("SELECT * FROM news WHERE id=?", (nid,)).fetchone()
    if not item: return redirect(url_for("admin_panel"))
    if request.method == "POST":
        title_ru = request.form.get("title_ru","").strip()
        title_kz = request.form.get("title_kz","").strip()
        body_ru  = request.form.get("body_ru","").strip()
        body_kz  = request.form.get("body_kz","").strip()
        pinned   = 1 if request.form.get("pinned") else 0
        image_path = item["image"]
        file = request.files.get("image")
        if file and file.filename and allowed(file.filename):
            ext = file.filename.rsplit(".",1)[1].lower()
            fname = f"{uuid.uuid4().hex}.{ext}"
            file.save(os.path.join(UPLOAD_FOLDER, fname))
            image_path = fname
        with get_db() as conn:
            conn.execute("""UPDATE news SET title_ru=?,title_kz=?,body_ru=?,body_kz=?,
                image=?,pinned=? WHERE id=?""",
                (title_ru,title_kz,body_ru,body_kz,image_path,pinned,nid))
        return redirect(url_for("admin_panel"))
    return render_template("admin_edit.html", item=item)

@app.route("/admin/delete/<int:nid>", methods=["POST"])
@require_admin
def admin_delete(nid):
    with get_db() as conn:
        conn.execute("DELETE FROM news WHERE id=?", (nid,))
    return redirect(url_for("admin_panel"))

if __name__ == "__main__":
    app.run(debug=True, port=5001)
