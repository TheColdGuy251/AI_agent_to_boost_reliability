from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, EmailField, BooleanField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional



class LoginForm(FlaskForm):
    email = EmailField('Email', validators=[
        DataRequired(message='Email обязателен для заполнения'),
        Email(message='Введите корректный email адрес')
    ])
    password = PasswordField('Пароль', validators=[
        DataRequired(message='Пароль обязателен для заполнения'),
        Length(min=6, message='Пароль должен содержать минимум 6 символов')
    ])
    remember_me = BooleanField('Запомнить меня')
    submit = SubmitField('Войти')


class RegisterForm(FlaskForm):
    surname = StringField('Фамилия*', validators=[
        DataRequired(message='Фамилия обязательна для заполнения'),
        Length(min=2, max=120, message='Фамилия должна содержать от 2 до 120 символов')
    ])
    name = StringField('Имя*', validators=[
        DataRequired(message='Имя обязательно для заполнения'),
        Length(min=2, max=120, message='Имя должно содержать от 2 до 120 символов')
    ])
    patronymic = StringField('Отчество', validators=[
        Optional(),
        Length(max=120, message='Отчество не должно превышать 120 символов')
    ])
    position = StringField('Должность*', validators=[
        DataRequired(message='Должность обязательна для заполнения'),
        Length(min=2, max=120, message='Должность должна содержать от 2 до 120 символов')
    ])
    username = StringField('Логин*', validators=[
        DataRequired(message='Логин обязателен для заполнения'),
        Length(min=3, max=80, message='Логин должен содержать от 3 до 80 символов')
    ])
    email = EmailField('Email*', validators=[
        DataRequired(message='Email обязателен для заполнения'),
        Email(message='Введите корректный email адрес'),
        Length(max=120, message='Email не должен превышать 120 символов')
    ])
    password = PasswordField('Пароль*', validators=[
        DataRequired(message='Пароль обязателен для заполнения'),
        Length(min=6, message='Пароль должен содержать минимум 6 символов')
    ])
    password_again = PasswordField('Повторите пароль*', validators=[
        DataRequired(message='Подтверждение пароля обязательно')
    ])
    submit = SubmitField('Зарегистрироваться')