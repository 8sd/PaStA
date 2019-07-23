"""
PaStA - Patch Stack Analysis

Copyright (c) BMW Cat It, 2019

Author:
  Sebastian Duda <sebastian.duda@fau.de>

This work is licensed under the terms of the GNU GPL, version 2. See
the COPYING file in the top-level directory.
"""

import datetime
import math
import os
import pickle
import subprocess

from dateutil import parser
from logging import getLogger
from multiprocessing import Pool, cpu_count
from tqdm import tqdm

_repo = ''
_log = getLogger(__name__[-15:])
_tag = ''
_tags = ''

_analyzed_files = dict()

get_maintainers_args = ['perl', '../../../tools/get_maintainer.pl', '--subsystem', '--status', '--separator', ';;']


def patch_date_extractor(patch):
    try:
        return _repo[patch].date
    except KeyError:
        return datetime.datetime.utcnow()


def execute_get_maintainers_per_file(file):
    if file in _analyzed_files:
        return _analyzed_files[file]
    if file is '':
        raise ValueError('File not found')

    p = subprocess.Popen(get_maintainers_args + [file],
                         cwd=os.path.dirname(os.path.realpath(__file__)) + '/../resources/linux/repo/',
                         stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    get_maintainer_pipes = p.communicate()

    get_maintainer_out = get_maintainer_pipes[0].decode("utf-8")
    if get_maintainer_out is '':
        error = get_maintainer_pipes[1].decode("utf-8")
        if 'not found' in error:
            file = file[0:file.rfind('/')]
            get_maintainer_out = execute_get_maintainers_per_file(file)
    _analyzed_files[file] = get_maintainer_out
    return get_maintainer_out


def run_scripts (patch_id):
    global _analyzed_files
    subsystems_with_stati = set()
    maintainers = set()
    supporter = set()
    odd = set()
    reviewer = set()
    lists = set()

    for file in _repo[patch_id].diff.affected:
        try:
            out = execute_get_maintainers_per_file(file)
        except ValueError:
            return patch_id, None

        lines = out.split('\n')

        for address in lines[0].split(';;'):
            if address is '':
                continue
            elif 'maintain' in address:
                maintainers.add(address)
            elif 'supporter' in address:
                supporter.add(address)
            elif 'list' in address:
                lists.add(address)
            elif 'odd fixer' in address:
                odd.add(address)
            elif 'reviewer' in address:
                reviewer.add(address)

        try:
            stati = lines[1].split(';;')
            subsystems = lines[2].split(';;')
        except IndexError:
            pass

        t = 'THE REST', 'Buried alive in reporters'
        subsystems_with_stati.add(t)
        try:
            subsystems.remove('THE REST')
        except ValueError:
            pass

        try:
            stati.remove('Buried alive in reporters')
        except ValueError:
            pass

        try:
            subsystems.remove('ABI/API')
        except ValueError:
            pass

        for i in range(1, len(subsystems) + 1):
            t = ()
            try:
                t = subsystems[-i], stati[-i]
            except IndexError:
                t = subsystems[-i], stati[0]
            subsystems_with_stati.add(t)

    return patch_id, {'version': _tag, 'maintainers': maintainers, 'supporter': supporter, 'odd fixer': odd,
                      'reviewer': reviewer, 'lists': lists, 'subsystem': subsystems_with_stati}


def match_tag_patch(patch_id):
    try:
        date_of_mail = parser.parse(_repo.mbox.get_messages(patch_id)[0]['Date'])
    except:
        date_of_mail = datetime.datetime.utcnow()
    tag_of_patch = ''
    for (tag, timestamp) in _tags:
        if timestamp > date_of_mail:
            break
        tag_of_patch = tag
    return tag_of_patch, patch_id


def get_maintainers(config, prog, argv):
    global _log
    if config.mode != config.Mode.MBOX:
        _log.error('Only works in Mbox mode!')
        return -1

    global _repo
    global _tag
    global _tags
    global _analyzed_files

    _config = config

    _repo = config.repo
    f_cluster, _clusters = config.load_cluster(must_exist=True)
    _clusters.optimize()

    _log.info('Loading patches…')
    _patches = _clusters.get_untagged()
    # patches_sorted = sorted(_patches, key=lambda p: patch_date_extractor(p))

    _log.info('Parsing tags file')
    tags = list()
    patches_by_version = dict()
    tags_file = open('resources/linux/tags', 'r')
    for line in tags_file:
        tag = line.split('\t')[0]
        tags.append((tag, parser.parse(line.split('\t')[1][:-1])))

        patches_by_version[tag] = set()

    _tags = sorted(tags, key=lambda x: x[1])

    _log.info('Match patches and tags…')
    # parallel
    p = Pool(processes=cpu_count(), maxtasksperchild=10)
    return_value = p.map(match_tag_patch, tqdm(_patches), 10)
    for tag, result in return_value:
        patches_by_version[tag].add(result)

    result = dict()
    for tag in tags:
        tag = tag[0]
        if len(patches_by_version[tag]) == 0:
            continue
        # checkout git
        _log.info('Checking out tag: ' + tag)
        _repo.repo.checkout('refs/tags/' + tag)
        _tag = tag
        _analyzed_files = dict()

        # parallel
        return_value = p.map(run_scripts, tqdm(patches_by_version[tag]), 10)
        for patch, res in return_value:
            result[patch] = res

    # save pkl
    _log.info('Saving pickle…')
    pickle.dump(result, open('maintaiers.pkl', 'wb'))

    _log.info('Cleaning up…')
    p.close()
    p.join()
