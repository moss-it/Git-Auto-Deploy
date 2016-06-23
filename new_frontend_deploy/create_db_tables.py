#!/usr/bin/env python
from core.models import Model
from core.session import postgres_engine


if __name__ == '__main__':
    Model.metadata.create_all(postgres_engine)
