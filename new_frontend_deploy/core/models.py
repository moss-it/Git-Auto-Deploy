from sqlalchemy import Column, Integer, String, TIMESTAMP, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base

Model = declarative_base()


class Revisions(Model):
    __tablename__ = 'revisions'

    REPR = u'''\n{__clsname__}.{id}'''

    id = Column(Integer, primary_key=True)

    app = Column(String(255))
    index_html_path = Column(String(255))
    revision_name = Column(String(255))
    build_log = Column(Text)
    s3_bucket_name = Column(String(255))
    deploy_env = Column(String(255))

    commit_sha = Column(String(255))
    commit_date = Column(String(255))
    commit_author = Column(String(255))
    commit_message = Column(String(255))
    tag = Column(String(255))

    record_created = Column(TIMESTAMP)
    record_modified = Column(TIMESTAMP)

    status = Column(String(255))
