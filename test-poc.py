from collections import defaultdict
from io import TextIOWrapper
from typing import TextIO
from urllib.request import urlopen, Request
from urllib.parse import urlparse
import jadn
import json
from jsonschema import validate, draft7_format_checker
from jsonschema.exceptions import ValidationError
import os

"""
Validate OpenC2 commands and responses for profiles stored in local ROOT_DIR or GitHub under ROOT_REPO
Environment variable "GitHubToken" must have a Personal Access Token to prevent rate limiting

/
|-- profile-A
|   |-- schema-A.jadn
|   |-- schema-A.json
|   |-- Good-command
|   |   |-- command.json
|   |   |-- command.json
|   |-- Bad-command
|   |   |-- command.json
|   |-- Good-response
|   |   |-- response.json
|   |-- Bad-response
|   |   |-- response.json
|-- profile-B
|   |-- schema-B.jadn
|   |-- schema-B.json
     ...
"""

VALIDATE_JADN = True    # Use JAON schema if True, JSON schema if False

ROOT_DIR = 'Test'
# ROOT_REPO = 'https://api.github.com/repos/oasis-tcs/openc2-usecases/contents/Actuator-Profile-Schemas/'
ROOT_REPO = 'https://api.github.com/repos/oasis-open/openc2-jadn-software/contents/'
TEST_ROOT = ROOT_DIR          # Select local directory or GitHub root of test tree

AUTH = {'Authorization': f'token {os.environ["GitHubToken"]}'}
# auth = {}


class WebDirEntry:
    """
    Fake os.DirEntry type for GitHub filesystem
    """
    def __init__(self, name, path, url):
        self.name = name
        self.path = path
        self.url = url


def list_dir(dirpath: str) -> dict:
    """
    Return a dict listing the files and directories in a directory on local filesystem or GitHub repo.

    :param dirpath: str - a filesystem path or GitHub API URL
    :return: dict {files: [DirEntry*], dirs: [DirEntry*]}
    Local Filesystem: Each list item is an os.DirEntry structure containing name and path attributes
    GitHub Filesystem: Each list item has name, path, and url (download URL) attributes
    """

    files, dirs = [], []
    u = urlparse(dirpath)
    if all([u.scheme, u.netloc]):
        with urlopen(Request(dirpath, headers=AUTH)) as d:
            for dl in json.loads(d.read().decode()):
                url = 'url' if dl['type'] == 'dir' else 'download_url'
                entry = WebDirEntry(dl['name'], dl[url], dl['url'])
                (dirs if dl['type'] == 'dir' else files).append(entry)
    else:
        with os.scandir(dirpath) as dlist:
            for entry in dlist:
                (dirs if os.path.isdir(entry) else files).append(entry)
    return {'files': files, 'dirs': dirs}


def open_file(fileentry: os.DirEntry) -> TextIO:
    u = urlparse(fileentry.path)
    if all([u.scheme, u.netloc]):
        return TextIOWrapper(urlopen(Request(fileentry.path, headers=AUTH)), encoding='utf8')
    return open(fileentry.path, 'r', encoding='utf8')


def find_tests(dirpath):        # Search for folders containing schemas and test data
    def _ft(dpath, tests):      # Internal recursive search
        dl = list_dir(dpath)    # Get local or web directory listing
        if 'Good-command' in {d.name for d in dl['dirs']}:      # Test data directory found
            tests.append(dpath)
        else:
            for dp in dl['dirs']:
                _ft(dp.path, tests)

    test_list = []          # Initialize, build test list, and return it
    _ft(dirpath, test_list)
    return test_list


def run_test(dpath):         # Check correct validation of good and bad commands and responses
    dl = list_dir(dpath)
    try:
        if VALIDATE_JADN:
            schemas = [f for f in dl['files'] if os.path.splitext(f.name)[1] in ('.jadn', '.jidl')]
            with open_file(schemas[0]) as fp:
                schema = jadn.load_any(fp)
                codec = jadn.codec.Codec(schema, verbose_rec=True, verbose_str=True)
        else:
            schemas = [f for f in dl['files'] if os.path.splitext(f.name)[1] == '.json']
            with open_file(schemas[0]) as fp:
                schema = json.load(fp)
    except IndexError:
        print(f'No schemas found in {dpath}')
        return
    except ValueError as e:
        print(e)
        return
    tcount = defaultdict(int)       # Total instances tested
    ecount = defaultdict(int)       # Error instances
    tdirs = {d.name: d for d in dl['dirs']}
    for cr in ('command', 'response'):
        for gb in ('Good', 'Bad'):
            pdir = f'{gb}-{cr}'
            if pdir in tdirs:
                print(pdir)
                dl2 = list_dir(tdirs[pdir].path)
                for n, f in enumerate(dl2['files'], start=1):
                    print(f'{n:>4} {f.name:<50}', end='')
                    try:
                        if VALIDATE_JADN:
                            crtype = 'OpenC2-Command' if cr == 'command' else 'OpenC2-Response'
                            codec.decode(crtype, json.load(open_file(f)))
                        else:
                            validate({'openc2_' + cr: json.load(open_file(f))}, schema,
                                     format_checker=draft7_format_checker)
                        tcount[pdir] += 1
                        ecount[pdir] += 1 if gb == 'Bad' else 0
                        print()
                    except ValidationError as e:    # JSON Schema validation error
                        tcount[pdir] += 1
                        ecount[pdir] += 1 if gb == 'Good' else 0
                        print(f' Fail: {e.message}')
                    except ValueError as e:         # JADN validation error
                        tcount[pdir] += 1
                        ecount[pdir] += 1 if gb == 'Good' else 0
                        print(f' Fail: {e}')
                    except json.decoder.JSONDecodeError as e:
                        print(f' Bad JSON: {e.msg} "{e.doc}"')
            else:
                print(pdir, 'No tests')
    print('\nValidation Errors:', {k: str(dict(ecount)[k]) + '/' + str(dict(tcount)[k]) for k in tcount})


print(f'Test Data: {TEST_ROOT}, Access Token: ..{AUTH["Authorization"][-4:]}')
for test in find_tests(TEST_ROOT):
    run_test(test)