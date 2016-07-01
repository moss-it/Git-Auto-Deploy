import argparse
import datetime
import json
import os
import re
import subprocess
import urllib2

import boto
import yaml

from new_frontend_deploy import settings as ss
from new_frontend_deploy.core.models import Revisions
from new_frontend_deploy.core.session import SessionContext
from new_frontend_deploy.settings import SLACK_URL

AVAILABLE_ENVS = ["dev", "staging", "test", "production"]


class Deploy(object):

    def __init__(self, config_path, app, envs):
        self.config_path = config_path
        self.app = app
        self.envs = [x for x in envs.split(',')
                     if envs and x in AVAILABLE_ENVS] or []

    def get_config(self, app, env):
        if not (self.config_path and os.path.isdir(self.config_path)):
            print 'Wrong config dir!'
            return

        with open(os.path.join(self.config_path, '{}/{}.yml'.format(env, app)),
                  'r') as f:
            project_settings = yaml.load(f)

        if not project_settings:
            raise Exception(
                'There is no {}.yml in provided dir {}/{}'.format(
                    app, self.config_path, env))

        return project_settings

    def create_env_file(self, global_config, env):

        if not global_config:
            # There is no configs for such env
            print "There is no global_config for {}".format(env)
            return False

        config_str = ''
        for key in ss.AWS_S3_KEYS:
            config_str += "{}={}\n".format(key, global_config.get(key))

        config_str += "{}={}\n".format(
            "aws_s3_bucket_prefix",
            self.app + '/' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))

        file_name = ".env.deploy.{}".format(env)
        if os.path.isfile(file_name):
            os.remove(file_name)

        with open(file_name, 'w') as f:
            f.writelines(config_str)

        return True

    @staticmethod
    def send_msg(msg):
        url = SLACK_URL
        data = json.dumps({"text": msg})
        req = urllib2.Request(
            url,
            data,
            {'Content-Type': 'application/json'}
        )
        urllib2.urlopen(req)

    @staticmethod
    def install_ember_packages():

        p = subprocess.Popen(["sudo", "pkgcache", "install", "npm"])
        p.wait()

        p = subprocess.Popen(["sudo", "pkgcache", "install", "-g",
                              "ember-cli@1.13.13"])
        p.wait()

        p = subprocess.Popen(["sudo", "pkgcache", "install", "npm"])
        p.wait()

        p = subprocess.Popen(["sudo", "npm", "install", "bower"])
        p.wait()

        p = subprocess.Popen(["sudo", "chown", "ubuntu:ubuntu",
                              "-R", "/home/ubuntu/.cache/"])
        p.wait()

        p = subprocess.Popen(["sudo", "chown", "ubuntu:ubuntu",
                              "-R", "/home/ubuntu/.config/"])
        p.wait()

        p = subprocess.Popen(["bower", "install"])
        p.wait()

    def update_json_config(self, app_config, global_settings):

        def update_config(config, route, value):
            target = config
            for k in route.split('.')[:-1]:
                target = target[k]
            target[route.split('.')[-1]] = value

        with open('config.json') as f:
            config = json.load(f)

        settings_keys = ss.APPS_SETTINGS_MAPPING.get(app_config['app'], [])

        for constant_var in settings_keys:
            if isinstance(constant_var, tuple):
                project_key, global_key = constant_var
                val = self.get_value_from_mapping(global_key, global_settings,
                                                  app_config)
                update_config(config, project_key, val)
            else:
                mapping_value = self.get_value_from_mapping(
                    constant_var, global_settings, app_config)

                update_config(config, constant_var, mapping_value)

        return config

    def update_project_config(self, app_config, global_config):
        new_json_configuration = self.update_json_config(app_config,
                                                         global_config)
        p = subprocess.Popen(["rm", "config.json"])
        p.wait()

        with open('config.json', 'w') as new_json_config:
            json.dump(new_json_configuration, new_json_config, indent=2)

    @staticmethod
    def get_value_from_mapping(project_key, global_config, project_config):

        mapping_value = ss.UPPER_TO_LOWER_SETTINGS_MAPPINGS.get(project_key)

        if isinstance(mapping_value, tuple):
            fn = mapping_value[-1]
            values = []

            for x in mapping_value[:-1]:
                key_val = project_config.get(x) or global_config.get(x)

                if not key_val:
                    key_val = ""
                    print '{} have no value.Project {}'.format(
                        x, project_config.get('app'))

                values.append(key_val)

            return fn(*values)

        elif mapping_value in project_config.keys():

            return project_config.get(mapping_value)

        return global_config.get(mapping_value)

    @staticmethod
    def public_file_link(bucket_name, key):
        return 'https://%s.s3.amazonaws.com/%s' % (bucket_name, key)

    def refactor_path(self, index_html_path, revision, global_config):
        s3_bucket_name = global_config.get('aws_s3_bucket_name')
        conn = boto.connect_s3(global_config.get("aws_s3_key"),
                               global_config.get("aws_s3_secret_key"))

        bucket = conn.get_bucket(s3_bucket_name)
        key = bucket.get_key(
            index_html_path + '/' + revision)
        content = key.get_contents_as_string()
        pathes = set(re.findall(
            'assets/(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
            content))

        for path in pathes:
            new_path = '{}/{}'.format(index_html_path, path)
            content = content.replace(
                path, self.public_file_link(s3_bucket_name, new_path))

        new_key = bucket.new_key(
            "/{}/index.html".format(index_html_path))
        new_key.content_type = "text/plain"
        new_key.set_contents_from_string(content, num_cb=100)
        new_key.make_public()

    def get_commit_info(self):
        commit_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"])[:-2]

        commit_data = subprocess.check_output(
            ["git", "show", "-s", "--format=%B%%%an%%%ae%%%ci", commit_sha])

        commit_data = [x.replace('\n', " ") for x in commit_data.split("%")
                       if x]

        resp = {"message": commit_data[0],
                "author": commit_data[1],
                "email": commit_data[2],
                "date": commit_data[3],
                "sha": commit_sha}

        commit_info = subprocess.check_output(
            ["git", "show-ref", "--tags"])

        if not commit_info:
            return resp

        commit_info = commit_info.split("\n")
        tag = [x.split("/tags/")[1] for x in commit_info if
               x.startswith(commit_sha)]

        resp.update({"tag": tag[0] if tag else ""})

        return resp

    def run(self):

        with SessionContext() as session:
            pattern = re.compile(r"[A-z]+/[0-9A-z_]+/index.html:[A-z0-9]+")
            for env in self.envs:

                # Retrieve commit info
                commit_data = {}
                try:
                    commit_data = self.get_commit_info()
                except (subprocess.CalledProcessError, Exception) as e:
                    print "Error", e.returncode, e.output

                app_config = self.get_config(self.app, env)
                global_config = self.get_config('global', env)
                revision_data = {
                    "app": self.app,
                    "deploy_env": env,
                    "s3_bucket_name": global_config.get(
                        'aws_s3_bucket_name'),
                    "record_created": datetime.datetime.utcnow(),
                    "record_modified": None,
                    "tag": commit_data.get("tag"),
                    "commit_sha": commit_data.get("sha"),
                    "commit_author": commit_data.get('author'),
                    "commit_date": commit_data.get('date'),
                    "commit_message": commit_data.get('message')
                }

                res = self.create_env_file(global_config, env)

                if not res:
                    revision_data.update(
                        {"status": "failed",
                         "build_log": "Can't create .env file"})
                    new_deploy_data = Revisions(**revision_data)
                    session.add(new_deploy_data)
                    session.commit()
                    return

                try:

                    self.install_ember_packages()

                    self.update_project_config(app_config, global_config)

                    try:

                        output = subprocess.check_output(
                            ["ember", "deploy", env, "--verbose"])

                    except subprocess.CalledProcessError as e:
                        revision_data.update(
                            {"status": "failed",
                             "build_log": "{}".format(e.output)})
                        new_deploy_data = Revisions(**revision_data)
                        session.add(new_deploy_data)
                        session.commit()
                        return

                    revision_data.update({
                        "build_log": output,
                    })

                    index_html_path = re.findall(pattern, output)
                    path = ""
                    revision_name = ""

                    if index_html_path:
                        index_html_path = index_html_path[0].split('/')
                        path = '/'.join((index_html_path[0],
                                         index_html_path[1]))
                        revision_name = index_html_path[-1]

                    if not path or not index_html_path:
                        revision_data.update(
                            {"status": "failed",
                             "build_log": "Can't find path for revision, check build log please"})

                        new_deploy_data = Revisions(**revision_data)
                        session.add(new_deploy_data)
                        session.commit()
                        return

                    try:
                        self.refactor_path(
                            path,
                            revision_name,
                            global_config
                        )
                    except Exception as e:
                        revision_data.update(
                            {"status": "failed",
                             "build_log":
                                 revision_data.get("build_log") + "{}".format(
                                     e.message)})

                        new_deploy_data = Revisions(**revision_data)
                        session.add(new_deploy_data)
                        session.commit()
                        return

                    revision_data.update({
                        "index_html_path": path,
                        "revision_name": revision_name,
                        "status": "success"
                    })

                    new_deploy_data = Revisions(**revision_data)
                    session.add(new_deploy_data)

                    msg = "`{}` :arrow_right: `{}`\n".format(self.app, env)
                    msg += "RELEASE TAG: `{}`\n".format(commit_data.get("tag")) \
                        if commit_data.get("tag") else ""
                    msg += "activate command: `activate {} on {}`\n".format(
                        commit_data.get("sha"),
                        env
                    )
                    msg += "```Commit info:\nsha: {}\ndate: {}\nauthor: {}\nmessage: {}\n```".format(
                        commit_data.get("sha"),
                        commit_data.get("date"),
                        commit_data.get("author"),
                        commit_data.get("message")
                    )
                    try:
                        self.send_msg(msg)
                    except Exception as e:
                        print e.message

                except Exception as e:
                    revision_data.update(
                        {"status": "failed",
                         "build_log": "{}".format(e.message)})
                    new_deploy_data = Revisions(**revision_data)
                    session.add(new_deploy_data)
                    session.commit()

            session.commit()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', help='Path to config directory',
                        required=True)
    parser.add_argument('-e', '--envs', help='Deploy to prod',
                        required=False)
    parser.add_argument('-a', '--app', help='Application',
                        required=False)
    args = parser.parse_args()

    deploy = Deploy(args.config, args.app, args.envs)
    deploy.run()
