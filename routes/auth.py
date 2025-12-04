from flask import Blueprint, render_template, redirect, flash, request
from flask_login import login_user, logout_user, login_required
from werkzeug.security import generate_password_hash
from forms.forms import LoginForm, RegisterForm
from data.db_session import create_session
from data.users import User

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        db_sess = create_session()
        # Ищем пользователя по email
        user = db_sess.query(User).filter(User.email == form.email.data).first()

        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash('Аккаунт деактивирован', 'danger')
                db_sess.close()
                return render_template('auth/login.html', form=form)

            login_user(user, remember=form.remember_me.data)
            db_sess.close()
            return redirect("/")

        flash('Неверный email или пароль', 'danger')
        db_sess.close()

    return render_template('auth/login.html', form=form)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        db_sess = create_session()

        # Проверка уникальности email и username
        existing_email = db_sess.query(User).filter(User.email == form.email.data).first()
        existing_username = db_sess.query(User).filter(User.username == form.username.data).first()

        if existing_email:
            flash('Пользователь с таким email уже существует', 'danger')
            db_sess.close()
            return render_template('auth/register.html', form=form)

        if existing_username:
            flash('Пользователь с таким логином уже существует', 'danger')
            db_sess.close()
            return render_template('auth/register.html', form=form)

        # Проверка совпадения паролей
        if form.password.data != form.password_again.data:
            flash('Пароли не совпадают', 'danger')
            db_sess.close()
            return render_template('auth/register.html', form=form)

        # Создание нового пользователя
        user = User(
            surname=form.surname.data,
            name=form.name.data,
            patronymic=form.patronymic.data,
            position=form.position.data,
            username=form.username.data,
            email=form.email.data,
            is_active=True
        )
        user.set_password(form.password.data)

        try:
            db_sess.add(user)
            db_sess.commit()
            flash('Регистрация успешна! Теперь вы можете войти.', 'success')
            db_sess.close()
            return redirect('/auth/login')
        except Exception as e:
            db_sess.rollback()
            flash(f'Ошибка при регистрации: {str(e)}', 'danger')
        finally:
            db_sess.close()

    return render_template('auth/register.html', form=form)


# Или модифицируйте существующий:
@auth_bp.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    logout_user()
    if request.method == 'POST':
        return {'success': True, 'message': 'Вы успешно вышли из системы'}
    flash('Вы успешно вышли из системы', 'info')
    return redirect('/auth/login')


# Функция для настройки user_loader
def setup_user_loader(login_manager):
    @login_manager.user_loader
    def load_user(user_id):
        db_sess = create_session()
        user = db_sess.query(User).get(int(user_id))
        db_sess.close()
        return user