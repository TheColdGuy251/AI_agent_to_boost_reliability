import os
import sys
from flask import Flask
from flask_migrate import Migrate
from data import db_session
from data.db_session import get_engine, SqlAlchemyBase

# Создаем Flask приложение
app = Flask(__name__)
app.config['SECRET_KEY'] = 'Secret_Key_That_NoOne_Knows'

# Инициализация базы данных
print("Инициализация базы данных...")
db_session.global_init("db/database.db")

# Настройка миграций
print("Настройка миграций...")
migrate = Migrate(app, get_engine())

if __name__ == '__main__':
    # Устанавливаем переменную окружения для Flask
    os.environ['FLASK_APP'] = 'migrate.py'

    if len(sys.argv) > 1:
        command = sys.argv[1]

        with app.app_context():
            from flask_migrate import migrate as migrate_cmd, upgrade, init, revision

            if command == 'init':
                print("Инициализация миграций...")
                init()
            elif command == 'migrate':
                print("Создание миграции...")
                message = sys.argv[2] if len(sys.argv) > 2 else "Auto migration"
                migrate_cmd(message=message)
            elif command == 'upgrade':
                print("Применение миграций...")
                upgrade()
            elif command == 'history':
                from flask_migrate import history

                history()
            elif command == 'current':
                from flask_migrate import current

                current()
            else:
                print(f"Неизвестная команда: {command}")
    else:
        print("Использование: python migrate.py [init|migrate|upgrade|history|current]")
        print("  init     - инициализировать миграции")
        print("  migrate  - создать новую миграцию")
        print("  upgrade  - применить миграции")
        print("  history  - показать историю миграций")
        print("  current  - показать текущую версию")