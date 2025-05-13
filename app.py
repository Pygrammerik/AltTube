from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from functools import wraps
from flask import abort
import json
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired

from models import db, User, Video
from forms import RegisterForm, LoginForm, UploadForm, CommentForm, ProfileImageForm

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///altube.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['PREVIEW_FOLDER'] = 'static/previews'
app.config['AVATAR_FOLDER'] = 'static/avatars'
app.config['COVER_FOLDER'] = 'static/covers'

# Создание папок для загрузок, если их нет
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PREVIEW_FOLDER'], exist_ok=True)
os.makedirs(app.config['AVATAR_FOLDER'], exist_ok=True)
os.makedirs(app.config['COVER_FOLDER'], exist_ok=True)

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

USERS_FILE = 'user.json'
COMMENTS_FILE = 'comments.json'
LIKES_FILE = 'likes.json'
DISLIKES_FILE = 'dislikes.json'
HISTORY_FILE = 'history.json'

def load_users():
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def get_user_by_username(username):
    users = load_users()
    for user in users:
        if user['username'] == username:
            return user
    return None

def get_user_by_id(user_id):
    users = load_users()
    for user in users:
        if user['id'] == user_id:
            return user
    return None

def update_user(user):
    users = load_users()
    for i, u in enumerate(users):
        if u['id'] == user['id']:
            users[i] = user
            break
    save_users(users)

@login_manager.user_loader
def load_user(user_id):
    user = get_user_by_id(int(user_id))
    if user:
        return UserJson(user)
    return None

@app.before_request
def create_tables():
    if not hasattr(app, 'db_initialized'):
        db.create_all()
        app.db_initialized = True

@app.route('/')
def index():
    reset_reuploads_user()
    videos = Video.query.all()
    print('Видео на главной:', [(v.id, v.user_id) for v in videos])
    subscriptions = get_user_subscriptions(current_user._dict) if current_user.is_authenticated else []
    history = get_user_history(current_user.id) if current_user.is_authenticated else []
    return render_template('index.html', videos=videos, subscriptions=subscriptions, history=history)

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        if get_user_by_username(form.username.data):
            flash('Username already exists')
            return redirect(url_for('register'))
        users = load_users()
        user_ip = request.remote_addr
        # Считаем пользователей с этим IP
        same_ip_count = sum(1 for u in users if u.get('ip') == user_ip)
        if same_ip_count >= 5:
            flash('С этого IP-адреса уже создано 5 аккаунтов!')
            return redirect(url_for('register'))
        new_id = max([u['id'] for u in users], default=0) + 1
        hashed_pw = generate_password_hash(form.password.data)
        user = {
            'id': new_id,
            'username': form.username.data,
            'password': hashed_pw,
            'is_banned': False,
            'strikes': 0,
            'subscriptions': [],
            'subscriptions_count': 0,
            'ip': user_ip
        }
        users.append(user)
        save_users(users)
        flash('Registered successfully!')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = get_user_by_username(form.username.data)
        if user and user['password'] == form.password.data:
            if user.get('is_banned', False):
                flash('Ваш аккаунт забанен!')
                return redirect(url_for('login'))
            login_user(UserJson(user))
            return redirect(url_for('index'))
        flash('Invalid credentials')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    form = UploadForm()
    if form.validate_on_submit():
        video_file = form.video.data
        preview_file = form.preview.data
        video_filename = secure_filename(video_file.filename)
        preview_filename = secure_filename(preview_file.filename)
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], video_filename)
        preview_path = os.path.join(app.config['PREVIEW_FOLDER'], preview_filename)
        video_file.save(video_path)
        preview_file.save(preview_path)
        video = Video(
            title=form.title.data,
            description=form.description.data,
            filename=video_filename,
            preview=preview_filename,
            user_id=current_user.id
        )
        db.session.add(video)
        db.session.commit()
        flash('Video uploaded!')
        return redirect(url_for('index'))
    return render_template('upload.html', form=form)

@app.route('/video/<int:video_id>', methods=['GET', 'POST'])
def video(video_id):
    video = Video.query.get_or_404(video_id)
    videos = Video.query.all()
    comments = [c for c in load_comments() if c['video_id'] == video_id]
    form = CommentForm()
    history_videos = {}
    if current_user.is_authenticated:
        add_to_history(current_user.id, video_id)
        # Для истории в сайдбаре
        user_history = get_user_history(current_user.id)
        history_ids = [h['video_id'] for h in user_history]
        history_videos = {v.id: v for v in Video.query.filter(Video.id.in_(history_ids)).all()}
    else:
        user_history = []
    if form.validate_on_submit() and current_user.is_authenticated:
        add_comment(video_id, current_user.id, current_user.username, form.text.data)
        return redirect(url_for('video', video_id=video_id))
    can_delete = lambda c: current_user.is_authenticated and (current_user.id == video.user_id)
    subscriptions = get_user_subscriptions(current_user._dict) if current_user.is_authenticated else []
    return render_template(
        'video.html',
        video=video,
        videos=videos,
        comments=comments,
        form=form,
        can_delete=can_delete,
        user_liked_video=user_liked_video,
        get_video_likes=get_video_likes,
        user_disliked_video=user_disliked_video,
        get_video_dislikes=get_video_dislikes,
        subscriptions=subscriptions,
        history=user_history,
        history_videos=history_videos
    )

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ['admin', 'owner']:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def owner_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'owner':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin')
@admin_required
def admin_panel():
    users = load_users()
    videos = Video.query.all()
    return render_template('admin.html', users=users, videos=videos)

@app.route('/admin/ban_user/<int:user_id>')
@admin_required
def ban_user(user_id):
    user = get_user_by_id(user_id)
    if not user:
        flash('Пользователь не найден!')
        return redirect(url_for('admin_panel'))
    if user['role'] == 'owner':
        flash('Нельзя забанить владельца!')
        return redirect(url_for('admin_panel'))
    user['is_banned'] = True
    update_user(user)
    flash(f'Пользователь {user['username']} забанен!')
    return redirect(url_for('admin_panel'))

@app.route('/admin/unban_user/<int:user_id>')
@admin_required
def unban_user(user_id):
    user = get_user_by_id(user_id)
    if not user:
        flash('Пользователь не найден!')
        return redirect(url_for('admin_panel'))
    user['is_banned'] = False
    update_user(user)
    flash(f'Пользователь {user['username']} разбанен!')
    return redirect(url_for('admin_panel'))

@app.route('/admin/strike_user/<int:user_id>')
@admin_required
def strike_user(user_id):
    user = get_user_by_id(user_id)
    if not user:
        flash('Пользователь не найден!')
        return redirect(url_for('admin_panel'))
    user['strikes'] = user.get('strikes', 0) + 1
    if user['strikes'] >= 3:
        user['is_banned'] = True
    update_user(user)
    flash(f'Пользователь {user['username']} получил страйк! (Всего: {user['strikes']})')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_video/<int:video_id>')
@admin_required
def delete_video(video_id):
    video = Video.query.get_or_404(video_id)
    db.session.delete(video)
    db.session.commit()
    flash('Видео удалено!')
    return redirect(url_for('admin_panel'))

@app.route('/giverole', methods=['GET', 'POST'])
@owner_required
def giverole():
    if request.method == 'POST':
        username = request.form.get('username')
        role = request.form.get('role')
        user = get_user_by_username(username)
        if not user:
            flash('Пользователь не найден!')
        elif role not in ['user', 'admin', 'owner']:
            flash('Недопустимая роль!')
        else:
            user['role'] = role
            update_user(user)
            flash(f'Роль пользователя {user['username']} изменена на {role}!')
        return redirect(url_for('giverole'))
    return render_template('giverole.html')

class UserJson(UserMixin):
    def __init__(self, user_dict):
        self.id = user_dict['id']
        self.username = user_dict['username']
        self.password = user_dict['password']
        self.role = user_dict.get('role', 'user')
        self.is_banned = user_dict.get('is_banned', False)
        self.strikes = user_dict.get('strikes', 0)
        self._dict = user_dict

    def get_id(self):
        return str(self.id)

def load_comments():
    if not os.path.exists(COMMENTS_FILE):
        return []
    with open(COMMENTS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_comments(comments):
    with open(COMMENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(comments, f, ensure_ascii=False, indent=2)

def add_comment(video_id, author_id, author_name, text):
    comments = load_comments()
    new_id = max([c['id'] for c in comments], default=0) + 1
    from datetime import datetime
    comment = {
        'id': new_id,
        'video_id': video_id,
        'author_id': author_id,
        'author_name': author_name,
        'text': text,
        'created': datetime.now().strftime('%Y-%m-%d %H:%M')
    }
    comments.append(comment)
    save_comments(comments)

def delete_comment(comment_id):
    comments = load_comments()
    comments = [c for c in comments if c['id'] != comment_id]
    save_comments(comments)

def subscribe(user, target_id):
    subs = user.get('subscriptions', [])
    if target_id not in subs:
        subs.append(target_id)
        user['subscriptions'] = subs
        user['subscriptions_count'] = len(subs)
        update_user(user)

def unsubscribe(user, target_id):
    subs = user.get('subscriptions', [])
    if target_id in subs:
        subs.remove(target_id)
        user['subscriptions'] = subs
        user['subscriptions_count'] = len(subs)
        update_user(user)

@app.route('/delete_comment/<int:comment_id>/<int:video_id>')
@login_required
def delete_comment_route(comment_id, video_id):
    comments = load_comments()
    comment = next((c for c in comments if c['id'] == comment_id), None)
    video = Video.query.get_or_404(video_id)
    if comment and current_user.id == video.user_id:
        delete_comment(comment_id)
    return redirect(url_for('video', video_id=video_id))

@app.route('/profile/<username>')
def profile(username):
    user = get_user_by_username(username)
    if not user:
        flash('Пользователь не найден!')
        return redirect(url_for('index'))
    videos = Video.query.filter_by(user_id=user['id']).all()
    is_me = current_user.is_authenticated and current_user.username == username
    is_subscribed = False
    if current_user.is_authenticated and not is_me:
        is_subscribed = user['id'] in current_user._dict.get('subscriptions', [])
    return render_template('profile.html', user=user, videos=videos, is_me=is_me, is_subscribed=is_subscribed)

@app.route('/subscribe/<int:user_id>')
@login_required
def subscribe_route(user_id):
    user = get_user_by_id(current_user.id)
    subscribe(user, user_id)
    return redirect(request.referrer or url_for('index'))

@app.route('/unsubscribe/<int:user_id>')
@login_required
def unsubscribe_route(user_id):
    user = get_user_by_id(current_user.id)
    unsubscribe(user, user_id)
    return redirect(request.referrer or url_for('index'))

@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = ProfileImageForm()
    user = get_user_by_id(current_user.id)
    if form.validate_on_submit():
        if form.avatar.data:
            avatar_filename = f"{user['username']}_avatar.png"
            avatar_path = os.path.join(app.config['AVATAR_FOLDER'], avatar_filename)
            form.avatar.data.save(avatar_path)
            user['avatar'] = avatar_filename
        if form.cover.data:
            cover_filename = f"{user['username']}_cover.png"
            cover_path = os.path.join(app.config['COVER_FOLDER'], cover_filename)
            form.cover.data.save(cover_path)
            user['cover'] = cover_filename
        update_user(user)
        flash('Профиль обновлен!')
        return redirect(url_for('profile', username=user['username']))
    return render_template('edit_profile.html', form=form, user=user)

@app.route('/studio')
@login_required
def studio():
    videos = Video.query.filter_by(user_id=current_user.id).all()
    comments = load_comments()
    user_comments = [c for c in comments if any(v.id == c['video_id'] for v in videos)]
    user = get_user_by_id(current_user.id)
    subscribers = [u for u in load_users() if user['id'] in u.get('subscriptions', [])]
    return render_template('studio.html', videos=videos, comments=user_comments, subscribers=subscribers)

@app.route('/studio/delete_video/<int:video_id>')
@login_required
def studio_delete_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.user_id != current_user.id:
        flash('У вас нет прав на удаление этого видео!', 'danger')
        return redirect(url_for('studio'))
    
    # Удаляем файлы видео и превью
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], video.filename))
        os.remove(os.path.join(app.config['PREVIEW_FOLDER'], video.preview))
    except Exception as e:
        print(f'Ошибка при удалении файлов: {e}')
    
    # Удаляем видео из базы данных
    db.session.delete(video)
    db.session.commit()
    
    flash('Видео успешно удалено!', 'success')
    return redirect(url_for('studio'))

def load_likes():
    if not os.path.exists(LIKES_FILE):
        return []
    with open(LIKES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_likes(likes):
    with open(LIKES_FILE, 'w', encoding='utf-8') as f:
        json.dump(likes, f, ensure_ascii=False, indent=2)

def get_video_likes(video_id):
    likes = load_likes()
    return [l for l in likes if l['video_id'] == video_id]

def user_liked_video(user_id, video_id):
    likes = load_likes()
    return any(l['user_id'] == user_id and l['video_id'] == video_id for l in likes)

def add_like(user_id, video_id):
    if not user_liked_video(user_id, video_id):
        likes = load_likes()
        likes.append({'user_id': user_id, 'video_id': video_id})
        save_likes(likes)

def remove_like(user_id, video_id):
    likes = load_likes()
    likes = [l for l in likes if not (l['user_id'] == user_id and l['video_id'] == video_id)]
    save_likes(likes)

@app.route('/like/<int:video_id>', methods=['POST'])
@login_required
def like_video(video_id):
    add_like(current_user.id, video_id)
    return redirect(request.referrer or url_for('video', video_id=video_id))

@app.route('/unlike/<int:video_id>', methods=['POST'])
@login_required
def unlike_video(video_id):
    remove_like(current_user.id, video_id)
    return redirect(request.referrer or url_for('video', video_id=video_id))

def load_dislikes():
    if not os.path.exists(DISLIKES_FILE):
        return []
    with open(DISLIKES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_dislikes(dislikes):
    with open(DISLIKES_FILE, 'w', encoding='utf-8') as f:
        json.dump(dislikes, f, ensure_ascii=False, indent=2)

def get_video_dislikes(video_id):
    dislikes = load_dislikes()
    return [d for d in dislikes if d['video_id'] == video_id]

def user_disliked_video(user_id, video_id):
    dislikes = load_dislikes()
    return any(d['user_id'] == user_id and d['video_id'] == video_id for d in dislikes)

def add_dislike(user_id, video_id):
    if not user_disliked_video(user_id, video_id):
        dislikes = load_dislikes()
        dislikes.append({'user_id': user_id, 'video_id': video_id})
        save_dislikes(dislikes)

def remove_dislike(user_id, video_id):
    dislikes = load_dislikes()
    dislikes = [d for d in dislikes if not (d['user_id'] == user_id and d['video_id'] == video_id)]
    save_dislikes(dislikes)

@app.route('/dislike/<int:video_id>', methods=['POST'])
@login_required
def dislike_video(video_id):
    add_dislike(current_user.id, video_id)
    return redirect(request.referrer or url_for('video', video_id=video_id))

@app.route('/undislike/<int:video_id>', methods=['POST'])
@login_required
def undislike_video(video_id):
    remove_dislike(current_user.id, video_id)
    return redirect(request.referrer or url_for('video', video_id=video_id))

def get_user_subscriptions(user):
    subs = user.get('subscriptions', [])
    return [get_user_by_id(uid) for uid in subs if get_user_by_id(uid)]

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_history(history):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def add_to_history(user_id, video_id):
    history = load_history()
    # Находим существующую запись
    existing_entry = next((h for h in history if h['user_id'] == user_id and h['video_id'] == video_id), None)
    
    from datetime import datetime
    new_entry = {
        'user_id': user_id,
        'video_id': video_id,
        'watched': datetime.now().strftime('%Y-%m-%d %H:%M')
    }
    
    if existing_entry:
        # Обновляем время просмотра существующей записи
        history.remove(existing_entry)
    
    history.append(new_entry)
    save_history(history)

def get_user_history(user_id):
    history = load_history()
    return [h for h in history if h['user_id'] == user_id]

def clear_user_history(user_id):
    history = load_history()
    history = [h for h in history if h['user_id'] != user_id]
    save_history(history)

@app.route('/clear_history', methods=['POST'])
@login_required
def clear_history():
    clear_user_history(current_user.id)
    flash('История просмотров очищена')
    return redirect(url_for('history'))

@app.route('/history')
@login_required
def history():
    history_entries = get_user_history(current_user.id)
    # Сортируем по времени просмотра (сначала новые)
    history_entries.sort(key=lambda x: x['watched'], reverse=True)
    subscriptions = get_user_subscriptions(current_user._dict)
    # Получаем все видео из истории одним запросом
    video_ids = [h['video_id'] for h in history_entries]
    videos = {v.id: v for v in Video.query.filter(Video.id.in_(video_ids)).all()}
    return render_template('history.html', history=history_entries, subscriptions=subscriptions, videos=videos)

class YoutubeImportForm(FlaskForm):
    url = StringField('Ссылка на YouTube-видео', validators=[DataRequired()])
    submit = SubmitField('Импортировать')

def reset_reuploads_user():
    from models import User
    from werkzeug.security import generate_password_hash
    # Удаляем из user.json
    users = load_users()
    users = [u for u in users if u['username'] != 'youtube_reuploads']
    reup_user = {
        'id': 9999,
        'username': 'youtube_reuploads',
        'password': generate_password_hash('reuploads123'),
        'is_banned': False,
        'strikes': 0,
        'subscriptions': [],
        'subscriptions_count': 0,
        'avatar': '',
        'cover': '',
        'links': [],
        'ip': ''
    }
    users.append(reup_user)
    save_users(users)
    # Удаляем из базы
    User.query.filter_by(username='youtube_reuploads').delete()
    db.session.commit()
    # Добавляем в базу
    if not User.query.filter_by(id=9999).first():
        db.session.add(User(id=9999, username='youtube_reuploads', password=generate_password_hash('reuploads123')))
        db.session.commit()
    print('Профиль youtube_reuploads пересоздан с id=9999')

@app.route('/reset_reuploads_user')
def reset_reuploads_user_route():
    reset_reuploads_user()
    flash('Профиль youtube_reuploads пересоздан!')
    return redirect(url_for('index'))

@app.route('/import_youtube', methods=['GET', 'POST'])
@login_required
def import_youtube():
    form = YoutubeImportForm()
    reset_reuploads_user()
    if form.validate_on_submit():
        url = form.url.data
        from yt_dlp import YoutubeDL
        reup_user_id = 9999
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': f'static/uploads/%(id)s.%(ext)s',
            'merge_output_format': 'mp4',
            'writethumbnail': True,
            'writeinfojson': True,
            'quiet': True,
            'noplaylist': True,
        }
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_filename = f"{info['id']}.mp4"
                preview_filename = None
                for ext in ['jpg', 'webp', 'png']:
                    thumb_path = f"static/uploads/{info['id']}.{ext}"
                    if os.path.exists(thumb_path):
                        preview_filename = f"{info['id']}.{ext}"
                        break
                if preview_filename:
                    import shutil
                    shutil.copy(f"static/uploads/{preview_filename}", f"static/previews/{preview_filename}")
                video = Video(
                    title=info.get('title', 'Видео с YouTube'),
                    description=info.get('description', ''),
                    filename=video_filename,
                    preview=preview_filename or '',
                    user_id=reup_user_id
                )
                db.session.add(video)
                db.session.commit()
                print('Импортировано видео:', video_filename, 'user_id:', reup_user_id)
                flash('Видео успешно импортировано!')
                return redirect(url_for('index'))
        except Exception as e:
            print('Ошибка при скачивании видео:', e)
            flash(f'Ошибка при скачивании видео: {e}', 'danger')
            return redirect(url_for('import_youtube'))
    return render_template('import_youtube.html', form=form)

if __name__ == '__main__':
    app.run(debug=True)
