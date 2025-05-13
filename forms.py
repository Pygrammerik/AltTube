from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, FileField, SubmitField
from wtforms.validators import DataRequired

class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Register')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class UploadForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired()])
    description = StringField('Description', validators=[DataRequired()])
    video = FileField('Video', validators=[DataRequired()])
    preview = FileField('Preview Image', validators=[DataRequired()])
    submit = SubmitField('Upload')

class CommentForm(FlaskForm):
    text = StringField('Комментарий', validators=[DataRequired()])
    submit = SubmitField('Оставить комментарий')

class ProfileImageForm(FlaskForm):
    avatar = FileField('Аватарка')
    cover = FileField('Шапка профиля')
    submit = SubmitField('Сохранить')
