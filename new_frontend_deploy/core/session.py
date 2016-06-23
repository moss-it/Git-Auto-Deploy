import collections
from contextlib import contextmanager
from functools import wraps
from itertools import ifilter

import new_frontend_deploy.settings as settings
from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy.orm import scoped_session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool


staging_url = 'postgresql://{}:{}@{}:{}/{}'.format(
    settings.POSTGRESQL_USERNAME,
    settings.POSTGRESQL_PASSWORD,
    settings.POSTGRESQL_HOST,
    settings.POSTGRESQL_PORT,
    settings.POSTGRESQL_DBNAME,
)

postgres_engine = create_engine(
    staging_url,
    echo=settings.POSTGRESQL_ECHO_MODE,
    encoding='utf-8',
    poolclass=NullPool,
)

# TODO: remove this shit
maker = sessionmaker(bind=postgres_engine)
Session = scoped_session(maker)


def create_session(*args, **kwargs):
    s = maker(*args, **kwargs)
    return s


_Session = create_session


def session_context(func):
    """
    SessionContext Decorator

    add SessionContext object as first arg
    if not received (with first arg or kwarg),
    else use received session

    >>> @session_context
    >>> def do_something(arg2, arg3, session=None)
    ...     print type(session)
    ...     print arg2
    ...     print arg3
    >>> do_something("A", "B")
    ... <class 'sqlalchemy.orm.session.Session'>
    ... 'A'
    ... 'B'
    >>> do_something('A', 'B', session=Session)
    ... <class 'sqlalchemy.orm.session.Session'>
    ... 'A'
    ... 'B'
    """

    @wraps(func)
    def wrapped(*args, **kwargs):
        from sqlalchemy.orm import Session

        expected_session_kwarg = kwargs.get('session')

        if isinstance(expected_session_kwarg, Session):
            return func(*args, **kwargs)
        else:
            with SessionContext() as session:
                return func(*args, session=session, **kwargs)

    return wrapped


class SessionContext(object):
    """ Transaction wrapper for SQLAlchemy sessions

    You can issue whatever commit or rollback inside session
    as many times as you want, it won't affect higher transaction
    """

    def __init__(self,
                 external_connection=None,
                 expunge_on_close=False,
                 lock_tables=None,
                 manual_transaction=False,
                 isolation_level=None,
                 **kwargs):
        self._external_connection = external_connection
        self._manual_transaction = manual_transaction
        self._isolation_level = isolation_level
        self._expunge_on_close = expunge_on_close
        self._lock_tables = set()
        self._kwargs = kwargs

        self._engine = postgres_engine
        if self._isolation_level:
            self._engine = (
                postgres_engine.execution_options(
                    isolation_level=self._isolation_level,
                )
            )

        if lock_tables:
            from collections import Iterable
            from models import Model

            if not isinstance(lock_tables, Iterable):
                raise TypeError('lock_tables is not iterable')

            allowed_tables = frozenset(Model.metadata.tables.keys())

            for table in lock_tables:
                if issubclass(table, Model):
                    self._lock_tables.add(table.__tablename__)
                elif (isinstance(table, basestring)
                      and table in allowed_tables):
                    self._lock_tables.add(table)
                else:
                    raise TypeError('Unknown table {}'.format(table))

    def __apply_locks(self):
        lock_command = 'LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE'  # full
        if self._lock_tables:
            q = lock_command.format(tables=', '.join(self._lock_tables))
            self._connection.execute(q)

    def __enter__(self):
        if self._manual_transaction:
            self._session = _Session(bind=self._engine, **self._kwargs)
        else:
            if self._external_connection:
                self._connection = self._external_connection
            else:
                self._connection = self._engine.connect()
                self._transaction = self._connection.begin()

            kwargs_copy = self._kwargs.copy()
            kwargs_copy['bind'] = self._connection
            self._session = sessionmaker(**kwargs_copy)()

        setattr(self._session, 'postcommit_data', [])
        setattr(self._session, 'cleanup_filters', [])

        self.__apply_locks()
        return self._session

    @contextmanager
    def __process_postcommit(self):
        if (self._session
            and hasattr(self._session, 'postcommit_data')
            and self._session.postcommit_data):
            for obj in self._session.postcommit_data:
                if obj in self._session:
                    self._session.expunge(obj)

        yield

        if (self._session
            and hasattr(self._session, 'postcommit_data')
            and self._session.postcommit_data):

            session = _Session(**self._kwargs)
            try:
                for obj in self._session.postcommit_data:
                    session.merge(obj)
                session.commit()
            except:
                session.rollback()
            finally:
                session.close()

    def __apply_cleanup_filters(self):
        if (self._session
            and hasattr(self._session, 'cleanup_filters')
            and self._session.cleanup_filters):
            session = _Session(**self._kwargs)

            try:
                for model, ids in self._session.cleanup_filters:
                    if isinstance(ids, (int, long)):
                        filters = (model.id == ids)
                    elif ids and isinstance(ids, collections.Iterable):
                        filters = (model.id.in_(ids))
                    else:
                        filters = None

                    if filters is not None:
                        q = session.query(model).filter(filters)
                        q.delete(synchronize_session='fetch')
                        session.commit()
            except:
                session.rollback()

    def __cleanup(self):
        with self.__process_postcommit():
            self._session.rollback()
            self._session.close()
            if not self._external_connection and not self._manual_transaction:
                self._transaction.rollback()
                self._connection.close()
        self.__apply_cleanup_filters()

    def __exit__(self, exc_type, exc_value, traceback):
        if not any((exc_type, exc_value, traceback)):
            success = True
            try:
                self._session.commit()
                if (not self._external_connection
                    and not self._manual_transaction):
                    self._transaction.commit()

                if self._expunge_on_close:
                    for _ref, obj in self._session.identity_map.iteritems():
                        self._session.refresh(obj)
                    self._session.expunge_all()

            except:
                self.__cleanup()
                raise
        else:
            success = False

        self.__cleanup()
        return success


def get_session(obj, *objs):
    ''' Returns db session from object

    If object has no session, an exception is raised
    If there are objs, each one is checked against obj's session
    '''
    assert obj
    for _obj in ifilter(None, objs):
        assert _obj

    state = inspect(obj)
    assert not state.detached

    session = state.session
    assert session

    for _obj in ifilter(None, objs):
        _state = inspect(_obj)
        assert not _state.detached
        assert session == _state.session

    return session
