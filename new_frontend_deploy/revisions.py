import argparse

import boto
import sqlalchemy as sa

from new_frontend_deploy.core.models import Revisions
from new_frontend_deploy.core.session import SessionContext
from new_frontend_deploy.settings import aws_access_key_id, \
    aws_secret_access_key

CORS_XML_TEMPLATE = """
<CORSConfiguration>
{RULES}
</CORSConfiguration>
"""

CORS_RULE_TEMPLATE = """
<CORSRule>
  <AllowedOrigin>https://{DOMAIN}</AllowedOrigin>
  <AllowedMethod>GET</AllowedMethod>
  <AllowedHeader>*</AllowedHeader>
</CORSRule>
<CORSRule>
  <AllowedOrigin>http://{DOMAIN}</AllowedOrigin>
  <AllowedMethod>GET</AllowedMethod>
  <AllowedHeader>*</AllowedHeader>
</CORSRule>
 <CORSRule>
   <AllowedOrigin>*</AllowedOrigin>
   <AllowedMethod>GET</AllowedMethod>
 </CORSRule>
"""

ORIGIN_HOSTS = [
    'app.local.collectrium.com:5000',
    'col5-app-devondemand.collectrium.com',
    'col5-app-devondemand2.collectrium.com',
    'col5-app.collectrium.com',
    'col5-app-test.collectrium.com',
    'col5-app-staging.collectrium.com',
    'col5-app-dev.collectrium.com',
    'col5-auth.collectrium.com',
    'col5-auth-test.collectrium.com',
    'col5-auth-staging.collectrium.com',
    'col5-auth-dev.collectrium.com',
    'auth-cams.collectriumdev.com',
    'app.collectriumdev.com',
    'auth.collectriumdev.com',
    'gavel.collectriumdev.com',
    'gavel-app-test.collectriumdev.com',
]


def public_file_link(bucket_name, key):
    return 'https://%s.s3.amazonaws.com/%s' % (bucket_name, key)


def setup_cors(aws_access_key_id, aws_secret_access_key,
               aws_storage_bucket_name):
    domains = ORIGIN_HOSTS
    conn = boto.connect_s3(aws_access_key_id, aws_secret_access_key)
    bucket = conn.get_bucket(aws_storage_bucket_name)
    domains = set(domains)
    cors_rules = ""
    for domain in domains:
        cors_rules += CORS_RULE_TEMPLATE.format(DOMAIN=domain)

    cors_xml = CORS_XML_TEMPLATE.format(RULES=cors_rules)
    bucket.set_cors_xml(cors_xml)


def get_all_revisions(session, app, env):
    query = sa.select(
        [
            Revisions.revision_name,
            Revisions.tag,
            Revisions.commit_message,
            Revisions.commit_author,
            Revisions.record_created,
        ]
    ).where(
        sa.and_(
            Revisions.app == app,
            Revisions.deploy_env == env
        )
    ).order_by(
        sa.asc(
            Revisions.id
        )
    )

    revisions = session.execute(query).fetchall()
    res_str = '*{} - {}*\n'.format(app, env)
    if not revisions:
        res_str += "There is no revisions for this app"
        return res_str

    for rev in revisions:
        res_str += '`{} {} {} {} {}`\n'.format(
            rev.revision_name,
            rev.record_created,
            rev.commit_message,
            rev.commit_author,
            rev.tag or "",
        )

    return res_str


def activate(session, commit_sha, env):
    query = sa.select(
        [
            Revisions.s3_bucket_name,
            Revisions.index_html_path,
            Revisions.app
        ]
    ).where(
        sa.and_(
            Revisions.commit_sha == commit_sha,
            Revisions.deploy_env == env
        )
    ).order_by(
        sa.asc(
            Revisions.id
        )
    ).limit(1)
    revision_data = session.execute(query).fetchone()

    # TODO: get keys accoding to env
    conn = boto.connect_s3(aws_access_key_id, aws_secret_access_key)
    bucket = conn.get_bucket(revision_data.s3_bucket_name)

    key = bucket.get_key(revision_data.index_html_path + '/' + 'index.html')
    if key.name:
        bucket.copy_key("index.html", bucket.name, key.name)
        return "Done!"
    else:
        return "There is no such revision."


        # TODO: set up cors if they are need
        # setup_cors(
        #     aws_access_key_id=self.global_config.get('aws_s3_access_key'),
        #     aws_secret_access_key=self.global_config.get(
        #         'aws_s3_secret_access_key'),
        #     aws_storage_bucket_name=self.global_config.get(
        #         'aws_assets_bucket_name'),
        # )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--list', help='All revisions for app')
    parser.add_argument('-a', '--activate', help='Activate revision')

    args = parser.parse_args()

    with SessionContext() as session:
        if args.list:
            print get_all_revisions(session, args.list, "test")

        elif args.activate:
            print activate(session, args.activate, "dev")

        else:
            parser.print_help()
