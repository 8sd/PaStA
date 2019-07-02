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

from logging import getLogger
from anytree import LevelOrderIter
from tqdm import tqdm
from dateutil import parser

import tools.gender.gender_guesser.detector as gender
import tools.ethnicity.ethnicity.ethnicity as ethnicity

__check_for_wrong_maintainer = True
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

    'key error': set(),
    'error patch series': set(),
    'key error patch set': set()
}
_patches = None
_threads = None


def write_cell(file, string):
    string = str(string).replace('\'', '"').replace('\n', '|').replace('\t', ' ').replace('=', '-')
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


def patch_is_sent_to_wrong_maintainer(patch):
    affected = _repo.mbox[patch].diff.affected
    maintainers = set()

# TODO: Check out for month of submission
    for file in affected:
        get_maintainer = subprocess.Popen(['perl', 'scripts/get_maintainer.pl', file], cwd='resources/linux/repo/',
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        get_maintainer_out = get_maintainer.communicate()[0]
        maintainers |= set(re.findall(r'<[a-z\.\-]+@[a-z\.\-]+>', get_maintainer_out.decode("utf-8")))
        # Maybe we ought to check if there is one correct maintainer per file?

    for maintainer in maintainers:
        if maintainer not in _repo.mbox.get_messages(patch)[0]['To']:
            return True
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
            if len(value) < 100000:
                f = open(file_name, 'w')
                for i in value:
                    f.write(str(i) + '\n')
                f.close()
        elif type(value) is dict:
            log.info(str(key) + ': ' + str(len(value)))
            if len(value) < 100000:
                f = open(file_name, 'w')
                for k, v in value.items():
                    f.write(str(k) + '\t' + str(v) + '\n')
                f.close()
        else:
            log.info(str(key) + ': ' + str(value))


def get_author_of_msg(patch):
    return _repo.mbox[patch].author_name


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

    _statistic['ignored'].add(patch)
    return True


def get_versions_of_patch(patch):
    return _clusters.get_untagged(patch)


def is_part_of_patch_set(patch):
    try:
        return re.search(r'[0-9]+/[0-9]+\]', _repo.mbox[patch].subject) is not None
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
            continue
        if not ignored:
            _statistic['not ignored patch groups'] |= patches
            return

    _statistic['ignored patch groups'] |= patches


def evaluate_result():
    _log.info('Sorting ' + str(len(_statistic['all patches'])) + ' Patches…')
    patches_sorted = sorted(_statistic['all patches'])
    _log.info('  ↪ done')

    all_authors = set()
    author_ignored = dict()
    author_not_ignored = dict()
    # patches_sorted = sorted(_statistic['all patches'])

    result_patch_data = list()

    # Use this script to generate ne new tags file
    # git log --tags --simplify-by-decoration --pretty='format:%D%x09%cD' | awk -F '\t' '/tag/ {print $1"\t"$2}' \
    # | sed 's/tag: //g' > ../tags
    _log.info('Loading Tags')
    tags = list()
    tags_file = open('resources/linux/tags', 'r')
    for line in tags_file:
        tag = line.split('\t')[0]
        tags.append((tag, parser.parse(line.split('\t')[1][:-1]), 'rc' in line))

    tags = sorted(tags, key=lambda x: x[1])
    _log.info('  ↪ done')
    
    _log.info('Evaluating Patches…')
    for patch in tqdm(patches_sorted):
        email = _repo.mbox.get_messages(patch)[0]
        author = email['From'].replace('\'', '"')
        if 'linux-next' in email['Subject']:  # Category
            category = 'Linux next'
        elif 'git pull' in email['Subject'].lower():
            category = 'Pull Request'
        else:
            category = ''
            if __check_for_wrong_maintainer and patch_is_sent_to_wrong_maintainer(patch):
                category += 'Wrong Maintainer '
            elif __check_for_applicability and patch_is_not_applicable(patch):
                category += 'Not Applicable'

        for (tag, timestamp, rc) in tags:
            date_of_mail = parser.parse(email['Date'])
            if timestamp > date_of_mail:
                break
            tag_of_patch = tag
            if rc:
                rcv = re.search('-rc[0-9]+', tag).group()[3:]
            else:
                rcv = 0
            version = re.search('[0-9v\.]+', tag).group()

        try:
            result_patch_data.append({
                'id': patch,
                'subject': email['Subject'],
                'from': author,
                'ignored': patch in _statistic['ignored patch groups'],
                'upstream': patch in _statistic['upstream patches'],
                'category': category,
                '#LoC': _repo.mbox[patch].diff.lines,
                '#Files': len(_repo.mbox[patch].diff.affected),
                'DoW': _repo.mbox[patch].date.weekday(),
                'ToD': _repo.mbox[patch].date.hour + (_repo.mbox[patch].date.minute / 60),
                'Month': _repo.mbox[patch].date.month,
                'Year': _repo.mbox[patch].date.year,
                'after Version': tag_of_patch,
                'rcv': rcv,
                'Kernel version': version
            })
        except KeyError:
            pass

        # Needed for author analysis
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

    write_dict_list(result_patch_data, 'patches.tsv')
    _log.info('  ↪ done')

    # author
    result_author_data = list()
    gender_detector = gender.Detector()
    ethnicity_detector = ethnicity.Ethnicity().make_dicts()

    _log.info('Evaluating authors…')
    for author in tqdm(all_authors):
        domain = re.search('@[\w\-\.]+', author).group()[1:]

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

        country = re.findall('\.[\w]+', domain)[-1][1:]
        if 'com' in country \
                or 'net' in country \
                or 'org' in country \
                or 'io' in country \
                or 'name' in country \
                or 'xyz' in country:
            country = ''

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

    _config = config

    _repo = config.repo
    f_cluster, _clusters = config.load_patch_groups(must_exist=True)
    _clusters.optimize()

    _statistic['all patches'] = _clusters.get_tagged() | _clusters.get_untagged()
    _statistic['upstream patches'] = _clusters.get_tagged()

    _patches = _clusters.get_not_upstream_patches()

    _statistic['upstream patches'] = _statistic['all patches'] - _patches

    _threads = _repo.mbox.load_threads()

    _log.info('Analyzing patches…')
    for patch in tqdm(_patches):
        analyze_patch(patch)

    _statistic['analyzed patches'] = _patches

    # write_and_print_statistic()
    evaluate_result()

    return True

