import json
import os
import tempfile
from pathlib import Path

import pytest
from deepdiff import DeepDiff
from flask import Response
from flask.testing import FlaskClient
from werkzeug.datastructures import Headers

from depc import create_app
from depc.controllers.checks import CheckController
from depc.controllers.configs import ConfigController
from depc.controllers.grants import GrantController
from depc.controllers.rules import RuleController
from depc.controllers.sources import SourceController
from depc.controllers.teams import TeamController
from depc.controllers.users import UserController
from depc.extensions import db


class DepcTestClient(FlaskClient):
    def __init__(self, *args, **kwargs):
        self._login = None
        super(DepcTestClient, self).__init__(*args, **kwargs)

    def login(self, login):
        self._login = login

    def logout(self):
        self._login = None

    def open(self, *args, **kwargs):
        headers = kwargs.pop('headers', Headers())

        if self._login:
            headers.extend({'X-Remote-User': self._login})
            kwargs['headers'] = headers
        return super().open(*args, **kwargs)


class DepcResponse(Response):

    def remove_keys(self, d, keys):
        if isinstance(keys, str):
            keys = [keys]
        if isinstance(d, dict):
            for key in set(keys):
                if key in d:
                    del d[key]
            for k, v in d.items():
                self.remove_keys(v, keys)
        elif isinstance(d, list):
            for i in d:
                self.remove_keys(i, keys)
        return d

    @property
    def json(self):
        data = json.loads(self.data.decode('utf-8'))
        self.remove_keys(data, ['id', 'createdAt', 'updatedAt', 'created_at', 'updated_at'])
        return data

    def raises_required_property(self, prop):
        wanted = {'message': "'{}' is a required property".format(prop)}
        return self.status_code == 400 and self.json == wanted


@pytest.fixture(scope='module')
def app_module():
    db_fd = db_path = None
    app = create_app(
        environment='test',
    )

    # Choose tests database
    if app.config['SQLALCHEMY_DATABASE_URI'] == 'sqlite://':
        db_fd, db_path = tempfile.mkstemp()
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///{}.db'.format(db_path)

    with app.app_context():
        db.create_all()

    app.response_class = DepcResponse
    app.test_client_class = DepcTestClient
    yield app

    with app.app_context():
        db.drop_all()

    if db_fd and db_path:
        os.close(db_fd)
        os.unlink(db_path)

    return app_module


@pytest.fixture(scope='function')
def app(app_module):
    with app_module.app_context():
        meta = db.metadata
        for table in reversed(meta.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
    return app_module


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def create_team(app):
    def _create_team(name):
        with app.app_context():
            return TeamController.create({
                'name': name
            })
    return _create_team


@pytest.fixture
def create_user(app):
    def _create_user(name):
        with app.app_context():
            return UserController.create({
                'name': name
            })
    return _create_user


@pytest.fixture
def create_grant(app):
    def _create_grant(team_id, user_id, role='member'):
        with app.app_context():
            return GrantController.create({
                'team_id': team_id,
                'user_id': user_id,
                'role': role
            })
    return _create_grant


@pytest.fixture
def create_source(app):
    def _create_source(name, team_id, plugin='Fake', conf={}):
        with app.app_context():
            return SourceController.create({
                'team_id': team_id,
                'name': name,
                'plugin': plugin,
                'configuration': conf
            })
    return _create_source


@pytest.fixture
def create_rule(app):
    def _create_rule(name, team_id, description=None):
        with app.app_context():
            return RuleController.create({
                'team_id': team_id,
                'name': name,
                'description': description
            })
    return _create_rule


@pytest.fixture
def create_check(app):
    def _create_check(name, source_id, type='Threshold', parameters={}):
        with app.app_context():
            return CheckController.create({
                'source_id': source_id,
                'name': name,
                'type': type,
                'parameters': parameters
            })
    return _create_check


@pytest.fixture
def add_check(app):
    def _add_check(rule_id, checks_id):
        with app.app_context():
            return RuleController.update_checks(
                rule_id=rule_id,
                checks_id=checks_id
            )
    return _add_check


@pytest.fixture
def create_config(app):
    def _create_config(team_id, conf={}):
        with app.app_context():
            return ConfigController.create({
                'team_id': team_id,
                'data': conf
            })
    return _create_config


@pytest.fixture
def open_mock():
    def _open_mock(name):
        path = Path(__file__).resolve().parent / 'data/{}.json'.format(name)
        with path.open() as f:
            data = json.load(f)
        return data
    return _open_mock


@pytest.fixture
def is_mock_equal(open_mock):
    def _is_mock_equal(data, mock_name):
        mock = open_mock(mock_name)
        return DeepDiff(data, mock, ignore_order=True) == {}
    return _is_mock_equal
