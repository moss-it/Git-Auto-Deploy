import os

import boto
import sqlalchemy as sa
import yaml

from new_frontend_deploy.core.models import Revisions
from new_frontend_deploy.settings import PATH_TO_CONFIGS


def get_all_revisions(session, app):
    query = sa.select(
        [
            Revisions.commit_sha,
            Revisions.commit_author,
            Revisions.commit_date,
            Revisions.deploy_env
        ]
    ).where(
        Revisions.app == app
    ).order_by(
        sa.desc(
            Revisions.id
        )
    ).limit(50)

    revisions = session.execute(query).fetchall()
    if not revisions:
        return "There are no revisions for this app"

    res_str = ""
    for rev in revisions:
        res_str += '`{} {} {} {} {}`\n'.format(
            app,
            rev.deploy_env,
            rev.commit_sha[:7] if rev.commit_sha else "",
            rev.commit_date,
            rev.commit_author
        )

    return res_str


def activate(session, commit, env):
    is_tag = False
    if '.' in commit:
        is_tag = True

    query = sa.select(
        [
            Revisions.s3_bucket_name,
            Revisions.index_html_path,
            Revisions.app
        ]
    ).where(
        sa.and_(
            Revisions.tag == commit if is_tag else Revisions.commit_sha.like(
                commit + "%"),
            Revisions.deploy_env == env
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
        return "Error with connection to AWS S3"

    try:
        key = bucket.get_key(revision_data.index_html_path + '/' + 'index.html')
        if key.name:
            bucket.copy_key("index.html", bucket.name, key.name,
                            metadata={'Content-Type': 'text/html',
                                      'Cache-Control': 'max-age=0'})
            return "Done!"
        else:
            return "There is no such revision."

    except Exception as e:
        print e.message
        return "Error with activation {} on {}".format(commit, env)
