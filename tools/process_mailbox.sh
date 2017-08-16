#!/bin/bash

# Copyright (c) OTH Regensburg, 2017
#
# Author:
#   Ralf Ramsauer <ralf.ramsauer@othr.de>
#
# This work is licensed under the terms of the GNU GPL, version 2.  See
# the COPYING file in the top-level directory.

function die {
	echo "$@" 1>&2
	exit -1;
}

if [ "$#" -ne 2 ]; then
	echo "Usage: $0 mailbox_file destination_directory"
	echo
	echo "This script splits up a mailbox file into seperate mail"
	echo "files, placed into date-separated subdirectories."
	exit 1
fi

BASEDIR=${2}
mkdir -p $BASEDIR || die "Unable to create basedir"

formail -n $(nproc) -s <${1} ./process_mail.sh ${BASEDIR}