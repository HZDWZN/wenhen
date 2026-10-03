import os, secrets
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
import psycopg
from psycopg.rows import dict_row

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE-ME")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "CHANGE-ME")

BAD_WORDS = ["加微信", "手机号", "裸聊", "赌博", "毒品"]

def db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def init_db():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id BIGSERIAL PRIMARY KEY,
            nickname TEXT NOT NULL,
            grade TEXT DEFAULT '',
            content TEXT NOT NULL,
            anonymous BOOLEAN DEFAULT TRUE,
            status TEXT DEFAULT 'pending',
            likes INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS comments (
            id BIGSERIAL PRIMARY KEY,
            post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
            nickname TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT DEFAULT 'approved',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS reports (
            id BIGSERIAL PRIMARY KEY,
            post_id BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
            reason TEXT DEFAULT '',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)

def contains_bad_word(text):
    return any(w.lower() in text.lower() for w in BAD_WORDS)

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper

@app.route("/")
def index():
    with db() as conn:
        posts = conn.execute(
            "SELECT * FROM posts WHERE status='approved' ORDER BY id DESC"
        ).fetchall()
    return render_template("index.html", posts=posts)

@app.route("/post", methods=["POST"])
def create_post():
    nickname=request.form.get("nickname","").strip()[:30]
    grade=request.form.get("grade","").strip()[:30]
    content=request.form.get("content","").strip()[:1000]
    anonymous=bool(request.form.get("anonymous"))
    if not nickname or not content:
        flash("昵称和表白内容不能为空。","error"); return redirect(url_for("index"))
    if contains_bad_word(nickname+grade+content):
        flash("内容包含不适合公开的信息，请修改后再提交。","error"); return redirect(url_for("index"))
    with db() as conn:
        conn.execute("INSERT INTO posts(nickname,grade,content,anonymous,status) VALUES(%s,%s,%s,%s,'pending')",
                     (nickname,grade,content,anonymous))
    flash("投稿成功！审核通过后会显示在表白墙。","success")
    return redirect(url_for("index"))

@app.route("/like/<int:post_id>", methods=["POST"])
def like(post_id):
    with db() as conn:
        row=conn.execute("UPDATE posts SET likes=likes+1 WHERE id=%s AND status='approved' RETURNING likes",(post_id,)).fetchone()
    if not row: return jsonify({"ok":False}),404
    return jsonify({"ok":True,"likes":row["likes"]})

@app.route("/comment/<int:post_id>", methods=["POST"])
def comment(post_id):
    nickname=request.form.get("nickname","").strip()[:30]
    content=request.form.get("content","").strip()[:300]
    if not nickname or not content:
        flash("评论昵称和内容不能为空。","error"); return redirect(url_for("index"))
    if contains_bad_word(nickname+content):
        flash("评论包含不适合公开的信息。","error"); return redirect(url_for("index"))
    with db() as conn:
        if not conn.execute("SELECT id FROM posts WHERE id=%s AND status='approved'",(post_id,)).fetchone():
            abort(404)
        conn.execute("INSERT INTO comments(post_id,nickname,content,status) VALUES(%s,%s,%s,'approved')",
                     (post_id,nickname,content))
    return redirect(url_for("index"))

@app.route("/report/<int:post_id>", methods=["POST"])
def report(post_id):
    reason=request.form.get("reason","").strip()[:200]
    with db() as conn:
        conn.execute("INSERT INTO reports(post_id,reason) VALUES(%s,%s)",(post_id,reason))
    flash("举报已提交，管理员会进行处理。","success")
    return redirect(url_for("index"))

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method=="POST":
        user=request.form.get("username",""); password=request.form.get("password","")
        if secrets.compare_digest(user,ADMIN_USER) and secrets.compare_digest(password,ADMIN_PASSWORD):
            session["admin"]=True; return redirect(url_for("admin"))
        flash("账号或密码错误。","error")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.clear(); return redirect(url_for("index"))

@app.route("/admin")
@admin_required
def admin():
    with db() as conn:
        pending=conn.execute("SELECT * FROM posts WHERE status='pending' ORDER BY id DESC").fetchall()
        approved=conn.execute("SELECT * FROM posts WHERE status='approved' ORDER BY id DESC").fetchall()
        rejected=conn.execute("SELECT * FROM posts WHERE status='rejected' ORDER BY id DESC").fetchall()
        stats={
          "total":conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"],
          "pending":conn.execute("SELECT COUNT(*) c FROM posts WHERE status='pending'").fetchone()["c"],
          "approved":conn.execute("SELECT COUNT(*) c FROM posts WHERE status='approved'").fetchone()["c"],
          "rejected":conn.execute("SELECT COUNT(*) c FROM posts WHERE status='rejected'").fetchone()["c"],
          "likes":conn.execute("SELECT COALESCE(SUM(likes),0) c FROM posts").fetchone()["c"],
          "reports":conn.execute("SELECT COUNT(*) c FROM reports").fetchone()["c"]
        }
    return render_template("admin.html",pending=pending,approved=approved,rejected=rejected,stats=stats)

@app.route("/admin/post/<int:post_id>/<action>",methods=["POST"])
@admin_required
def admin_post_action(post_id,action):
    with db() as conn:
        if action=="approve": conn.execute("UPDATE posts SET status='approved' WHERE id=%s",(post_id,))
        elif action=="reject": conn.execute("UPDATE posts SET status='rejected' WHERE id=%s",(post_id,))
        elif action=="delete": conn.execute("DELETE FROM posts WHERE id=%s",(post_id,))
        else: abort(400)
    return redirect(url_for("admin"))

@app.route("/admin/comment/<int:comment_id>/delete",methods=["POST"])
@admin_required
def admin_delete_comment(comment_id):
    with db() as conn: conn.execute("DELETE FROM comments WHERE id=%s",(comment_id,))
    return redirect(url_for("admin"))

@app.get("/health")
def health(): return "ok"

if __name__=="__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
