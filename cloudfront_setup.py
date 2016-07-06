import argparse
import json
import os
import time
import boto3
import yaml
from botocore.exceptions import ClientError

from new_frontend_deploy import settings


class CloudFrontDeploy(object):
    def __init__(
            self,
            domain_name,
            aws_region,
            aws_access_key_id,
            aws_secret_access_key
    ):
        self.domain_name = domain_name
        self.certificate_id = None
        aws_settings = {
            "region_name": aws_region,
            "aws_access_key_id": aws_access_key_id,
            "aws_secret_access_key": aws_secret_access_key,
        }
        self.s3 = boto3.client("s3", **aws_settings)
        self.iam = boto3.client("iam", **aws_settings)
        self.cf = boto3.client("cloudfront", **aws_settings)
        self.invalidate = True

    def create_s3_website(self):
        if self.domain_name not in \
                [bucket['Name'] for bucket in
                 self.s3.list_buckets()['Buckets']]:
            print "Create bucket {}...".format(self.domain_name)
            self.s3.create_bucket(
                Bucket=self.domain_name
            )

        print "Apply bucket policy.."
        self.s3.put_bucket_policy(
            Bucket=self.domain_name,
            Policy=json.dumps({
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "AddPerm",
                        "Effect": "Allow",
                        "Principal": "*",
                        "Action": "s3:GetObject",
                        "Resource": "arn:aws:s3:::{}/*".format(
                            self.domain_name)
                    }
                ]
            }, indent=4)
        )

        print "Set website configuration..."
        self.s3.put_bucket_website(
            Bucket=self.domain_name,
            WebsiteConfiguration={
                'IndexDocument': {
                    'Suffix': 'index.html'
                },
                'RoutingRules': [
                    {
                        'Condition': {
                            'HttpErrorCodeReturnedEquals': '404',
                        },
                        'Redirect': {
                            'HostName': self.domain_name,
                            'ReplaceKeyPrefixWith': '#!/',
                        }
                    },
                ]
            }
        )

        print "Enable redirect"
        if "www." + self.domain_name not in [
            bucket['Name'] for bucket in self.s3.list_buckets()['Buckets']
            ]:
            print "Create bucket {}".format("www." + self.domain_name)
            self.s3.create_bucket(
                ACL='private',
                Bucket="www." + self.domain_name
            )
        self.s3.put_bucket_website(
            Bucket="www." + self.domain_name,
            WebsiteConfiguration={
                'RedirectAllRequestsTo': {
                    'HostName': self.domain_name,
                },
            }
        )

    def upload_certificate(self, debug=False):
        try:
            self.iam.upload_server_certificate(
                Path='/cloudfront/{}/'.format(self.domain_name),
                ServerCertificateName=self.domain_name,
                CertificateBody=settings.CF_SSL_CERT_DEV_TEXT if debug else settings.CF_SSL_CERT_TEXT,
                PrivateKey=settings.SSL_KEY_DEV_TEXT if debug else settings.SSL_KEY_TEXT,
                CertificateChain=settings.CF_SSL_CERT_DEV_CHAIN if debug else settings.CF_SSL_CERT_CHAIN
            )
        except ClientError as ce:
            print (str(ce))

        response = self.iam.get_server_certificate(
            ServerCertificateName=self.domain_name
        )
        self.certificate_id = response[
            'ServerCertificate'
        ][
            'ServerCertificateMetadata'
        ][
            'ServerCertificateId'
        ]

    def create_cloudfront_distribution(self, price_class):
        ids = {
            origin['Id']: {
                'domain_name': item['DomainName'],
                'id': item['Id'],
            }
            for item in
            self.cf.list_distributions()['DistributionList']['Items']
            for origin in item['Origins']['Items']

            }
        self.cloudfront_domain = ids.get(
            "S3-{}".format(self.domain_name), {}
        ).get('domain_name')

        self.cloudfront_id = ids.get(
            "S3-{}".format(self.domain_name), {}
        ).get('id')

        print "CF domain {}".format(self.cloudfront_domain)
        if not self.cloudfront_domain:
            self.invalidate = False
            print "Create CF domain "
            distribution_config = {
                'Aliases': {
                    'Quantity': 1,
                    'Items': [self.domain_name]
                },
                "Comment": "",
                "Origins": {
                    "Items": [
                        {
                            "S3OriginConfig": {
                                "OriginAccessIdentity": ""
                            },
                            "Id": "S3-{}".format(self.domain_name),
                            "DomainName": "{}.s3.amazonaws.com".format(
                                self.domain_name),
                        }
                    ],
                    "Quantity": 1
                },
                "DefaultRootObject": "index.html",
                "PriceClass": price_class or "PriceClass_100",
                "Enabled": True,
                "DefaultCacheBehavior": {
                    "TrustedSigners": {
                        "Enabled": False,
                        "Quantity": 0
                    },
                    "TargetOriginId": "S3-{}".format(self.domain_name),
                    "ViewerProtocolPolicy": "redirect-to-https",
                    "ForwardedValues": {
                        "Cookies": {
                            "Forward": "none"
                        },
                        "QueryString": False
                    },
                    "AllowedMethods": {
                        "Items": [
                            "HEAD",
                            "GET",
                            "OPTIONS"
                        ],
                        "CachedMethods": {
                            "Items": [
                                "HEAD",
                                "GET"
                            ],
                            "Quantity": 2
                        },
                        "Quantity": 3
                    },
                    "MinTTL": 0,
                    "Compress": True
                },
                "CallerReference": str(int(time.time())),
                "ViewerCertificate": {
                    "SSLSupportMethod": "sni-only",
                    "MinimumProtocolVersion": "TLSv1",
                    "IAMCertificateId": self.certificate_id,
                    "Certificate": self.certificate_id,
                    "CertificateSource": "iam"
                }

            }
            print distribution_config
            response = self.cf.create_distribution(
                DistributionConfig=distribution_config
            )
            self.cloudfront_domain = response['Distribution']['DomainName']
            self.cloudfront_id = response['Distribution']['Id']

    def setup_cors(self):
        print "Setup cors"
        self.s3.put_bucket_cors(
            Bucket=self.domain_name,
            CORSConfiguration={
                'CORSRules': [
                    {
                        'AllowedMethods': [
                            'GET',
                        ],
                        'AllowedOrigins': [
                            '*.collectriumdev.com',
                            '*.collectrium.com',

                        ],
                    },
                ]
            },

        )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    # example - path/dev/
    parser.add_argument('-c', '--config', help='Config path', required=True)
    parser.add_argument('-a', '--app', help='App name', required=True)

    args = parser.parse_args()
    try:
        if not (args.config and os.path.isdir(args.config)):
            raise Exception('Wrong config dir!')

        with open(os.path.join(args.config, 'global.yml')) as f:
            global_settings = yaml.load(f)

        if not global_settings:
            raise Exception(
                'There is no global.yml in provided dir '.format(args.config))

        dpl = CloudFrontDeploy(
            domain_name=global_settings[args.app],
            aws_region=global_settings['aws_s3_region'],
            aws_access_key_id=global_settings['aws_s3_key'],
            aws_secret_access_key=global_settings['aws_s3_secret_key'],
        )

        dpl.create_s3_website()
        dpl.upload_certificate(debug=global_settings['debug'])
        dpl.create_cloudfront_distribution(
            price_class=global_settings["aws_cloudfront_price_class"])
        dpl.setup_cors()

    except Exception as e:
        print e.message
