import boto
import sqlalchemy as sa

from new_frontend_deploy.core.models import Revisions
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
        return "There is no revisions for this app"

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

    # TODO: get keys accoding to env
    conn = boto.connect_s3(aws_access_key_id, aws_secret_access_key)
    bucket = conn.get_bucket(revision_data.s3_bucket_name)

    key = bucket.get_key(revision_data.index_html_path + '/' + 'index.html')
    if key.name:
        bucket.copy_key("index.html", bucket.name, key.name,
                        metadata={'Content-Type': 'text/html'})
        return "Done!"
    else:
        return "There is no such revision."
