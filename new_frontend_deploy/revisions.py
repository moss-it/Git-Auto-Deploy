import os

import boto
import sqlalchemy as sa
import yaml

from new_frontend_deploy.core.models import Revisions
from new_frontend_deploy.settings import PATH_TO_CONFIGS


def get_all_revisions(session, data):

    app = data.get("app")
    req_filter = data.get("record_created")
    enable_sorting = data.get("enable_sorting")
    offset = data.get("offset")
    limit = data.get("limit")
    query = sa.select(
        [
            Revisions.commit_sha,
            Revisions.commit_author,
            Revisions.commit_date,
            Revisions.commit_message,
            Revisions.deploy_env,
            Revisions.tag,
            Revisions.record_created,
            Revisions.status,
            Revisions.s3_bucket_name,
        ]
    ).where(
        sa.and_(
            Revisions.app == app,
            Revisions.record_created >= req_filter
        ) if req_filter else Revisions.app == app
    ).order_by(
        sa.desc(
            Revisions.record_created if enable_sorting else Revisions.id
        )
    ).offset(offset or 0).limit(limit or 50)

    revisions = session.execute(query).fetchall()
    if not revisions:
        return "There are no revisions for this app"

    resp = []

    for rev in revisions:
        commit_sha = rev.commit_sha[:7] if rev.commit_sha else ""
        resp.append({
            "app": app,
            "env": rev.deploy_env,
            "commit_sha": commit_sha,
            "commit_date": rev.commit_date,
            "commit_message": rev.commit_message,
            "commit_author": rev.commit_author,
            "tag": rev.tag,
            "record_created": str(rev.record_created),
            "status": rev.status,
            "test_link": "https://{}/?build={}".format(rev.s3_bucket_name,
                                                       commit_sha)
        })

    return resp


def activate(session, data):

    app = data.get("app")
    env = data.get("env")
    commit = data.get("commit_sha")

    if not app or not env or not commit:
        return "Error! Invalid json!"

    query = sa.select(
        [
            Revisions.s3_bucket_name,
            Revisions.index_html_path,
        ]
    ).where(
        sa.and_(
            Revisions.commit_sha.like(commit + "%"),
            Revisions.deploy_env == env,
            Revisions.app == app,
        )
    ).order_by(
        sa.asc(
            Revisions.id
        )
    ).limit(1)
    revision_data = session.execute(query).fetchone()

    if not PATH_TO_CONFIGS:
        print 'Wrong configs dir in settings.py!'
        return "Error with revision activation, check git configs please!"

    with open(os.path.join(PATH_TO_CONFIGS, '{}/global.yml'.format(env))) as f:
        global_settings = yaml.load(f)

    try:
        conn = boto.connect_s3(global_settings.get('aws_s3_key'),
                               global_settings.get('aws_s3_secret_key'))
        bucket = conn.get_bucket(revision_data.s3_bucket_name)
    except Exception as e:
        print e.message
        return "Error with connection to AWS S3!"

    try:
        key = bucket.get_key(revision_data.index_html_path + '/' + 'index.html')
        if key.name:
            bucket.copy_key("index.html", bucket.name, key.name,
                            metadata={'Content-Type': 'text/html',
                                      'Cache-Control': 'max-age=0'})
            return "Done!"
        else:
            return "There is no such revision.!"

    except Exception as e:
        print e.message
        return "Error with activation {} on {}".format(commit, env)
