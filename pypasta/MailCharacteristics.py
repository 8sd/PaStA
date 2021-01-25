"""
PaStA - Patch Stack Analysis

Copyright (c) OTH Regensburg, 2019-2021

Author:
  Ralf Ramsauer <ralf.ramsauer@oth-regensburg.de>
  Sebastian Duda <sebastian@duda.pub>

This work is licensed under the terms of the GNU GPL, version 2.  See
the COPYING file in the top-level directory.
"""

import email
import re

from anytree import LevelOrderIter
from multiprocessing import Pool, cpu_count

from logging import getLogger
log = getLogger(__name__[-15:])

from .Util import mail_parse_date, load_pkl_and_update

MAIL_STRIP_TLD_REGEX = re.compile(r'(.*)\..+')
VALID_EMAIL_REGEX = re.compile(r'.+@.+\..+')

_repo = None
_clustering = None

def email_get_recipients(message):
    recipients = message.get_all('To', []) + message.get_all('Cc', [])
    recipients = list(filter(None, recipients))
    # get_all might return Header objects. Convert them all to strings.
    recipients = [str(x) for x in recipients]

    # Only accept valid email addresses
    recipients = {x[1].lower() for x in email.utils.getaddresses(recipients)
                  if VALID_EMAIL_REGEX.match(x[1])}

    return recipients


def email_get_header_normalised(message, header):
    header = str(message[header] or '').lower()
    header = header.replace('\n', '').replace('\t', ' ')

    return header


def email_get_from(message):
    mail_from = email_get_header_normalised(message, 'From')
    return email.utils.parseaddr(mail_from)


def ignore_tld(address):
    match = MAIL_STRIP_TLD_REGEX.match(address)
    if match:
        return match.group(1)

    return address


def ignore_tlds(addresses):
    return {ignore_tld(address) for address in addresses if address}


class MaintainerMetrics:
    def __init__(self, c):
        self.one_list_and_mtr = False
        self.one_list = False
        self.one_list_or_mtr = False

        # Metric: At least one correct list + at least one correct maintainer
        if (not c.mtrs_has_lists or c.mtrs_has_one_correct_list) and \
           (not c.mtrs_has_maintainers or c.mtrs_has_one_correct_maintainer):
            self.one_list_and_mtr = True

        # Metric: One correct list
        if not c.mtrs_has_lists or c.mtrs_has_one_correct_list:
            self.one_list = True

        # Metric: One correct list or one correct maintainer
        if c.mtrs_has_lists and c.mtrs_has_one_correct_list:
            self.one_list_or_mtr = True
        elif c.mtrs_has_maintainers and c.mtrs_has_one_correct_maintainer:
            self.one_list_or_mtr = True
        if not c.mtrs_has_lists and not c.mtrs_has_maintainers:
            self.one_list_or_mtr = c.mtrs_has_main_list


class MailCharacteristics ():
    def _is_from_bot(self, message):
        email = self.mail_from[1].lower()
        subject = email_get_header_normalised(message, 'subject')
        uagent = email_get_header_normalised(message, 'user-agent')
        xmailer = email_get_header_normalised(message, 'x-mailer')
        x_pw_hint = email_get_header_normalised(message, 'x-patchwork-hint')
        potential_bot = email in POTENTIAL_BOTS

        if email in BOTS:
            return True

        if potential_bot:
            if x_pw_hint == 'ignore':
                return True

            # Mark Brown's bot and lkp
            if subject.startswith('applied'): # Linuxspecific?
                return True

        for md in BOT_REGEX:
            if md['subject'].match(subject) and md['mail'].match(email) and md['u-agent'].match(uagent) and md['next'].match(str(self.is_next)):
                for l in self.lists:
                    if md['list'].match(l):
                        return True

        return False

    def _has_foreign_response(self, repo, thread):
        """
        This function will return True, if there's another author in this
        thread, other than the ORIGINAL author. (NOT the author of this
        email)
        """
        if len(thread.children) == 0:
            return False  # If there is no response the check is trivial

        for mail in list(LevelOrderIter(thread)):
            # Beware, the mail might be virtual
            if mail.name not in repo:
                continue

            this_email = email_get_from(repo.mbox.get_messages(mail.name)[0])[1]
            if this_email != self.mail_from[1]:
                return True
        return False

    @staticmethod
    def _patches_project(patch):
        for affected in patch.diff.affected:
            if True in map(lambda x: affected.startswith(x),
                           ROOT_DIRS) or \
               affected in ROOT_FILES:
                continue

            return False

        return True

    def _analyse_series(self, thread, message):
        if self.is_patch:
            if self.message_id == thread.name or \
               self.message_id in [x.name for x in thread.children]:
                self.is_first_patch_in_thread = True
        elif 'Subject' in message and \
             MailCharacteristics.REGEX_COVER.match(str(message['Subject'])):
            self.is_cover_letter = True

    def list_matches_patch(self, list):
        for lists, _, _ in self.maintainers.values():
            if list in lists:
                return True
        return False

    def __init__(self, repo, maintainers_version, clustering, message_id):
        self.message_id = message_id
        self.is_patch = message_id in repo and message_id not in repo.mbox.invalid
        self.is_stable_review = False
        self.patches_linux = False
        self.has_foreign_response = None
        self.is_upstream = None

        self.linux_version = None

        self.is_cover_letter = False
        self.is_first_patch_in_thread = False
        self.process_mail = False

        # stuff for maintainers analysis
        self.maintainers = dict()
        self.mtrs_has_lists = None
        self.mtrs_has_maintainers = None
        self.mtrs_has_one_correct_list = None
        self.mtrs_has_one_correct_maintainer = None
        self.mtrs_has_maintainer_per_section = None
        self.mtrs_has_list_per_section = None
        self.mtrs_has_main_list = None
        self.maintainer_metrics = None

        message = repo.mbox.get_messages(message_id)[0]
        thread = repo.mbox.threads.get_thread(message_id)
        recipients = email_get_recipients(message)

        self.recipients_lists = recipients & MAILING_LISTS
        self.recipients_other = recipients - MAILING_LISTS

        self.mail_from = email_get_from(message)
        self.subject = email_get_header_normalised(message, 'Subject')
        self.date = mail_parse_date(message['Date'])

        self.lists = repo.mbox.get_lists(message_id)
        self.is_next = self._is_next()

        self.is_from_bot = self._is_from_bot(message)
        self._analyse_series(thread, message)

        if self.is_patch:
            patch = repo[message_id]
            self.patches_linux = self._patches_project(patch)
            self.is_stable_review = self._is_stable_review(message, patch)

            # We must only analyse foreign responses of patches if the patch is
            # the first patch in a thread. Otherwise, we might not be able to
            # determine the original author of a thread. Reason: That mail
            # might be missing.
            if self.is_first_patch_in_thread:
                self.has_foreign_response = self._has_foreign_response(repo, thread)

            # Even if the patch does not patch Linux, we can assign it to a
            # appropriate version
            self.linux_version = repo.linux_patch_get_version(patch)
            if self.patches_linux:
                if clustering is not None:
                    self.is_upstream = len(clustering.get_upstream(message_id)) != 0

                self.process_mail = True in [process in self.subject for process in PROCESSES]

                if maintainers_version is not None:
                    maintainers = maintainers_version[self.linux_version]
                    self._get_maintainer(maintainers, patch)



def load_mail_characteristics(config, clustering,
                                    ids, mail_characteristics_loader):
    repo = config.repo

    MAILING_LISTS = config.mailinglists
    ROOT_FILES = config.root_files
    ROOT_DIRS = config.root_dirs

    def _load_characteristics(ret):
        if ret is None:
            ret = dict()

        missing = ids - ret.keys()
        if len(missing) == 0:
            return ret, False

        global _repo, _clustering
        _clustering = clustering
        _repo = repo
        p = Pool(processes=int(cpu_count()), maxtasksperchild=1)

        missing = p.map(mail_characteristics_loader, missing, chunksize=1000)
        missing = dict(missing)
        print('Done')
        p.close()
        p.join()
        _repo = None
        _clustering = None

        return {**ret, **missing}, True

    log.info('Loading/Updating linux patch characteristics...')
    characteristics = load_pkl_and_update(config.f_characteristics_pkl,
                                          _load_characteristics)

    return characteristics