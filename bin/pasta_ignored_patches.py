"""
PaStA - Patch Stack Analysis

Copyright (c) BMW Cat It, 2019

Author:
  Sebastian Duda <sebastian.duda@fau.de>

This work is licensed under the terms of the GNU GPL, version 2. See
the COPYING file in the top-level directory.
"""

import re
import datetime
import subprocess
import pickle
import os

from logging import getLogger
from anytree import LevelOrderIter
from tqdm import tqdm
from dateutil import parser
from multiprocessing import Pool, cpu_count

import pandas as pd

import tools.gender.gender_guesser.detector as gender
import tools.ethnicity.ethnicity.ethnicity as ethnicity

__check_for_wrong_maintainer = False
__check_for_applicability = False

_config = None
_log = getLogger(__name__[-15:])
_repo = None
_clusters = None
_statistic = {
    'ignored': set(),
    'analyzed patches': set(),
    'ignored patch groups': set(),
    'not ignored patch groups': set(),

    'too old': set(),
    'foreign response': set(),
    'process': set(),

    'key error': set(),
    'error patch series': set(),
    'key error patch set': set(),
    'error get maintainer': set()
}
_patches = None
_threads = None
__last_tag = None


def write_cell(file, string):
    string = str(string).replace('\'', '`').replace('"', '`').replace('\n', '|').replace('\t', ' ').replace('=', '-')
    file.write(string + '\t')


def write_dict_list(_list, name):
    f = open(name, 'w')
    for k in _list[0].keys():
        write_cell(f, k)
    f.write('\n')
    for data in _list:
        for k in data.keys():
            write_cell(f, data[k])
        f.write('\n')


def write_dict_to_file_as_pandas(_list, name):
    if not isinstance(_list, list):
        raise TypeError

    df = pd.DataFrame(_list)
    pickle.dump(df, open(name, 'wb'))


def patch_is_sent_to_wrong_maintainer(maintainers, patch):
    msgs = _repo.mbox.get_messages(patch)
    if not msgs:
        return False
    msg = msgs[0]
    if not msg:
        return False

    to = msg['To'] if msg['To'] else ''
    cc = msg['Cc'] if msg['Cc'] else ''

    if maintainers:
        for maintainer in maintainers:
            if maintainer not in to and \
                    maintainer not in cc:
                return True
    else:
        _statistic['error get maintainer'].add(patch)
    return False


def patch_is_not_applicable(patch):
    pass


def write_and_print_statistic():
    log = getLogger('Statistics')
    for key, value in _statistic.items():
        file_name = (datetime.datetime.now().strftime('%Y.%m.%d-%H:%M_') + str(key) + ".out").replace(' ', '_')
        if type(value) is str:
            log.info(str(key) + ': ' + value)
        elif type(value) is set:
            log.info(str(key) + ': ' + str(len(value)))
        elif type(value) is dict:
            log.info(str(key) + ': ' + str(len(value)))
        else:
            log.info(str(key) + ': ' + str(value))


def get_author_of_msg(msg):
    email = _repo.mbox.get_messages(msg)[0]
    return email['From']


def patch_has_foreign_response(patch):
    if len(_threads.get_thread(patch).children) == 0:
        return False  # If there is no response the check is trivial

    author = get_author_of_msg(patch)

    for mail in list(LevelOrderIter(_threads.get_thread(patch))):
        this_author = get_author_of_msg(mail.name)
        if this_author is not author:
            return True
    return False


def is_single_patch_ignored(patch):
    try:
        patch_mail = _repo[patch]
    except KeyError:
        _statistic['key error'].add(patch)
        return False

    if _config.time_frame < patch_mail.date:
        _statistic['too old'].add(patch)  # Patch is too new to be analyzed
        return False

    if patch_has_foreign_response(patch):
        _statistic['foreign response'].add(patch)
        return False

    if 'linux-next' in patch_mail.mail_subject or 'git pull' in patch_mail.mail_subject.lower():
        _statistic['process'].add(patch)
        return None

    _statistic['ignored'].add(patch)
    return True


def get_versions_of_patch(patch):
    return _clusters.get_untagged(patch)


def is_part_of_patch_set(patch):
    try:
        return re.search(r'[0-9]+/[0-9]+\]', _repo[patch].mail_subject) is not None
    except KeyError:
        _statistic['key error patch set'].add(patch)
        return False


def get_patch_set(patch):
    result = set()
    result.add(patch)
    thread = _threads.get_thread(patch)

    if thread.children is None:
        return result

    if not is_part_of_patch_set(patch):
        return result

    cover = thread  # this only works if
    result.add(cover.name)

    # get leaves of cover letter
    for child in cover.children:
        result.add(child.name)
    return result


def get_related_patches(patch):
    patches = get_versions_of_patch(patch)
    patches |= get_patch_set(patch)
    return patches


def analyze_patch(patch):
    if patch in _statistic['analyzed patches']:
        return

    patches = get_related_patches(patch)

    _statistic['analyzed patches'] |= patches

    for patch in patches:
        ignored = is_single_patch_ignored(patch)
        if ignored is None:
            try:
                _statistic['all patches'].remove(patch)
            except KeyError:
                pass

            continue
        if not ignored:
            _statistic['not ignored patch groups'] |= patches
            return

    _statistic['ignored patch groups'] |= patches


def patch_date_extractor(patch):
    try:
        return _repo[patch].date
    except KeyError:
        return datetime.datetime.utcnow()

def gather_data_of_single_patch(patch):
    global _maintainers

    category = None
    email = _repo.mbox.get_messages(patch)[0]
    author = email['From'].replace('\'', '"')
    mail_traffic = sum(1 for _ in LevelOrderIter(_threads.get_thread(patch)))
    first_mail_in_thread = _threads.get_thread(patch).name
    maintainers = None
    helping = None
    lists = None
    subsystems = None

    try:
        date_of_mail = parser.parse(email['Date'])

        tag = '' #TODO use get_maintainers.pkl
        rc = 'rc' in tag

        if rc:
            rcv = re.search('-rc[0-9]+', tag).group()[3:]
            version = re.search('v[0-9]+\.', tag).group() + '%02d' % int(re.search('\.[0-9]+', tag).group()[1:])
        else:
            rcv = 0
            version = re.search('v[0-9]+\.', tag).group() + '%02d' % (
                    int(re.search('\.[0-9]+', tag).group()[1:]) + 1)
    except AttributeError:
        rcv = 'error'
        version = 'error'

    # use get_maintainers pkl
    get_maintainers = _maintainers[patch]
    if (get_maintainers is not None):
        maintainers = get_maintainers['maintainers']
        helping = get_maintainers['supporter'] | get_maintainers['odd fixer'] | get_maintainers['reviewer']
        lists = get_maintainers['lists']
        subsystems = get_maintainers['subsystem']

    if email['cc'] is not None:
        recipients = email['To'] + email['cc']
    else:
        recipients = email['To']

    return {
        'id': patch,
        'subject': email['Subject'],
        'from': author,
        'ignored': patch in _statistic['ignored patch groups'],
        'upstream': patch in _statistic['upstream patches'],
        'category': category,
        '#LoC': _repo[patch].diff.lines,
        '#Files': len(_repo[patch].diff.affected),
        '#recipients without lists': len(re.findall('<', recipients)),
        '#recipients': len(re.findall('@', recipients)),
        'DoW': _repo[patch].date.weekday(),
        'timestamp': _repo[patch].date.timestamp(),
        'after version': tag,
        'rcv': rcv,
        'kernel version': version,
        'maintainers': maintainers,
        'helping': helping,
        'lists': lists,
        'subsystems': subsystems,
        'mailTraffic': mail_traffic,
        'firstMailInThread': first_mail_in_thread
    }


def evaluate_result():
    all_authors = set()
    author_ignored = dict()
    author_not_ignored = dict()
    result_patch_data = list()

    # Use this script to generate ne new tags file
    # git log --tags --simplify-by-decoration --pretty='format:%D%x09%cD' | awk -F '\t' '/tag/ {print $1"\t"$2}' \
    # | sed 's/tag: //g' > ../tags
    _log.info('Evaluating Patches…')
    # do parallelized stuff
    p = Pool(processes=cpu_count(), maxtasksperchild=10)
    return_value = p.map(gather_data_of_single_patch, tqdm(_statistic['all patches']), 10)

    write_dict_list(return_value, 'patches.tsv')
    write_dict_to_file_as_pandas(return_value, 'patches.pkl')
    _log.info('  ↪ done')

    # Needed for author analysis
    _log.info('Collecting authors…')
    for patch in tqdm(_statistic['all patches']):
        email = _repo.mbox.get_messages(patch)[0]
        author = email['From'].replace('\'', '"')
        if author in all_authors:
            if patch in _statistic['ignored patch groups']:
                author_ignored[author] += 1
            else:
                author_not_ignored[author] += 1
        else:
            all_authors.add(author)
            if patch in _statistic['ignored patch groups']:
                author_ignored[author] = 1
                author_not_ignored[author] = 0
            else:
                author_ignored[author] = 0
                author_not_ignored[author] = 1
    # End of author analysis

    # author
    result_author_data = list()
    gender_detector = gender.Detector()
    ethnicity_detector = ethnicity.Ethnicity().make_dicts()
    _log.info('  ↪ done')

    _log.info('Evaluating authors…')
    for author in tqdm(all_authors):
        try:
            domain = re.search('@[\w\-\.]+', author).group()[1:]
        except:
            domain = 'error.error'
            _log.warning(author)

        company = domain
        if 'gmail.com' in company or 'gmx.' in company or 'outlook.' in company:
            company = ''
        elif 'amd.com' in company:
            company = 'AMD'
        elif 'arm.com' in company:
            company = 'ARM'
        elif 'codeaurora.org' in company:
            company = 'Code Aurora'
        elif 'huawei.com' in company:
            company = 'Huawei'
        elif 'intel.com' in company:
            company = 'Intel'
        elif 'ibm.com' in company:
            company = 'IBM'
        elif 'kernel.org' in company:
            company = 'KERNEL'
        elif 'linaro.org' in company:
            company = 'Linaro'
        elif 'nxp.com' in company:
            company = 'NXP'
        elif 'oracle.com' in company:
            company = 'Oracle'
        elif 'redhat.com' in company:
            company = 'Red Hat'
        elif 'suse.' in company:
            company = 'Suse'
        elif 'xilinx.com' in company:
            company = 'Xilinx'
        elif 'zytor.com' in company:
            company = 'Zytor'

        try:
            country = re.findall('\.[\w]+', domain)[-1][1:]
            if 'com' in country \
                    or 'net' in country \
                    or 'org' in country \
                    or 'edu' in country \
                    or 'io' in country \
                    or 'name' in country \
                    or 'xyz' in country:
                country = ''
        except:
            _log.warning(author)
            country='error'

        name = re.search('\w[\w\s.-]+\w', author)
        if name is None:
            print(author)
            name = ""
        else:
            name = name.group()[:-1]

        ethnicity_result = ethnicity_detector.get([name])['Ethnicity'][0]

        gender_result = gender_detector.get_gender(name)
        if 'tip-bot' in author:
            gender_result = 'Bot'
            ethnicity_result = 'Bot'

        result_author_data.append({
            'Author': author,
            'Ignored': author_ignored[author],
            'Not Ignored': author_not_ignored[author],
            'Company': company,
            'Country': country,
            'Ethnicity': ethnicity_result,
            'Gender': gender_result
        })

    write_dict_list(result_author_data, 'authors.tsv')
    _log.info('  ↪ done')


def ignored_patches(config, prog, argv):
    global _log
    if config.mode != config.Mode.MBOX:
        _log.error('Only works in Mbox mode!')
        return -1

    global _config
    global _repo
    global _clusters
    global _statistic
    global _patches
    global _threads
    global _maintainers
    _maintainers = pickle._load(open('maintainers.pkl', 'rb'))

    _config = config

    _repo = config.repo
    f_cluster, _clusters = config.load_cluster(must_exist=True)
    _clusters.optimize()

    _statistic['all patches'] = _clusters.get_untagged()

    _patches = _clusters.get_not_upstream_patches()

    _statistic['upstream patches'] = _statistic['all patches'] - _patches

    _threads = _repo.mbox.load_threads()
    _log.info('Analyzing patches…')
    for patch in tqdm(_patches):
        analyze_patch(patch)

    _statistic['analyzed patches'] = _patches

    write_and_print_statistic()
    evaluate_result()

    return True

