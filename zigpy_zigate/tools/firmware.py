import urllib.request
import logging
import os
import argparse
import json
from collections import OrderedDict

URL = 'https://api.github.com/repos/fairecasoimeme/ZiGate/releases'
LOGGER = logging.getLogger("ZiGate Firmware")


def get_releases():
    LOGGER.info('Searching for ZiGate firmware')
    releases = OrderedDict()
    r = urllib.request.urlopen(URL)
    if r.status == 200:
        for release in json.loads(r.read()):
            if release.get('draft'):
                continue
            if release.get('prerelease'):
                continue
            for asset in release['assets']:
                if 'pdm' in asset['name'].lower():
                    continue
                if asset['name'].endswith('.bin'):
                    LOGGER.info('Found %s', asset['name'])
                    releases[asset['name']] = asset['browser_download_url']
    return releases


def download(url, dest='/tmp'):
    filename = url.rsplit('/', 1)[1]
    LOGGER.info('Downloading %s to %s', url, dest)
    r = urllib.request.urlopen(url)
    if r.status == 200:
        filename = os.path.join(dest, filename)
        with open(filename, 'wb') as fp:
            fp.write(r.read())
        LOGGER.info('Done')
        return filename
    else:
        LOGGER.error('Error downloading %s %s', r.status, r.reason)


def download_latest(dest='/tmp'):
    LOGGER.info('Download latest firmware')
    releases = get_releases()
    if releases:
        latest = list(releases.keys())[0]
        LOGGER.info('Latest is %s', latest)
        return download(releases[latest], dest)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("command", help="Command to start", choices=["list", "download", "download-latest"])
    parser.add_argument('--url', help="Download URL")
    parser.add_argument('--dest', help="Download folder, default to /tmp", default='/tmp')
    args = parser.parse_args()
    if args.command == 'list':
        for k, v in get_releases().items():
            print(k, v)
    elif args.command == 'download':
        if not args.url:
            LOGGER.error('You have to give a URL to download using --url')
        else:
            download(args.url, args.dest)
    elif args.command == 'download-latest':
        download_latest(args.dest)
