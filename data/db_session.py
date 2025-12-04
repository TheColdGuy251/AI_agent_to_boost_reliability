import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import Session
import sqlalchemy.ext.declarative as dec

SqlAlchemyBase = dec.declarative_base()

__factory = None
__engine = None

def global_init(db_file):
    global __factory, __engine

    if __factory:
        return __engine

    if not db_file or not db_file.strip():
        raise Exception("Необходимо указать файл базы данных.")

    conn_str = f'sqlite:///{db_file.strip()}?check_same_thread=False'
    print(f"Подключение к базе данных по адресу {conn_str}")

    __engine = sa.create_engine(conn_str, echo=False)
    __factory = orm.sessionmaker(bind=__engine)

    SqlAlchemyBase.metadata.create_all(__engine)
    return __engine

def create_session() -> Session:
    global __factory
    if not __factory:
        raise Exception("База данных не инициализирована. Вызовите global_init() сначала.")
    return __factory()

def get_engine():
    global __engine
    return __engine

def get_base():
    return SqlAlchemyBase

def get_metadata():
    return SqlAlchemyBase.metadata