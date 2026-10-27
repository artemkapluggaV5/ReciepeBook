from .test_settings import *  # noqa
DATABASES = {'default': env.db('DATABASE_URL')}
